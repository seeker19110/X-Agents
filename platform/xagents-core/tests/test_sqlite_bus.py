"""`xagents_core.sqlite_bus` — bus bền vững chung (K3.5c).

Dùng lại đúng CÔNG TY GIẢ của `test_bus.py` (hai topic, một `Envelope` con): mã ở core thì ca ở core, và ca ở
core không được mượn tên topic của company hay studio. Bốn ca cuối (`__del__`, `_alive` hai nền tảng, file
lock hỏng) chuyển sang từ `software-company/tests/test_coverage_100.py` cùng với mã chúng đo.
"""
from __future__ import annotations

import errno
import multiprocessing
import os
import sqlite3
import sys
import types
from pathlib import Path

import pytest

import _lease_con
from conftest import FakeEnvelope, _tin
from xagents_core import sqlite_bus as SB
from xagents_core.bus import BusError
from xagents_core.sqlite_bus import BUSY_TIMEOUT_S, Lease, LeaseError, SQLiteBus


class Bus(SQLiteBus[FakeEnvelope]):
    envelope_cls = FakeEnvelope


@pytest.fixture
def bus(cfg, tmp_path):
    b = Bus(cfg, tmp_path / "b.sqlite")
    yield b
    b.close()


# ---------- ghi, mở lại, replay ----------

def test_path_mac_dinh_lay_tu_cfg_db_name(cfg, tmp_path, monkeypatch):
    """Core không viết tên file bus của công ty nào vào mình: mặc định đến từ `CoreConfig.db_name`."""
    monkeypatch.chdir(tmp_path)
    b = Bus(cfg)
    try:
        assert b.path.name == "fake.sqlite" and b.path.exists()
    finally:
        b.close()


def test_ghi_dia_va_mo_lai_giu_thu_tu(cfg, tmp_path):
    db = tmp_path / "b.sqlite"
    b1 = Bus(cfg, db)
    for i in range(3):
        b1.publish(_tin(key=f"B{i}"))
    b1.close()
    b2 = Bus(cfg, db)
    try:
        assert [e.key for e in b2.replay()] == ["B0", "B1", "B2"]
        assert [e.key for e in b2.replay(topic="ban-tin", key="B1")] == ["B1"]
        assert list(b2.replay(topic="khong-co")) == []
        assert len(b2) == 3
    finally:
        b2.close()


def test_publish_khong_hop_le_thi_khong_ghi_gi(bus):
    with pytest.raises(BusError):
        bus.publish(FakeEnvelope(topic="ban-tin", key="B1", actor="bien-tap", payload={}))
    assert bus._db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_latest_lay_ban_moi_nhat_va_none_khi_khong_co(bus):
    bus.publish(_tin(key="B1", payload={"tieu_de": "cu"}))
    bus.publish(_tin(key="B1", payload={"tieu_de": "moi"}))
    got = bus.latest("ban-tin", "B1")
    assert got is not None and got.payload["tieu_de"] == "moi"
    assert bus.latest("ban-tin", "khong-co") is None


# ---------- poll: event của tiến trình khác ----------

def test_poll_bao_event_cua_tien_trinh_khac_va_bo_qua_event_cua_minh(cfg, tmp_path, bus):
    thay: list[FakeEnvelope] = []
    bus.subscribe("ban-tin", thay.append)
    bus.publish(_tin(key="MINH"))
    assert thay == bus._log[:1] and bus.poll() == []      # hàng của chính mình chỉ đẩy con trỏ seq

    khac = Bus(cfg, tmp_path / "b.sqlite")                # "tiến trình khác" ghi vào cùng file
    khac.publish(_tin(key="KHAC")); khac.close()

    moi = bus.poll()
    assert [e.key for e in moi] == ["KHAC"] and [e.key for e in thay] == ["MINH", "KHAC"]


