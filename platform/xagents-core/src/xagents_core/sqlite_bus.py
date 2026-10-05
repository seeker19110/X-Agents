"""Bus bền vững trên SQLite, dùng chung hai công ty (K3.5c của ADR gốc 0001).

**Vì sao bước này là "lấy bản company" thật, khác cả K3.5a lẫn K3.5b.** `difflib` hai file cho **0.442** —
cao nhất trong ba module của K3.5, và con số ấy đúng: hai bên cùng một `_DDL`, cùng cách nạp lại `_log` khi mở,
cùng câu `INSERT`, cùng `replay` ghép `WHERE`. Chỗ lệch không phải hai miền (K3.5a) cũng không phải một bên
thiếu cả cơ chế (K3.5b), mà là **company đã đi xa hơn trên cùng một con đường**: khoá, `latest()` để SQLite tìm
trên index, `_persist_only` ghi đĩa, `__del__` đóng kết nối, và `Lease` cho hai tiến trình. Sáu hàm chỉ company
có, một hàm chỉ studio có (`_notify`) — và hàm ấy đã lên core từ K3.5b, nên nó không còn là điểm lệch.

Ba quyết định hợp nhất, mỗi cái kèm cái nó đổi ở studio:

1. **Khoá.** Bản studio không khoá gì cả: `publish` tháo `_subs` ra, gọi `super().publish`, ghi đĩa, rồi báo
   subscriber — ba bước không nguyên tử. Bản company giữ `RLock` của `InMemoryBus` quanh cả `INSERT` + append
   `_log` + báo subscriber. Studio nhận khoá này. Nó cũng là lý do studio **không cần** mẹo tháo `_subs` nữa:
   thứ tự "ghi đĩa TRƯỚC, báo sau" nay nằm thẳng trong `publish` của core.
2. **`check_same_thread=False`.** Bản studio thiếu, nên một `SQLiteBus` truyền sang thread khác là
   `ProgrammingError`. Nó chỉ chưa nổ vì runner studio chạy một thread. Đi kèm khoá ở (1) nên an toàn: nhiều
   thread dùng chung MỘT kết nối, tuần tự hoá bằng `RLock`.
3. **`BUSY_TIMEOUT_S` là hằng chung.** Company viết thẳng `timeout=30` trong lời gọi, studio đặt tên
   `BUSY_TIMEOUT_S = 30.0` rồi giải thích tại sao. Cùng một con số, một bên có tên một bên không — lấy cái có
   tên. Đây là hướng ngược với hai điểm trên, và là chỗ duy nhất bản studio thắng.

`path` mặc định lấy từ `cfg.db_name` (`"company.sqlite"` / `"studio.sqlite"`): core không được viết tên file
của một công ty vào mình (`config.py`).
"""
from __future__ import annotations

import errno
import os
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import TypeVar

from .bus import BusError, InMemoryBus
from .config import CoreConfig
from .events import Envelope

__all__ = ["BUSY_TIMEOUT_S", "DDL", "Lease", "LeaseError", "SQLiteBus"]

E = TypeVar("E", bound=Envelope)

DDL = """
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT UNIQUE NOT NULL,
  topic TEXT NOT NULL, key TEXT NOT NULL, actor TEXT NOT NULL, ts TEXT NOT NULL,
  body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_topic_key ON events(topic, key);
"""
#: Nhiều tiến trình (orchestrator + gate CLI) cùng ghi một file → chờ khoá thay vì "database is locked" ngay.
BUSY_TIMEOUT_S = 30.0


