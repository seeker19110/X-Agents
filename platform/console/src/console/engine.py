"""Bật/tắt ĐỘNG CƠ của từng xưởng từ console (`orchestrator run --watch`).

Trước module này console là một mặt kính: nó publish việc và ký gate, nhưng vòng lặp xử lý phải do người tự
bật ở một terminal khác — bật console mà quên `run --watch` thì việc giao xong **nằm im**, không lỗi, không
dấu hiệu. Đó là chỗ hụt duy nhất còn lại giữa "nhìn được tất cả" và "điều khiển được tất cả" (ADR-0004).

Ba ranh giới không được phá:

1. **Không có tham số nào của người đi vào dòng lệnh.** `argv` dựng từ `SPECS` chốt cứng trong file này; thứ
   duy nhất người đặt được là `interval` (float, kẹp trong `[MIN_INTERVAL, MAX_INTERVAL]`) và nó đi qua
   `str(float(...))`. Không `shell=True`, không ghép chuỗi, không đường dẫn do client gửi.
2. **Con của console chết cùng console.** `stop_all()` chạy ở `atexit` và khi server đóng: một orchestrator
   mồ côi vẫn ghi vào bus sau khi người trực đã tắt console là đúng thứ TRAPS.md gọi là "công ty chạy mà
   không ai nhìn".
3. **Trạng thái là đo được, không phải khai báo.** `status()` gọi `poll()` từng tiến trình mỗi lần hỏi; một
   động cơ đã chết vì thiếu API key phải hiện `exited` kèm mã thoát và đuôi log, không phải hiện `running`
   vì ta từng bấm Bật (bẫy "xanh vì rỗng", `TRAPS.md`).
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from console.server import CONSOLE_DIR, REPO_ROOT

# Tên hai xưởng lặp lại ở đây thay vì nhập từ `console.decide` một cách CỐ Ý: `server.py` dựng `EngineManager`
# ngay trong `__init__`, mà test của server thay hẳn `console.decide` bằng module giả trong `sys.modules`.
# Nhập chéo lúc đó là một AttributeError phụ thuộc thứ tự import. `test_engine.py` canh hai bảng không lệch nhau.
COMPANY = "software-company"
KEEPER = "keeper"
XUONG = (COMPANY, KEEPER)

LOG_DIR = CONSOLE_DIR / ".engine"          # đã nằm trong .gitignore cùng .console-token
LOG_TAIL_BYTES = 4096                      # đuôi log đọc cho trang: đủ thấy traceback cuối, không đủ để nghẽn
LOG_TAIL_LINES = 12
MIN_INTERVAL = 5.0
MAX_INTERVAL = 3600.0
STOP_GRACE_SECONDS = 10.0                  # SIGTERM rồi mới SIGKILL: vòng watch cần kịp đóng SQLite đang ghi


class EngineError(Exception):
    """Không bật/tắt được động cơ (đang chạy rồi, chưa cấu hình DB, xưởng lạ...)."""

    def __init__(self, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.http_status = http_status


@dataclass(frozen=True)
class EngineSpec:
    """Cách gọi động cơ của một xưởng. `cwd` không phải trang trí: `company.orchestrator` PHẢI chạy trong
    `software-company/` vì gốc repo có `company.sqlite` rỗng (`AGENTS.md` §Chạy cái gì ở đâu)."""

    module: str
    cwd: Path
    label: str
    needs_repo: bool = False
    supports_deliver: bool = False

    def argv(self, db: Path, interval: float, *, deliver_remote: str | None = None) -> list[str]:
        if self.needs_repo:      # keeper: `watch --db … --repo … --interval N` (keeper/src/keeper/cli.py)
            return [sys.executable, "-m", self.module, "watch", "--db", str(db),
                    "--repo", str(REPO_ROOT), "--interval", str(interval)]
        # ADR-0027: không có `--deliver --push-remote` thì `_deliver()` KHÔNG BAO GIỜ chạy — release được ký,
        # khách nghiệm thu, mà tag/nhánh release không bao giờ tới repo khách (sự cố 2026-09-10). Hai cờ này
        # là cờ toàn cục của `company.orchestrator`, phải đứng trước subcommand `run`.
        giao = ["--deliver", "--push-remote", deliver_remote] if (self.supports_deliver and deliver_remote) else []
        return [sys.executable, "-m", self.module, "--db", str(db), *giao, "run", "--watch", str(interval)]


SPECS: dict[str, EngineSpec] = {
    COMPANY: EngineSpec("company.orchestrator", REPO_ROOT / "companies" / "software-company", "xưởng phần mềm",
                        supports_deliver=True),
    KEEPER: EngineSpec("keeper.cli", REPO_ROOT / "companies" / "keeper", "công ty bảo trì", needs_repo=True),
}


def _tail(path: Path) -> str:
    """Đuôi file log, đọc từ cuối lên. Log không có (chưa chạy lần nào) là trạng thái hợp lệ, trả chuỗi rỗng
    — người trực phân biệt "chưa chạy" với "chạy mà im" bằng `state`, không bằng log rỗng."""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(max(0, size - LOG_TAIL_BYTES))
            raw = fh.read()
    except OSError:
        return ""
    text = raw.decode("utf-8", errors="replace")
    return "\n".join(text.splitlines()[-LOG_TAIL_LINES:])


@dataclass
class _Proc:
    popen: subprocess.Popen[bytes]
    log: Path
    started_at: float
    by: str
    interval: float
    argv: list[str]


class EngineManager:
    """Sổ tiến trình con của console, một khoá cho cả sổ (bật/tắt hiếm và nhanh, không đáng chia nhỏ khoá)."""

    def __init__(self, dbs: dict[str, Path | None], *, log_dir: Path = LOG_DIR,
                 deliver_remote: str | None = None) -> None:
        self._dbs = dbs
        self._log_dir = log_dir
        # Quyết định của NGƯỜI TRỰC lúc gõ lệnh (`--deliver-remote`), không bao giờ là trường trong POST
        # /api/engine — `console/CLAUDE.md`: argv chốt cứng trong SPECS, không nhận tham số client.
        self.deliver_remote = deliver_remote
        self._procs: dict[str, _Proc] = {}
        self._last: dict[str, dict[str, Any]] = {}   # lần chạy gần nhất đã kết thúc, để trang còn kể được
        self._lock = threading.Lock()

    # --- đọc -----------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Trạng thái ĐO ĐƯỢC của cả ba động cơ. Gọi `poll()` nên phát hiện được tiến trình đã chết."""
        with self._lock:
            return {"engines": [self._one(x) for x in XUONG]}

    def fingerprint(self) -> str:
        """Đổi khi có động cơ bật/tắt/chết — để `/api/stream` đẩy trạng thái mới ngay, không chờ nhịp 10 giây."""
        with self._lock:
            return "|".join(f"{x}:{self._one(x)['state']}:{self._one(x).get('pid') or '-'}" for x in XUONG)

    def _one(self, xuong: str) -> dict[str, Any]:
        spec = SPECS[xuong]
        db = self._dbs.get(xuong)
        # `delivers` là lời khai BẮT BUỘC của trạng thái: một động cơ chạy mà không giao hàng nhìn y hệt một
        # động cơ giao hàng, và đó là cách sự cố 2026-09-10 sống sót qua cả gate ký lẫn nghiệm thu của khách.
        giao = spec.supports_deliver and bool(self.deliver_remote)
        base: dict[str, Any] = {"xuong": xuong, "label": spec.label, "db": str(db) if db else None,
                                "configured": db is not None, "delivers": giao,
                                "deliver_remote": self.deliver_remote if giao else None}
        proc = self._procs.get(xuong)
        if proc is not None:
            code = proc.popen.poll()
            if code is None:
                return {**base, "state": "running", "pid": proc.popen.pid, "by": proc.by,
                        "interval": proc.interval, "started_at": proc.started_at,
                        "uptime_s": round(time.time() - proc.started_at, 1),
                        "log": str(proc.log), "tail": _tail(proc.log)}
            self._reap(xuong, proc, code)
        last = self._last.get(xuong)
        if last is not None:
            return {**base, **last}
        return {**base, "state": "stopped", "pid": None, "tail": ""}

    def _reap(self, xuong: str, proc: _Proc, code: int) -> None:
        """Tiến trình đã kết thúc: dời khỏi sổ đang chạy, giữ lại *vì sao* cho lần hỏi sau."""
        self._procs.pop(xuong, None)
        self._last[xuong] = {"state": "exited", "pid": None, "exit_code": code, "by": proc.by,
                             "interval": proc.interval, "started_at": proc.started_at,
                             "stopped_at": time.time(), "log": str(proc.log), "tail": _tail(proc.log)}

    # --- ghi -----------------------------------------------------------------

    def start(self, xuong: str, *, interval: float, by: str) -> dict[str, Any]:
        if xuong not in SPECS:
            raise EngineError(f"xưởng lạ: {xuong} (chỉ nhận {' | '.join(XUONG)})")
        by = (by or "").strip()
        if not by:
            raise EngineError("thiếu người bật (`by`)")
        _check_actor(by)
        try:
            interval = float(interval)
        except (TypeError, ValueError):
            raise EngineError("`interval` phải là số giây") from None
        if not MIN_INTERVAL <= interval <= MAX_INTERVAL:
            raise EngineError(f"`interval` phải trong khoảng {MIN_INTERVAL:g}–{MAX_INTERVAL:g} giây")
        db = self._dbs.get(xuong)
        if db is None:
            raise EngineError(f"console chạy không có đường dẫn bus của {xuong}")
        spec = SPECS[xuong]
        if not spec.cwd.is_dir():
            raise EngineError(f"không thấy thư mục {spec.cwd} — console đang chạy ngoài repo?")

        with self._lock:
            running = self._procs.get(xuong)
            if running is not None and running.popen.poll() is None:
                raise EngineError(f"động cơ {spec.label} đang chạy rồi (pid {running.popen.pid})", 409)
            self._log_dir.mkdir(parents=True, exist_ok=True)
            log = self._log_dir / f"{xuong}.log"
            argv = spec.argv(Path(db).resolve(), interval, deliver_remote=self.deliver_remote)
            # Nối stdout+stderr vào một file: người trực đọc một dòng thời gian, không phải ghép hai file.
            handle = log.open("ab", buffering=0)
            try:
                handle.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} console bật bởi {by}: "
                             f"{' '.join(argv)} (cwd {spec.cwd})\n".encode())
                popen = subprocess.Popen(argv, cwd=str(spec.cwd), stdout=handle, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL,
                                         env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            except OSError as e:
                raise EngineError(f"không chạy được động cơ {spec.label}: {e}", 500) from e
            finally:
                handle.close()
            self._procs[xuong] = _Proc(popen, log, time.time(), by, interval, argv)
            self._last.pop(xuong, None)
            return {"ok": True, **self._one(xuong)}

    def stop(self, xuong: str, *, by: str) -> dict[str, Any]:
        if xuong not in SPECS:
            raise EngineError(f"xưởng lạ: {xuong} (chỉ nhận {' | '.join(XUONG)})")
        if not (by or "").strip():
            raise EngineError("thiếu người tắt (`by`)")
        _check_actor(by.strip())
        with self._lock:
            proc = self._procs.get(xuong)
            if proc is None or proc.popen.poll() is not None:
                raise EngineError(f"động cơ {SPECS[xuong].label} không chạy", 409)
            code = _terminate(proc.popen)
            self._reap(xuong, proc, code)
            self._last[xuong]["stopped_by"] = by.strip()
            return {"ok": True, **self._one(xuong)}

    def stop_all(self) -> None:
        """Tắt mọi động cơ console đã bật. Chạy ở `atexit` và khi server đóng — không ném ra ngoài."""
        with self._lock:
            for xuong, proc in list(self._procs.items()):
                if proc.popen.poll() is None:
                    code = _terminate(proc.popen)
                else:                                          # pragma: no cover - đua với chính nó
                    code = proc.popen.returncode
                self._reap(xuong, proc, code)


def _check_actor(by: str) -> None:
    """Luật chung của trường danh tính (`console.decide.actor_problem`); nhập trễ như `server.py` nhập `decide`."""
    from console.decide import actor_problem

    if (why := actor_problem(by, "by")) is not None:
        raise EngineError(why)


def _terminate(popen: subprocess.Popen[bytes]) -> int:
    """SIGTERM, chờ `STOP_GRACE_SECONDS`, rồi SIGKILL. Trả mã thoát."""
    popen.terminate()
    try:
        return popen.wait(timeout=STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:                          # pragma: no cover - cần một tiến trình cố tình lì
        popen.kill()
        return popen.wait()