def test_publish_ghi_dia_truoc_khi_handler_nem_loi(cfg, tmp_path):
    """Handler hỏng không được làm mất event: nó đã bền vững trước khi subscriber được báo."""
    db = tmp_path / "b.sqlite"
    b = Bus(cfg, db)
    b.subscribe("ban-tin", lambda e: (_ for _ in ()).throw(RuntimeError("handler hỏng")))
    with pytest.raises(RuntimeError, match="handler hỏng"):
        b.publish(_tin(key="B1"))
    b.close()
    b2 = Bus(cfg, db)
    try:
        keys = [e.key for e in b2.replay(topic="ban-tin")]
        assert keys == ["B1"]                                     # event vẫn còn trên đĩa
        assert [e.payload["action"] for e in b2.replay(topic="audit-log")] == ["subscriber_error"]
    finally:
        b2.close()


def test_persist_only_ghi_dia_ma_khong_bao_subscriber(bus):
    thay: list[FakeEnvelope] = []
    bus.subscribe("*", thay.append)
    bus._persist_only(_tin(key="B1"))
    assert thay == [] and bus._db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    bus.publish(_tin(key="B2"))
    assert [e.key for e in thay] == ["B2"]     # bảng subscriber được trả lại nguyên vẹn


def test_bus_dung_duoc_tu_thread_khac(bus):
    """`check_same_thread=False` — bản studio trước K3.5c thiếu cờ này nên nổ `ProgrammingError` ở đây."""
    import threading
    loi: list[Exception] = []

    def ghi():
        try: bus.publish(_tin(key="B1"))
        except Exception as e: loi.append(e)
    t = threading.Thread(target=ghi); t.start(); t.join()
    assert loi == [] and len(bus) == 1


def test_busy_timeout_la_hang_chung():
    assert BUSY_TIMEOUT_S == 30.0


# ---------- close / __del__ ----------

def test_close_dong_ket_noi(cfg, tmp_path):
    b = Bus(cfg, tmp_path / "b.sqlite"); b.close()
    with pytest.raises(sqlite3.ProgrammingError):
        b._db.execute("SELECT 1")


def test_del_nuot_loi_khi_dong_that_bai(bus):
    """`__del__` chạy lúc thông dịch tắt: `close()` hỏng thì phải nuốt, vì `__del__` không được phép ném."""
    that = bus._db   # giữ kết nối THẬT lại: bỏ rơi nó là đúng cái ResourceWarning mà `__del__` sinh ra để tránh

    class _Hong:
        def close(self): raise RuntimeError("thông dịch đang tắt")

    bus._db = _Hong()   # type: ignore[assignment]
    bus.__del__()       # không được ném
    bus._db = that


# ---------- Lease ----------

def test_alive_tren_windows_dung_openprocess(monkeypatch):
    """Nhánh nền tảng rẽ theo `sys.platform`, không phải `os.name` — xem chú thích trong `_alive`: chỉ
    `sys.platform` mới cho mypy thu hẹp, nên chỉ nó mới làm `mypy` sạch trên CẢ Linux lẫn Windows."""
    calls: list[tuple] = []

    class _K32:
        def OpenProcess(self, flags, inherit, pid): calls.append((flags, pid)); return 0 if pid == 404 else 7
        def CloseHandle(self, h): calls.append(("close", h))
    monkeypatch.setattr(SB.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "ctypes", types.SimpleNamespace(windll=types.SimpleNamespace(kernel32=_K32())))
    assert SB._alive(404) is False           # OpenProcess trả handle rỗng → coi như đã chết
    assert SB._alive(123) is True and ("close", 7) in calls
    assert calls[0] == (0x1000, 404)


def test_alive_permission_error_la_con_song(monkeypatch):
    monkeypatch.setattr(SB.sys, "platform", "linux")

    def kill(pid, sig): raise PermissionError
    monkeypatch.setattr(SB.os, "kill", kill)
    assert SB._alive(1) is True


@pytest.mark.parametrize("pid", [0, 2 ** 22 - 1])
def test_alive_pid_khong_hop_le_hoac_da_chet(pid, monkeypatch):
    monkeypatch.setattr(SB.sys, "platform", "linux")

    def kill(p, sig): raise ProcessLookupError
    monkeypatch.setattr(SB.os, "kill", kill)
    assert SB._alive(pid) is False