class SQLiteBus(InMemoryBus[E]):
    """Cùng interface với `InMemoryBus`, đủ cho một máy. Mọi envelope append vào bảng `events`; mở lại là
    replay được theo topic/key — đây cũng là checkpoint để tiếp tục việc bị gián đoạn đúng chỗ (ADR-0001)."""

    def __init__(self, cfg: CoreConfig, path: str | Path | None = None, enforce_owners: bool = True):
        super().__init__(cfg, enforce_owners=enforce_owners)
        self.path = Path(cfg.db_name if path is None else path)
        # check_same_thread=False + RLock của lớp cha: nhiều thread của orchestrator dùng chung một kết nối, tuần tự hoá.
        # timeout: tiến trình khác (gate CLI, publish) đang ghi thì chờ thay vì "database is locked" ngay.
        # WAL: đọc không chặn ghi giữa các tiến trình (orchestrator watch + CLI cùng một file).
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=BUSY_TIMEOUT_S)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(DDL)
        self._seq = 0  # seq cuối đã ĐỌC từ đĩa (không phải seq mình vừa ghi) — poll không được bỏ sót event của tiến trình khác
        self._seen: set[str] = set()  # event_id đã có trong _log (tự ghi hoặc poll về) — poll không nạp lại
        for seq, body in self._db.execute("SELECT seq, body FROM events ORDER BY seq"):
            env = self.envelope_cls.model_validate_json(body)
            self._log.append(env); self._seen.add(env.event_id); self._seq = seq

    def publish(self, env: E) -> E:
        # Lớp cha validate + kiểm quyền; ghi đĩa TRƯỚC khi vào log bộ nhớ và báo subscriber: handler ném lỗi thì event
        # vẫn đã bền vững. KHÔNG nhảy `_seq` tới lastrowid: tiến trình khác có thể đã chèn hàng có seq nhỏ hơn (giữa
        # hai lần poll) — poll đọc từ `_seq` cũ và bỏ qua hàng đã thấy theo event_id.
        self._check_publish(env)
        with self._lock:
            self._write(env)
            self._log.append(env); self._seen.add(env.event_id)
            self._notify_safely(env, reraise=True)  # như InMemoryBus: mọi subscriber nhận, lỗi ghi audit rồi ném lại
        return env

    def _write(self, env: E) -> None:
        with self._db:
            self._db.execute("INSERT INTO events(event_id, topic, key, actor, ts, body) VALUES (?,?,?,?,?,?)",
                             (env.event_id, env.topic, env.key, env.actor, env.ts.isoformat(), env.model_dump_json()))

    def _persist_only(self, env: E) -> E:
        """Ghi đĩa + log nhưng không báo subscriber: audit về handler hỏng không được đi qua chính handler đó."""
        with self._lock:
            subs, self._subs = self._subs, defaultdict(list)
            try:
                return self.publish(env)
            finally:
                self._subs = subs

    def poll(self) -> list[E]:
        """Nạp event do tiến trình KHÁC ghi vào cùng file (gate CLI, human publish) và báo subscriber như event mới.
        Hàng do chính tiến trình này ghi (đã có trong _seen) chỉ đẩy `_seq` lên, không báo lại."""
        with self._lock:
            rows = self._db.execute("SELECT seq, event_id, body FROM events WHERE seq > ? ORDER BY seq",
                                    (self._seq,)).fetchall()
            new: list[E] = []
            for seq, event_id, body in rows:
                self._seq = seq
                if event_id in self._seen: continue
                env = self.envelope_cls.model_validate_json(body)
                self._log.append(env); self._seen.add(event_id); new.append(env)
                self._notify_safely(env)
        return new

    def replay(self, topic: str | None = None, key: str | None = None) -> Iterable[E]:
        q, args, conds = "SELECT body FROM events", [], []
        if topic: conds.append("topic = ?"); args.append(topic)
        if key: conds.append("key = ?"); args.append(key)
        if conds: q += " WHERE " + " AND ".join(conds)
        with self._lock:
            rows = self._db.execute(q + " ORDER BY seq", args).fetchall()
        for (body,) in rows:
            yield self.envelope_cls.model_validate_json(body)

    def latest(self, topic: str, key: str) -> E | None:
        """Như lớp cha nhưng để SQLite tìm: `ORDER BY seq DESC LIMIT 1` trên index (topic, key), không quét log."""
        with self._lock:
            row = self._db.execute("SELECT body FROM events WHERE topic = ? AND key = ? ORDER BY seq DESC LIMIT 1",
                                   (topic, key)).fetchone()
        return self.envelope_cls.model_validate_json(row[0]) if row else None

    def close(self) -> None:
        self._db.close()

    def __del__(self) -> None:
        """Đóng kết nối khi bus bị thu hồi mà người dùng quên `close()`.

        Không có bước này, `sqlite3.Connection` tự cảnh báo `ResourceWarning: unclosed database` lúc GC — trên
        Python 3.13 và với `filterwarnings = error` thì cảnh báo đó là lỗi test. Đóng ở đây sửa đúng chỗ rò (mỗi
        lần mở lại bus là một kết nối) thay vì tắt cảnh báo đi. Chạy lúc thông dịch đang tắt thì thuộc tính có thể
        đã biến mất, nên bọc rộng."""
        try:
            self._db.close()
        except Exception:   # __del__ không được phép ném; mất kết nối lúc thông dịch tắt là chuyện thường
            pass


