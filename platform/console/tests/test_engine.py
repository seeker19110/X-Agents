"""engine.py: console bật/tắt động cơ của từng xưởng (ADR-0004).

Test chạy tiến trình con THẬT (`sys.executable -c ...`) chứ không mock `subprocess`: thứ đáng sai ở module này
là vòng đời tiến trình — bật hai lần, chết giữa chừng, tắt rồi vẫn khai đang chạy — và mock `Popen` thì đúng
những chỗ đó không được kiểm. Điều duy nhất thay là `SPECS`: không test nào được gọi orchestrator thật.
"""
from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from console import engine as en
from console.engine import COMPANY, KEEPER

SLEEP = "import time,sys; print('song', flush=True); time.sleep(60)"
DIE = "import sys; sys.stderr.write('vo tao roi\\n'); sys.exit(3)"


@dataclass(frozen=True)
class FakeSpec(en.EngineSpec):
    """Spec dùng đúng `EngineSpec` thật, chỉ đổi dòng lệnh sang một python vô hại."""

    code: str = SLEEP

    def argv(self, db: Path, interval: float, *, deliver_remote: str | None = None) -> list[str]:
        return [sys.executable, "-c", self.code]


@pytest.fixture
def mgr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> en.EngineManager:
    monkeypatch.setitem(en.SPECS, COMPANY, FakeSpec("x", tmp_path, "xưởng phần mềm"))
    m = en.EngineManager({COMPANY: tmp_path / "company.sqlite", KEEPER: None},
                         log_dir=tmp_path / ".engine")
    yield m
    m.stop_all()