def test_alive_nhan_ra_tien_trinh_dang_chay(monkeypatch):
    monkeypatch.setattr(SB.sys, "platform", "linux")
    assert SB._alive(os.getpid()) is True     # `os.kill(pid, 0)` không ném: còn sống


def test_lease_giu_va_nha(tmp_path):
    lease = Lease(tmp_path / "b.sqlite")
    lease.acquire()
    assert lease.held and lease.path.read_text(encoding="utf-8") == str(os.getpid())
    lease.acquire()                     # cùng pid: lấy lại được, không phải lỗi
    lease.release()
    assert not lease.path.exists() and not lease.held
    lease.release()                     # nhả hai lần không nổ


def test_lease_bo_qua_file_lock_hong(tmp_path):
    lease = Lease(tmp_path / "b.sqlite")
    lease.path.write_text("không phải số", encoding="utf-8")
    lease.acquire()          # pid không đọc được → coi như lock cũ, lấy lại được
    assert lease.held and lease.path.read_text(encoding="utf-8") == str(os.getpid())
    lease.release()


def test_lease_khong_doc_duoc_lock_thi_coi_la_lock_cu(tmp_path, monkeypatch):
    """Giữ nguyên hành vi cũ: đọc lock lỗi OS (vd Windows khoá chia sẻ) → như pid không đọc được, lấy lại."""
    from pathlib import Path
    lease = Lease(tmp_path / "b.sqlite")
    lease.path.write_text("123", encoding="utf-8")
    def boom(p, *a, **k): raise PermissionError(p)
    monkeypatch.setattr(Path, "read_text", boom)
    lease.acquire()
    assert lease.held
    monkeypatch.undo()
    assert lease.path.read_text(encoding="utf-8") == str(os.getpid())


def test_lease_tu_choi_khi_tien_trinh_khac_con_song(tmp_path, monkeypatch):
    lease = Lease(tmp_path / "b.sqlite")
    lease.path.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(SB, "_alive", lambda pid: True)
    with pytest.raises(LeaseError, match="đang chạy"):
        lease.acquire()
    assert not lease.held


def test_lease_tao_moi_la_nguyen_tu_khong_de_len_lock_vua_co_nguoi_tao(tmp_path, monkeypatch):
    """Đua giữa hai tiến trình: A kiểm "chưa có lock" xong thì B tạo lock; A ghi đè → CẢ HAI cùng giữ bus, xử lý
    trùng event. Giả lập đúng cửa sổ đó: `exists()` trả lời theo cái nhìn trước khi B tạo, nhưng file đã có.
    Tạo mới phải là thao tác nguyên tử (O_CREAT|O_EXCL), không phải kiểm-rồi-ghi."""
    from pathlib import Path
    lease = Lease(tmp_path / "b.sqlite")
    lease.path.write_text("999999", encoding="utf-8")          # B vừa tạo xong
    real_exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda p: False if p == lease.path else real_exists(p))
    monkeypatch.setattr(SB, "_alive", lambda pid: True)
    with pytest.raises(LeaseError, match="đang chạy"):
        lease.acquire()
    assert lease.path.read_text(encoding="utf-8") == "999999" and not lease.held


def test_lease_file_rong_dang_bi_khoa_la_dang_tao_thi_tu_choi(tmp_path):
    """Thay ca cũ "file rỗng = đang có người tạo → từ chối". Cửa sau mà ca cũ chặn (kẻ đến sau đọc rỗng thành "lock
    cũ" rồi ghi đè người vừa tạo) nay do khoá OS chặn: người tạo giữ khoá TRƯỚC khi ghi pid, nên file rỗng mà ĐANG
    bị khoá mới là "đang được tạo"."""
    lease = Lease(tmp_path / "b.sqlite")
    fd = os.open(lease.path, os.O_RDWR | os.O_CREAT)   # kẻ khác vừa tạo + khoá, chưa kịp ghi pid
    try:
        assert SB._lock(fd) is True
        with pytest.raises(LeaseError, match="chưa ghi pid"):
            lease.acquire()
        assert lease.path.read_text(encoding="utf-8") == "" and not lease.held
    finally:
        SB._unlock(fd); os.close(fd)