class LeaseError(BusError): ...


def _alive(pid: int) -> bool:
    """Tiến trình còn sống? Không dùng os.kill(pid, 0) trên Windows (ở đó nó TerminateProcess)."""
    if pid <= 0: return False
    # `sys.platform` chứ không `os.name`: mypy THU HẸP theo `sys.platform` (PEP 484) nhưng không theo
    # `os.name`. Với `os.name == "nt"`, mypy chạy trên Linux vẫn soi thân khối và đỏ ở `ctypes.windll`
    # (`windll` chỉ tồn tại trên Windows), nên phải chú `# type: ignore[attr-defined]` — mà chú ấy lại THỪA
    # khi mypy chạy trên Windows, và core bật `strict` nên "thừa" cũng là lỗi. Hệ quả trước 2026-09-09:
    # `mypy src/xagents_core` KHÔNG BAO GIỜ xanh được trên cả hai nền tảng cùng lúc, và vì `core-static` chỉ
    # chạy ubuntu nên CI không thấy nửa còn lại. Với `sys.platform` thì trên Linux cả khối là unreachable và
    # trên Windows `windll` có thật — sạch ở cả hai, không cần chú nào.
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h: return False
        k32.CloseHandle(h); return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


#: msvcrt khoá BẮT BUỘC theo vùng byte: khoá đè lên phần pid thì chính người đọc pid (kể cả cùng tiến trình, qua
#: handle khác) cũng bị chặn. Khoá một byte ở xa phần pid — Windows cho khoá vùng nằm quá cuối file.
_KHOA_TAI = 1 << 30
#: Số lần mở lại khi khoá trúng file vừa bị gỡ tên. Mỗi lần cần một người giữ nhả đúng khoảnh khắc ấy; hết lượt mà
#: vẫn trúng là chuyện khác (có kẻ xoá lock dồn dập, hệ tệp báo `st_nlink` sai) — nói ra, không lặp im lặng.
_SO_LAN_MO = 5