def _wait(mgr: en.EngineManager, xuong: str, state: str, timeout: float = 10.0) -> dict:
    """Chờ tới khi `status()` ĐO ĐƯỢC trạng thái mong đợi. Không `sleep` cố định: máy CI chậm hơn máy dev."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        one = next(e for e in mgr.status()["engines"] if e["xuong"] == xuong)
        if one["state"] == state:
            return one
        time.sleep(0.05)
    raise AssertionError(f"{xuong} không bao giờ tới trạng thái {state}: {mgr.status()}")


# ---------- dòng lệnh: không tham số nào của người đi vào argv ----------

def test_argv_company_chay_run_watch_trong_thu_muc_cong_ty() -> None:
    spec = en.SPECS[COMPANY]
    argv = spec.argv(Path("/tmp/company.sqlite"), 30.0)
    assert argv[:3] == [sys.executable, "-m", "company.orchestrator"]
    assert argv[-3:] == ["run", "--watch", "30.0"] and "--db" in argv
    assert spec.cwd.name == "software-company"   # gốc repo có company.sqlite RỖNG (AGENTS.md)


def test_argv_keeper_dung_lenh_watch_cua_no_kem_repo() -> None:
    argv = en.SPECS[KEEPER].argv(Path("/tmp/keeper.sqlite"), 300.0)
    assert argv[3] == "watch" and "--repo" in argv and argv[-2:] == ["--interval", "300.0"]


# ---------- giao hàng: động cơ bật từ console phải giao được, và im lặng không giao là chế độ hỏng ----------

def test_argv_company_mac_dinh_khong_giao_hang() -> None:
    """Chiều ngược: không ai bật thì tuyệt đối không có cờ giao hàng — push lên remote của khách
    không bao giờ được là mặc định."""
    argv = en.SPECS[COMPANY].argv(Path("/tmp/company.sqlite"), 30.0)
    assert "--deliver" not in argv and "--push-remote" not in argv


def test_argv_company_mang_co_giao_hang_khi_nguoi_truc_bat() -> None:
    """Sự cố 2026-09-10: QA pass, gate ký, khách nghiệm thu — nhưng `_deliver()` không bao giờ chạy vì
    tiến trình thiếu `--deliver --push-remote`. Động cơ bật từ console phải giao được."""
    argv = en.SPECS[COMPANY].argv(Path("/tmp/company.sqlite"), 30.0, deliver_remote="origin")
    assert "--deliver" in argv and argv[argv.index("--push-remote") + 1] == "origin"
    # cờ toàn cục phải đứng TRƯỚC subcommand `run` (argparse: chúng khai trên parser gốc, không trên subparser)
    assert argv.index("--deliver") < argv.index("run")
    assert argv[-3:] == ["run", "--watch", "30.0"]


def test_keeper_khong_nhan_co_giao_hang() -> None:
    """`keeper.cli watch` không có hai cờ đó; truyền nhầm là tiến trình chết ngay lúc khởi động."""
    argv = en.SPECS[KEEPER].argv(Path("/tmp/keeper.sqlite"), 300.0, deliver_remote="origin")
    assert "--deliver" not in argv and "--push-remote" not in argv


def test_status_khai_bao_dong_co_co_giao_hang_hay_khong(tmp_path: Path) -> None:
    """Khuôn lỗi số 1 của repo: *chế độ hỏng không tự khai báo*. Một động cơ chạy mà không giao hàng nhìn
    y hệt một động cơ giao hàng — đêm 2026-09-10 mất nhiều giờ mới phát hiện. Trạng thái phải nói ra."""
    tat = en.EngineManager({COMPANY: tmp_path / "c.sqlite", KEEPER: None}, log_dir=tmp_path / ".e1")
    cong_ty = next(e for e in tat.status()["engines"] if e["xuong"] == COMPANY)
    assert cong_ty["deliver_remote"] is None and cong_ty["delivers"] is False

    bat = en.EngineManager({COMPANY: tmp_path / "c.sqlite", KEEPER: None},
                           log_dir=tmp_path / ".e2", deliver_remote="origin")
    cong_ty = next(e for e in bat.status()["engines"] if e["xuong"] == COMPANY)
    assert cong_ty["deliver_remote"] == "origin" and cong_ty["delivers"] is True


def test_status_keeper_khong_bao_gio_khai_giao_hang(tmp_path: Path) -> None:
    """Keeper không có đường giao hàng nào; khai `delivers=True` cho nó là nói dối người trực."""
    m = en.EngineManager({COMPANY: None, KEEPER: tmp_path / "k.sqlite"},
                         log_dir=tmp_path / ".e3", deliver_remote="origin")
    keeper = next(e for e in m.status()["engines"] if e["xuong"] == KEEPER)
    assert keeper["delivers"] is False and keeper["deliver_remote"] is None


def test_co_giao_hang_den_tu_dong_lenh_console_khong_tu_client(tmp_path: Path) -> None:
    """`console/CLAUDE.md`: argv chốt cứng trong SPECS, KHÔNG nhận tham số client. Remote là quyết định
    của người trực lúc gõ lệnh, không phải trường trong POST /api/engine."""
    m = en.EngineManager({COMPANY: tmp_path / "c.sqlite", KEEPER: None},
                         log_dir=tmp_path / ".engine", deliver_remote="origin")
    assert m.deliver_remote == "origin"
    import inspect
    assert "deliver" not in inspect.signature(m.start).parameters


def test_cwd_cua_hai_dong_co_co_that_tren_dia() -> None:
    """`spec.cwd.name` khớp là chưa đủ: `platform/software-company` cũng có `name` đúng mà không tồn tại.
    Đây là cái ADR-0011 (dời sang `companies/`) làm hỏng mà test cũ không thấy — `start()` chỉ ném
    `không thấy thư mục …` khi người trực bấm Bật, tức là lộ ra ở tay người dùng chứ không ở CI."""
    for xuong, spec in en.SPECS.items():
        assert spec.cwd.is_dir(), f"cwd của động cơ {xuong} không tồn tại: {spec.cwd}"
        assert (spec.cwd / "pyproject.toml").is_file(), f"{spec.cwd} không phải cây package"


# ---------- vòng đời ----------

def test_bat_roi_hoi_lai_thi_thay_dang_chay_kem_pid_va_log(mgr: en.EngineManager) -> None:
    r = mgr.start(COMPANY, interval=10, by="human:truc-ban")
    assert r["ok"] is True and r["state"] == "running" and r["pid"] > 0
    one = _wait(mgr, COMPANY, "running")
    assert one["by"] == "human:truc-ban" and one["interval"] == 10.0 and one["uptime_s"] >= 0
    assert Path(one["log"]).exists() and "console bật bởi human:truc-ban" in Path(one["log"]).read_text(encoding="utf-8")


def test_bat_hai_lan_thi_lan_hai_bi_chan_409(mgr: en.EngineManager) -> None:
    mgr.start(COMPANY, interval=10, by="human:a")
    with pytest.raises(en.EngineError) as e:
        mgr.start(COMPANY, interval=10, by="human:b")
    assert e.value.http_status == 409 and "đang chạy rồi" in str(e.value)


def test_tat_thi_tien_trinh_chet_that_va_ghi_lai_ai_tat(mgr: en.EngineManager) -> None:
    started = mgr.start(COMPANY, interval=10, by="human:a")
    r = mgr.stop(COMPANY, by="human:b")
    assert r["state"] == "exited" and r["stopped_by"] == "human:b"
    # Bằng chứng máy, không phải lời khai của sổ: `exit_code` là số nguyên nghĩa là `Popen.wait()` ĐÃ trả về,
    # tức hệ điều hành đã báo tiến trình kết thúc và thu xác nó — sổ không tự bịa ra được con số này.
    assert isinstance(r["exit_code"], int)
    # Thêm một phép đo độc lập, CHỈ trên POSIX: hỏi hệ điều hành xem pid còn không.
    # Trên Windows KHÔNG làm được phép này: `os.kill(pid, 0)` của CPython không phải "thăm dò" như POSIX — nó
    # gọi TerminateProcess với mã 0, tức phép đo sẽ GIẾT tiến trình còn sống thay vì hỏi nó còn không, và với pid
    # đã chết thì ném `OSError: [WinError 87]` chứ không phải `ProcessLookupError` (đo được trên CI windows-latest
    # 2026-09-09). Một phép đo giết chính thứ nó đo thì không phải phép đo.
    if sys.platform != "win32":
        con = subprocess.run([sys.executable, "-c", f"import os;os.kill({started['pid']},0)"], capture_output=True)
        assert con.returncode != 0 and b"ProcessLookupError" in con.stderr


def test_dong_co_tu_chet_thi_hien_exited_kem_ma_thoat_va_duoi_log(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """Bẫy 'xanh vì đã bấm Bật': động cơ chết vì thiếu cấu hình phải nhìn khác hẳn động cơ đang chạy."""
    monkeypatch.setitem(en.SPECS, COMPANY, FakeSpec("x", tmp_path, "xưởng phần mềm", code=DIE))
    m = en.EngineManager({COMPANY: tmp_path / "c.sqlite"}, log_dir=tmp_path / ".engine")
    m.start(COMPANY, interval=10, by="human:a")
    one = _wait(m, COMPANY, "exited")
    assert one["exit_code"] == 3 and "vo tao roi" in one["tail"] and "stopped_by" not in one
    assert m.status()["engines"][0]["state"] == "exited"      # hỏi lại vẫn nhớ vì sao


def test_tat_khi_khong_chay_bi_chan_409(mgr: en.EngineManager) -> None:
    with pytest.raises(en.EngineError) as e:
        mgr.stop(COMPANY, by="human:a")
    assert e.value.http_status == 409


def test_tat_dong_co_da_tu_chet_cung_bi_chan_409(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(en.SPECS, COMPANY, FakeSpec("x", tmp_path, "xưởng phần mềm", code=DIE))
    m = en.EngineManager({COMPANY: tmp_path / "c.sqlite"}, log_dir=tmp_path / ".engine")
    m.start(COMPANY, interval=10, by="human:a")
    _wait(m, COMPANY, "exited")
    with pytest.raises(en.EngineError):
        m.stop(COMPANY, by="human:a")


def test_stop_all_giet_moi_dong_co_console_da_bat(mgr: en.EngineManager) -> None:
    mgr.start(COMPANY, interval=10, by="human:a")
    mgr.stop_all()
    assert _wait(mgr, COMPANY, "exited")["state"] == "exited"
    mgr.stop_all()   # gọi lần hai không nổ: đường atexit chạy sau server_close


# ---------- từ chối ----------

@pytest.mark.parametrize("xuong,by,interval,mong", [
    ("xuong-la", "human:a", 30, "xưởng lạ"),
    (COMPANY, "  ", 30, "thiếu người bật"),
    (COMPANY, "human:a", "nhanh", "phải là số giây"),
    (COMPANY, "human:a", 1, "5–3600"),
    (COMPANY, "human:a", 9999, "5–3600"),
    # audit 2026-10-10 (G4): `by` đi thẳng vào dòng `=== … console bật bởi {by}` của log — xuống dòng giả được
    # một dòng log khác, và trường danh tính không có trần độ dài.
    (COMPANY, "human:a\n=== 2026-01-01 00:00:00 console bật bởi human:b", 30, "ký tự điều khiển"),
    (COMPANY, "human:" + "x" * 80, 30, "quá dài"),
])
def test_start_tu_choi_tham_so_sai(mgr: en.EngineManager, xuong: str, by: str, interval, mong: str) -> None:
    with pytest.raises(en.EngineError, match=mong):
        mgr.start(xuong, interval=interval, by=by)


def test_start_tu_choi_khi_console_khong_co_db_cua_xuong(mgr: en.EngineManager) -> None:
    with pytest.raises(en.EngineError, match="không có đường dẫn bus"):
        mgr.start(KEEPER, interval=30, by="human:a")


def test_start_tu_choi_khi_thu_muc_cong_ty_khong_ton_tai(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(en.SPECS, COMPANY, FakeSpec("x", tmp_path / "khong-co", "xưởng phần mềm"))
    m = en.EngineManager({COMPANY: tmp_path / "c.sqlite"}, log_dir=tmp_path / ".engine")
    with pytest.raises(en.EngineError, match="không thấy thư mục"):
        m.start(COMPANY, interval=30, by="human:a")


def test_start_bao_500_khi_khong_chay_duoc_tien_trinh(mgr: en.EngineManager, monkeypatch: pytest.MonkeyPatch) -> None:
    def no(*a, **k):
        raise OSError("hết tiến trình")
    monkeypatch.setattr(en.subprocess, "Popen", no)
    with pytest.raises(en.EngineError) as e:
        mgr.start(COMPANY, interval=30, by="human:a")
    assert e.value.http_status == 500 and "hết tiến trình" in str(e.value)


def test_stop_tu_choi_xuong_la_va_thieu_nguoi(mgr: en.EngineManager) -> None:
    with pytest.raises(en.EngineError, match="xưởng lạ"):
        mgr.stop("xuong-la", by="human:a")
    with pytest.raises(en.EngineError, match="thiếu người tắt"):
        mgr.stop(COMPANY, by="")
    with pytest.raises(en.EngineError, match="ký tự điều khiển"):
        mgr.stop(COMPANY, by="human:a\rhuman:b")


# ---------- trạng thái đọc ----------

def test_xuong_khong_cau_hinh_db_hien_configured_false(mgr: en.EngineManager) -> None:
    st = {e["xuong"]: e for e in mgr.status()["engines"]}
    assert set(st) == {COMPANY, KEEPER}
    assert st[KEEPER]["configured"] is False and st[KEEPER]["state"] == "stopped" and st[KEEPER]["tail"] == ""
    assert st[COMPANY]["configured"] is True


def test_fingerprint_doi_khi_bat_va_khi_tat(mgr: en.EngineManager) -> None:
    truoc = mgr.fingerprint()
    mgr.start(COMPANY, interval=10, by="human:a")
    giua = mgr.fingerprint()
    mgr.stop(COMPANY, by="human:a")
    assert truoc != giua != mgr.fingerprint()


def test_tail_tra_chuoi_rong_khi_khong_doc_duoc_log(tmp_path: Path) -> None:
    assert en._tail(tmp_path / "khong-co.log") == ""


def test_tail_chi_lay_may_dong_cuoi(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_text("\n".join(f"dong {i}" for i in range(200)), encoding="utf-8")
    duoi = en._tail(log).splitlines()
    assert len(duoi) == en.LOG_TAIL_LINES and duoi[-1] == "dong 199"


def test_ten_xuong_khong_lech_voi_decide() -> None:
    """`engine.py` chép hai hằng tên xưởng (xem chú thích ở đầu file). Chép thì phải có người canh."""
    from console import decide

    assert (en.COMPANY, en.KEEPER) == (decide.COMPANY, decide.KEEPER)
    assert en.XUONG == decide.XUONG and set(en.SPECS) == set(decide.XUONG)