def test_lease_file_rong_khong_ai_khoa_la_rac_chiem_duoc(tmp_path):
    """Nửa kia của ca cũ: file rỗng mà KHÔNG ai giữ khoá OS là rác của một lần tạo dở (chết giữa lúc tạo và lúc ghi
    pid) hoặc của một lần nhả không xoá được file — không ai đang giữ bus. Ca cũ từ chối nó mãi tới khi có người xoá
    tay; nay lấy lại được, vì khoá OS (không phải nội dung file) mới quyết ai là chủ."""
    lease = Lease(tmp_path / "b.sqlite")
    lease.path.write_text("", encoding="utf-8")
    lease.acquire()
    assert lease.held and lease.path.read_text(encoding="utf-8") == str(os.getpid())
    lease.release()


# ---------- Lease: khoá OS (trả nợ "chiếm lock cũ là đọc-rồi-ghi") ----------

PID_CHET = "999999999"


def _don(con: list) -> None:
    for p in con:
        p.join(_lease_con.CHO_S)
        if p.is_alive():
            p.kill(); p.join()


def test_lease_hai_tien_trinh_dua_chiem_mot_lock_cu_moi_vong_dung_mot_thang(tmp_path):
    """Nợ cũ ở `_take_over`: chiếm lock cũ (pid chết) là đọc-rồi-ghi, nên hai orchestrator khởi động cùng lúc sau một
    lần crash có thể CÙNG chiếm và xử lý trùng event trên một bus — hỏng âm thầm. Đua giữa hai tiến trình THẬT,
    không trông vào may rủi: `_alive` của mỗi con đứng chờ con kia (`_lease_con.GapNhauMotLan`); với mã đọc-rồi-ghi
    đó đúng là lúc cả hai đã đọc "pid chết" mà chưa ai ghi, nên cả hai cùng thắng ở MỌI vòng."""
    ctx = multiprocessing.get_context("spawn")
    db = str(tmp_path / "b.sqlite"); lock = Path(db + ".lock"); so_vong = 10
    xuat_phat, da_dem, da_nha = ctx.Barrier(3), ctx.Barrier(3), ctx.Barrier(3)
    gap, ket_qua = ctx.Barrier(2), ctx.Queue()
    con = [ctx.Process(target=_lease_con.dua, args=(db, so_vong, xuat_phat, gap, ket_qua, da_dem, da_nha))
           for _ in range(2)]
    for p in con: p.start()
    so_ke_thang: list[int] = []
    try:
        for _ in range(so_vong):
            lock.write_text(PID_CHET, encoding="utf-8")    # orchestrator trước đã chết, file lock của nó còn đó
            xuat_phat.wait(_lease_con.CHO_S)
            ket = [ket_qua.get(timeout=_lease_con.CHO_S) for _ in range(2)]
            so_ke_thang.append(sum(thang for _, thang in ket))
            da_dem.wait(_lease_con.CHO_S); da_nha.wait(_lease_con.CHO_S)
    finally:
        _don(con)
    assert so_ke_thang == [1] * so_vong


def test_lease_khoa_os_moi_la_chu_tien_trinh_giu_bi_kill_thi_ke_sau_chiem_duoc(tmp_path, monkeypatch):
    """Khoá OS là thẩm quyền, không phải pid trong file: dù pid đọc ra bị coi là đã chết, kẻ đến sau vẫn bị chặn
    khi tiến trình giữ còn sống. Tiến trình giữ bị kill (không kịp `release()`) thì OS nhả khoá — chiếm được ngay,
    không cần ai xoá file."""
    ctx = multiprocessing.get_context("spawn")
    db = str(tmp_path / "b.sqlite"); san_sang = ctx.Event()
    p = ctx.Process(target=_lease_con.giu, args=(db, san_sang)); p.start()
    try:
        assert san_sang.wait(_lease_con.CHO_S)
        with monkeypatch.context() as m:
            m.setattr(SB, "_alive", lambda pid: False)
            with pytest.raises(LeaseError, match=f"pid {p.pid}"):
                Lease(db).acquire()
    finally:
        p.kill(); p.join(_lease_con.CHO_S)
    p.close()   # Windows: còn handle tới tiến trình đã chết thì `OpenProcess` vẫn mở được, `_alive` báo sống
    lease = Lease(db); _chiem_trong_han(lease)
    assert lease.held and lease.path.read_text(encoding="utf-8") == str(os.getpid())
    lease.release()