# no-ky-thuat: khoá OS chỉ loại trừ giữa các tiến trình của MỘT máy trên hệ tệp cục bộ (flock qua NFS/SMB tuỳ máy chủ và trình gắn — như WAL của SQLite), quay lại khi bus nằm trên thư mục mạng mà nhiều máy cùng mở
def _lock(fd: int) -> bool:
    """Khoá loại trừ KHÔNG chờ trên file đã mở. True = đã khoá; False = handle khác (tiến trình này hay tiến trình
    khác) đang giữ. Lỗi khác — hệ tệp không hỗ trợ khoá — ném `OSError` để `acquire` nói đúng tên nó, không gói
    thành "orchestrator khác đang chạy" (khuôn 1, `TRAPS.md` gốc). Rẽ theo `sys.platform` vì lý do ở `_alive`."""
    if sys.platform == "win32":
        import msvcrt
        os.lseek(fd, _KHOA_TAI, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as e:
            if e.errno == errno.EACCES: return False   # LK_NBLCK trúng vùng đang bị khoá
            raise
        return True
    else:
        import fcntl
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True


def _unlock(fd: int) -> None:
    """Đóng fd cũng nhả khoá; nhả tường minh trước vì Windows chỉ hứa nhả "tuỳ tài nguyên hệ thống" khi đóng."""
    if sys.platform == "win32":
        import msvcrt
        os.lseek(fd, _KHOA_TAI, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


def _con_ten(fd: int) -> bool:
    """File đang mở còn tên trong thư mục không — hỏi thẳng `st_nlink` của chính fd. Không cần so inode với
    `stat(path)`: chỉ `release` làm đổi tên (gỡ tên, không rename), nên còn tên ⇔ vẫn là file ở `path`."""
    return os.fstat(fd).st_nlink > 0


def _xoa(path: Path) -> bool:
    """Xoá file lock. False khi Windows từ chối vì còn handle mở tới nó (kể cả handle của chính mình)."""
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        return False
    return True


class Lease:
    """Một tiến trình orchestrator cho một file bus: hai tiến trình `run` trên cùng SQLite sẽ xử lý trùng event
    (processed chỉ học qua audit sau poll). Chủ của bus là ai giữ **khoá OS** trên `<db>.lock` (`fcntl.flock` trên
    POSIX, `msvcrt.locking` trên Windows); pid trong file để người đọc chẩn đoán và để nhận ra bản cũ (dưới).

    **Vì sao khoá OS (trả nợ 2026-10-04).** Bản trước quyết chủ bằng pid trong file: tạo mới thì nguyên tử
    (`O_EXCL`), nhưng chiếm lock CŨ (pid chết) là đọc-rồi-ghi — hai tiến trình khởi động cùng lúc sau một lần crash
    cùng đọc "pid chết", cùng ghi, cùng giữ bus. Khoá OS là một syscall nguyên tử và OS tự nhả khi tiến trình chết,
    nên không còn "lock cũ" phải đoán bằng pid. Đã loại: rename nguyên tử hay file mutex phụ — vẫn phải đoán chủ cũ
    chết chưa bằng pid, cửa sổ kiểm-rồi-chiếm chỉ dời chỗ; `fcntl.lockf` — khoá theo TIẾN TRÌNH, đóng bất kỳ fd nào
    tới file là mất khoá, và hai `Lease` trong một tiến trình không loại trừ nhau.

    **Bẫy gỡ tên.** Kẻ đã mở file trước khi người giữ nhả có thể khoá được nó SAU khi khoá nhả — nếu file ấy đã bị
    gỡ tên thì kẻ thứ ba tạo file mới và cũng khoá được: hai chủ. Nên khoá xong phải kiểm file còn tên
    (`_con_ten`), không thì mở lại. Và POSIX phải gỡ tên KHI CÒN khoá: nhả trước thì kẻ khác khoá được file còn
    tên, qua kiểm, rồi bị gỡ tên dưới chân. Windows ngược lại: không xoá được file còn handle mở, nên đóng rồi mới
    xoá; kẻ vừa mở file trong khe ấy làm lần xoá thất bại và file ở lại — đúng file người ấy đang khoá. Một đường
    cho cả hai: thử xoá khi còn giữ, bị từ chối thì xoá lại sau khi đóng. pid bị xoá khỏi file trước đó, để kẻ mở
    trong khe không thấy pid còn sống của người vừa nhả.

    **pid vẫn được đọc** (sau khi đã giữ khoá) vì orchestrator bản CŨ không lấy khoá OS: pid còn sống, không phải
    mình ⇒ từ chối như trước. Rỗng, hỏng hay pid chết khi đã giữ khoá ⇒ rác của lần tạo dở hoặc lần nhả không xoá
    được, chiếm được. fd từ `os.open` không kế thừa (PEP 446): tiến trình con `exec` (git, sandbox, `claude -p`)
    không mang khoá theo; `redeploy` nhả lease trước `execv` (`cli_cmds._with_lease`)."""

    def __init__(self, db: str | Path):
        self.path = Path(str(db) + ".lock")
        self.held = False
        self._fd = -1

    def acquire(self) -> None:
        if self.held: return   # gọi lại trên đối tượng đang giữ: không mở fd thứ hai — khoá của chính mình sẽ chặn nó
        fd = self._khoa()
        try:
            self._kiem_ban_cu()
            os.ftruncate(fd, 0); os.lseek(fd, 0, os.SEEK_SET); os.write(fd, str(os.getpid()).encode())
        except BaseException:
            _unlock(fd); os.close(fd)
            raise
        self._fd, self.held = fd, True

    def _khoa(self) -> int:
        """Mở-hoặc-tạo `path` rồi khoá; trả fd đang giữ khoá trên đúng file còn mang tên `path`."""
        for _ in range(_SO_LAN_MO):
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0))
            try:
                got = _lock(fd)
            except OSError as e:
                os.close(fd)
                raise LeaseError(f"không khoá được {self.path} ({e}): hệ tệp này không hỗ trợ khoá OS — đặt bus "
                                 f"trên ổ cục bộ") from e
            if not got:
                os.close(fd)
                pid = self._doc_pid()
                ai = f"pid {pid}" if pid > 0 else "chưa ghi pid, đang được tạo"
                raise LeaseError(f"orchestrator khác ({ai}) đang chạy trên {self.path.with_suffix('')}: dừng nó "
                                 f"trước. Khoá OS tự nhả khi nó chết — đừng xoá {self.path} khi nó còn sống")
            if _con_ten(fd): return fd
            _unlock(fd); os.close(fd)   # khoá trúng file người giữ trước vừa gỡ tên: mở lại theo tên
        raise LeaseError(f"không giữ được {self.path}: {_SO_LAN_MO} lần khoá xong thì file đều đã bị gỡ tên — có "
                         f"tiến trình xoá lock liên tục, hoặc hệ tệp báo st_nlink sai")

    def _doc_pid(self) -> int:
        try: raw = self.path.read_text(encoding="utf-8").strip()
        except OSError: return 0   # vd Windows khoá chia sẻ: như pid không đọc được
        try: return int(raw)
        except ValueError: return 0

    def _kiem_ban_cu(self) -> None:
        """Đã giữ khoá OS nên không tiến trình bản này nào giữ bus; còn orchestrator bản cũ (chỉ ghi pid) thì khoá
        không thấy được — pid còn sống và không phải mình ⇒ coi như nó đang giữ."""
        pid = self._doc_pid()
        # no-ky-thuat: pid còn sống mà không giữ khoá OS vẫn bị coi là chủ (để không giẫm lên orchestrator bản cũ) nên pid bị tái dụng sau crash là từ chối oan tới khi xoá tay, quay lại khi không còn máy nào chạy Lease bản trước khoá OS
        if pid != os.getpid() and _alive(pid):
            raise LeaseError(f"orchestrator khác (pid {pid}) đang chạy trên {self.path.with_suffix('')}: "
                             f"dừng nó trước, hoặc xoá {self.path} nếu chắc chắn nó đã chết")

    def release(self) -> None:
        if not self.held: return
        fd, self._fd, self.held = self._fd, -1, False
        try:
            os.ftruncate(fd, 0)          # kẻ mở file trong khe đóng-rồi-xoá (Windows) thấy rỗng, không thấy pid mình
            da_xoa = _xoa(self.path)     # POSIX: gỡ tên khi CÒN khoá
        finally:
            _unlock(fd); os.close(fd)
        if not da_xoa:
            _xoa(self.path)              # Windows: đóng rồi mới xoá được; ai vừa mở thì file ở lại cho người đó