def _chiem_trong_han(lease: Lease) -> None:
    """Chiếm ngay khi khoá của tiến trình đã chết được nhả — có hạn. POSIX nhả cùng lúc tiến trình chết; Windows chỉ
    hứa nhả "tuỳ tài nguyên hệ thống" (tài liệu `LockFileEx`), nên ngay sau `join` khoá có thể còn trong khoảnh
    khắc. Hết hạn mà vẫn bị chặn thì ném đúng `LeaseError` cuối cùng — đỏ, không treo."""
    import time
    het_han = time.monotonic() + _lease_con.CHO_S
    while True:
        try:
            lease.acquire(); return
        except LeaseError:
            if time.monotonic() > het_han: raise
            time.sleep(0.05)


def test_lease_cung_tien_trinh_doi_tuong_thu_hai_bi_chan_nha_roi_chiem_lai_duoc(tmp_path):
    """Khoá OS gắn với file đã mở (flock) / handle (msvcrt), không gắn với tiến trình: hai `Lease` trong cùng một
    tiến trình cũng loại trừ nhau — mã cũ cho đối tượng thứ hai chiếm luôn vì "cùng pid". Nhả xong thì lấy lại được."""
    db = tmp_path / "b.sqlite"
    a = Lease(db); a.acquire()
    with pytest.raises(LeaseError, match=f"pid {os.getpid()}"):
        Lease(db).acquire()
    assert a.held and a.path.read_text(encoding="utf-8") == str(os.getpid())
    a.release()
    b = Lease(db); b.acquire()
    assert b.held and b.path.read_text(encoding="utf-8") == str(os.getpid())
    b.release()
    assert not b.path.exists()


def test_lease_khoa_trung_file_vua_bi_go_ten_thi_mo_lai_file_moi(tmp_path, monkeypatch):
    """Bẫy kinh điển của khoá theo file: người giữ trước nhả = gỡ tên file rồi nhả khoá; kẻ đã MỞ file cũ trước đó
    khoá được nó sau khi khoá nhả — nhưng file ấy không còn tên, kẻ thứ ba tạo file mới và cũng khoá được, hai người
    cùng "giữ". Khoá được rồi phải kiểm file còn tên, không thì mở lại. Trên Windows không gỡ được tên file đang mở
    (nên bẫy không xảy ra ở đó) — ca này khẳng định cả điều ấy thay vì lặng lẽ bỏ qua."""
    lease = Lease(tmp_path / "b.sqlite")
    that, lan, go_duoc = SB._lock, [], []

    def lock(fd):
        lan.append(fd); ok = that(fd)
        if len(lan) == 1:
            try:
                os.unlink(lease.path); go_duoc.append(True)   # đúng lúc này người giữ trước gỡ tên file
            except PermissionError:
                go_duoc.append(False)
        return ok
    monkeypatch.setattr(SB, "_lock", lock)
    lease.acquire()
    assert go_duoc == [sys.platform != "win32"]
    assert len(lan) == (2 if go_duoc[0] else 1)
    assert lease.held and lease.path.read_text(encoding="utf-8") == str(os.getpid())
    lease.release()


def test_lease_file_bi_go_ten_mai_thi_bao_loi_khong_lap_vo_han(tmp_path, monkeypatch):
    """Mở lại có giới hạn: một hệ tệp báo `st_nlink` sai (hay ai đó xoá file dồn dập) không được biến `acquire`
    thành vòng lặp im lặng. Hết lượt thì nói ra, và mọi khoá đã lấy trong các lượt ấy đều đã nhả."""
    lease = Lease(tmp_path / "b.sqlite")
    that, lan = SB._lock, []
    monkeypatch.setattr(SB, "_lock", lambda fd: lan.append(fd) or that(fd))
    monkeypatch.setattr(SB, "_con_ten", lambda fd: False)
    with pytest.raises(LeaseError, match="bị gỡ tên"):
        lease.acquire()
    assert len(lan) == SB._SO_LAN_MO and not lease.held
    monkeypatch.undo()
    lease.acquire()                 # các lượt trước không bỏ sót khoá nào: chính mình không tự chặn mình
    assert lease.held
    lease.release()


def test_con_ten_doc_st_nlink_cua_file_dang_mo(tmp_path):
    p = tmp_path / "x.lock"
    fd = os.open(p, os.O_RDWR | os.O_CREAT)
    try:
        assert SB._con_ten(fd) is True
    finally:
        os.close(fd)


def test_lease_he_tep_khong_khoa_duoc_thi_noi_dung_ly_do(tmp_path, monkeypatch):
    """Khuôn 1 của `TRAPS.md` gốc: hệ tệp không hỗ trợ khoá (ENOLCK trên vài ổ mạng) KHÔNG được báo thành "orchestrator
    khác đang chạy" — người đọc sẽ đi tìm một tiến trình không tồn tại."""
    lease = Lease(tmp_path / "b.sqlite")

    def hong(fd): raise OSError(errno.ENOLCK, "No locks available")
    monkeypatch.setattr(SB, "_lock", hong)
    with pytest.raises(LeaseError, match="không khoá được") as e:
        lease.acquire()
    assert "đang chạy" not in str(e.value) and not lease.held


def test_lease_tu_choi_vi_pid_ban_cu_con_song_van_nha_khoa_os(tmp_path, monkeypatch):
    """Từ chối ở bước kiểm pid (orchestrator bản cũ chưa biết khoá OS) xảy ra khi ĐÃ giữ khoá OS: phải nhả nó trước
    khi ném, không thì chính tiến trình này tự chặn mình ở lần thử sau."""
    lease = Lease(tmp_path / "b.sqlite")
    lease.path.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(SB, "_alive", lambda pid: True)
    with pytest.raises(LeaseError, match="đang chạy"):
        lease.acquire()
    monkeypatch.setattr(SB, "_alive", lambda pid: False)
    lease.acquire()
    assert lease.held
    lease.release()


def test_lease_nha_khi_khong_xoa_duoc_file_dang_mo_thi_dong_roi_xoa(tmp_path, monkeypatch):
    """Windows không xoá được file còn handle mở — kể cả handle của chính mình. POSIX thì PHẢI gỡ tên khi còn khoá
    (xem `Lease`). Một đường cho cả hai: thử xoá khi còn giữ; bị từ chối thì đóng handle rồi xoá lại."""
    lease = Lease(tmp_path / "b.sqlite"); lease.acquire(); fd = lease._fd
    that, lan = Path.unlink, []

    def unlink(p, missing_ok=False):
        lan.append(p)
        if len(lan) == 1:
            raise PermissionError(13, "file đang mở")
        with pytest.raises(OSError):
            os.fstat(fd)            # lần xoá thứ hai chỉ sau khi handle đã đóng
        that(p, missing_ok=missing_ok)
    monkeypatch.setattr(Path, "unlink", unlink)
    lease.release()
    assert len(lan) == 2 and not lease.held
    monkeypatch.undo()
    assert not lease.path.exists()


def test_lease_nha_ma_ke_khac_vua_mo_file_thi_de_lai_file_rong(tmp_path, monkeypatch):
    """Windows: giữa lúc đóng handle và lúc xoá, kẻ khác vừa mở file (để khoá) — xoá bị từ chối, file ở lại. Nó
    phải ở lại RỖNG: pid của người vừa nhả còn sống, để nguyên trong file thì kẻ kia từ chối oan."""
    lease = Lease(tmp_path / "b.sqlite"); lease.acquire()

    def tu_choi(p, missing_ok=False): raise PermissionError(13, "file đang mở")
    monkeypatch.setattr(Path, "unlink", tu_choi)
    lease.release()
    monkeypatch.undo()
    assert not lease.held and lease.path.read_text(encoding="utf-8") == ""
    sau = Lease(lease.path.with_suffix("")); sau.acquire()
    assert sau.held
    sau.release()


def test_khoa_os_nhanh_windows_dung_msvcrt_o_xa_phan_pid(tmp_path, monkeypatch):
    """Nhánh Windows đo được trên Linux bằng `msvcrt` giả (cùng cách `_alive` giả `ctypes`). Khoá của msvcrt là khoá
    BẮT BUỘC: khoá byte 0 thì chính người đọc pid cũng bị chặn (kể cả trong cùng tiến trình qua handle khác), nên
    khoá một byte ở xa phần pid. EACCES = đang có người giữ; lỗi khác ném ra cho `acquire` nói đúng tên."""
    goi, loi = [], []

    def locking(fd, mode, n):
        goi.append((mode, os.lseek(fd, 0, os.SEEK_CUR), n))
        if loi: raise loi.pop()
    monkeypatch.setattr(SB.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", types.SimpleNamespace(LK_NBLCK=2, LK_UNLCK=0, locking=locking))
    fd = os.open(tmp_path / "x.lock", os.O_RDWR | os.O_CREAT)
    try:
        assert SB._lock(fd) is True
        loi.append(OSError(errno.EACCES, "đang bị khoá"))
        assert SB._lock(fd) is False
        loi.append(OSError(errno.EINVAL, "lạ"))
        with pytest.raises(OSError, match="lạ"):
            SB._lock(fd)
        SB._unlock(fd)
    finally:
        os.close(fd)
    assert goi == [(2, SB._KHOA_TAI, 1)] * 3 + [(0, SB._KHOA_TAI, 1)]
    assert SB._KHOA_TAI > 2 ** 20


def test_khoa_os_nhanh_posix_dung_flock_khong_cho(monkeypatch):
    """Nhánh POSIX đo được trên Windows bằng `fcntl` giả — chân Windows của core-unit đo `--cov` 100% mà ở đó không
    có `fcntl` thật (đối xứng với `msvcrt` giả ở ca trên). Không chờ (`LOCK_NB`): `BlockingIOError` = đang có người
    giữ; lỗi khác (ENOLCK trên vài ổ mạng) phải ném ra để `acquire` nói đúng tên, không nuốt thành "đang chạy"."""
    goi, loi = [], []

    def flock(fd, op):
        goi.append(op)
        if loi: raise loi.pop()
    monkeypatch.setattr(SB.sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "fcntl", types.SimpleNamespace(LOCK_EX=2, LOCK_NB=4, LOCK_UN=8, flock=flock))
    assert SB._lock(7) is True
    loi.append(BlockingIOError(errno.EAGAIN, "đang bị khoá"))
    assert SB._lock(7) is False
    loi.append(OSError(errno.ENOLCK, "lạ"))
    with pytest.raises(OSError, match="lạ"):
        SB._lock(7)
    SB._unlock(7)
    assert goi == [2 | 4] * 3 + [8]


def test_lease_nha_go_ten_khi_van_con_giu_khoa(tmp_path, monkeypatch):
    """POSIX phải gỡ tên KHI CÒN khoá: nhả trước thì kẻ khác khoá được file còn tên, qua `_con_ten`, rồi bị gỡ tên
    dưới chân — kẻ thứ ba tạo file mới, hai chủ. Lúc gỡ tên, một handle khác vẫn phải bị khoá chặn; gỡ được ngay lần
    đầu thì không gỡ lần hai. (`unlink` giả trả thành công để ca chạy được cả trên Windows, nơi xoá file còn handle
    mở luôn bị từ chối.)"""
    lease = Lease(tmp_path / "b.sqlite"); lease.acquire()
    lan: list[bool] = []

    def unlink(p, missing_ok=False):
        khac = os.open(p, os.O_RDWR)
        try:
            lan.append(SB._lock(khac))
            if lan[-1]: SB._unlock(khac)
        finally:
            os.close(khac)
    monkeypatch.setattr(Path, "unlink", unlink)
    lease.release()
    assert lan == [False] and not lease.held
