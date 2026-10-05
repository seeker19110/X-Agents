"""Bộ hợp đồng của `xagents_core.sandbox` (K3.2; ADR-0035 của software-company, ADR gốc 0001).

Chuyển sang core cùng lúc với mã theo bất biến 2 của K3: test đơn vị đi theo module. Trước K3.2 file này nằm ở
`Studio-creators/tests/test_sandbox.py`; phần đo *điểm gọi thật* của mỗi công ty (media của studio, workspace/smoke
của company) ở lại nơi cũ vì đó là test tích hợp, không phải test của module này.

Mọi ca dưới đây chạy cho **cả hai backend** — cùng `RunSpec` phải cho cùng `Result` (exit code, cắt output, cờ
timeout), env luôn qua bộ lọc khoá. Backend container dùng `runner=` giả trả `CompletedProcess`, không cần docker
trên CI.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from xagents_core.sandbox import (
    ContainerSandbox,
    Result,
    RunSpec,
    SandboxError,
    SubprocessSandbox,
    clean_env,
    sandbox_from_settings,
    sanitize_env,
)

PY = sys.executable


def _spec(tmp_path: Path, **kw: Any) -> RunSpec:
    return RunSpec(argv=[PY, "-c", "print('x')"], cwd=tmp_path, **kw)


class _Recorder:
    """Sandbox giả: ghi lại `RunSpec` đã nhận và trả `Result` dựng sẵn."""

    def __init__(self, result: Result | None = None, side: Any = None):
        self.name = "recorder"
        self.specs: list[RunSpec] = []
        self._result = result or Result(0, "", "", False, "recorder")
        self._side = side

    def run(self, spec: RunSpec) -> Result:
        self.specs.append(spec)
        if self._side is not None: return self._side(spec)
        return self._result

    def spawn(self, spec: RunSpec) -> Any:  # pragma: no cover - phòng video không spawn
        raise NotImplementedError


def _fake_runner(record: list[dict[str, Any]], code: int = 0, out: str = "OUT", err: str = "ERR",
                 boom: bool = False) -> Any:
    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        record.append({"argv": argv, **kw})
        if boom: raise subprocess.TimeoutExpired(argv, kw.get("timeout", 0))
        return subprocess.CompletedProcess(argv, code, out, err)
    return run


# ---------- bộ hợp đồng: hai backend, cùng lời hứa ----------

def _backends(record: list[dict[str, Any]], **kw: Any) -> list[Any]:
    return [SubprocessSandbox(runner=_fake_runner(record, **kw)),
            ContainerSandbox("docker", "python:3.12-slim", runner=_fake_runner(record, **kw), env_via_stdin=True)]


@pytest.mark.parametrize("i", [0, 1])
def test_hai_backend_tra_cung_khuon_result(tmp_path, i):
    rec: list[dict[str, Any]] = []
    sb = _backends(rec, code=3, out="A" * 20, err="B" * 20)[i]
    r = sb.run(_spec(tmp_path, max_output=5))
    assert r.exit_code == 3 and r.timed_out is False
    assert r.stdout == "AAAAA" and r.stderr == "BBBBB"      # cắt đuôi đúng max_output
    assert r.sandbox == sb.name and sb.name in {"subprocess", "container:python:3.12-slim",
                                                "container:python:3.12-slim:no-uid"}


@pytest.mark.parametrize("i", [0, 1])
def test_hai_backend_bao_timeout_thay_vi_nem_ngoai_le(tmp_path, i):
    rec: list[dict[str, Any]] = []
    r = _backends(rec, boom=True)[i].run(_spec(tmp_path, timeout=7))
    assert r.timed_out is True and r.exit_code is None and "quá 7" in r.stderr


@pytest.mark.parametrize("i", [0, 1])
def test_hai_backend_khong_bao_gio_chuyen_bien_giong_khoa(tmp_path, monkeypatch, i):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "kín")
    monkeypatch.setenv("STUDIO_LLM_API_KEY", "kín")
    monkeypatch.setenv("PATH_KHONG_PHAI_KHOA", "ok")
    rec: list[dict[str, Any]] = []
    # env=None: sandbox tự lấy clean_env(); nơi gọi quên lọc thì sandbox vẫn lọc.
    _backends(rec)[i].run(RunSpec(argv=["x"], cwd=tmp_path, env=dict(os.environ)))
    blob = repr(rec[0])
    assert "kín" not in blob and "PATH_KHONG_PHAI_KHOA" in blob


def test_sanitize_env_loc_lai_du_noi_goi_da_ban_env_ban(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert "OPENAI_API_KEY" not in clean_env()
    e = sanitize_env({"AWS_SECRET_ACCESS_KEY": "x", "LANG": "vi"})
    assert e == {"LANG": "vi", "PYTHONDONTWRITEBYTECODE": "1"}
    assert "OPENAI_API_KEY" not in sanitize_env(None)   # None → clean_env()


# ---------- argv của container ----------

def test_container_argv_mount_rw_mang_tat_va_env_qua_stdin(tmp_path):
    rec: list[dict[str, Any]] = []
    sb = ContainerSandbox("podman", "img:1", cpus="1", memory="1g", runner=_fake_runner(rec), env_via_stdin=True)
    sb.run(RunSpec(argv=["ffmpeg", "-version"], cwd=tmp_path, env={"LANG": "vi"}))
    argv = rec[0]["argv"]
    assert argv[:3] == ["podman", "run", "--rm"] and "--pids-limit" in argv
    assert f"{tmp_path}:/w:rw" in argv and argv[argv.index("-w") + 1] == "/w"
    assert argv[argv.index("--network") + 1] == "none"
    assert argv[-2:] == ["ffmpeg", "-version"] and "--env-file" in argv
    assert "LANG=vi" in rec[0]["input"]        # env đi qua stdin, không hiện trong danh sách tiến trình


def test_container_env_file_doc_stdin_qua_dev_stdin(tmp_path):
    rec: list[dict[str, Any]] = []
    ContainerSandbox("docker", "img:1", runner=_fake_runner(rec), env_via_stdin=True).run(
        RunSpec(argv=["python", "-V"], cwd=tmp_path, env={"LANG": "vi"}))
    argv = rec[0]["argv"]
    assert argv[argv.index("--env-file") + 1] == "/dev/stdin"


def test_container_mount_chi_doc_cho_qc_va_mo_cong_khi_can_mang(tmp_path):
    rec: list[dict[str, Any]] = []
    sb = ContainerSandbox("docker", "img:1", runner=_fake_runner(rec), egress=_Egress())
    sb.run(RunSpec(argv=["ffprobe"], cwd=tmp_path, read_only=True))
    assert f"{tmp_path}:/w:ro" in rec[0]["argv"]
    sb.run(RunSpec(argv=["srv"], cwd=tmp_path, network=True, port=8080))
    assert rec[1]["argv"][rec[1]["argv"].index("--network") + 1] == "isolated"
    assert "-p" not in rec[1]["argv"]  # publish nằm ở relay, workload vẫn chỉ internal


def test_container_khi_can_stdin_thi_env_buoc_phai_ra_dong_lenh(tmp_path):
    """`--env-file /dev/stdin` chiếm stdin, mà CommandTTS cần văn bản → env quay về `-e` (đánh đổi có chủ ý)."""
    rec: list[dict[str, Any]] = []
    ContainerSandbox("docker", "img:1", runner=_fake_runner(rec), env_via_stdin=True).run(
        RunSpec(argv=["tts"], cwd=tmp_path, env={"LANG": "vi"}, stdin="xin chào"))
    argv = rec[0]["argv"]
    assert "--env-file" not in argv and "-i" in argv and "LANG=vi" in argv
    assert rec[0]["input"] == "xin chào"


def test_container_tren_windows_env_qua_dong_lenh_va_noi_thang_trong_ten(tmp_path):
    """docker CLI trên Windows coi `-` của `--env-file` là TÊN FILE ("open -: The system cannot find the file
    specified") → không có đường stdin; env buộc quay về `-e` như ca stdin, và tên sandbox phải nói thẳng đánh đổi."""
    rec: list[dict[str, Any]] = []
    sb = ContainerSandbox("docker", "img:1", runner=_fake_runner(rec), env_via_stdin=False)
    sb.run(RunSpec(argv=["pytest"], cwd=tmp_path, env={"LANG": "vi"}))
    argv = rec[0]["argv"]
    assert "--env-file" not in argv and "LANG=vi" in argv and argv[argv.index("LANG=vi") - 1] == "-e"
    assert rec[0]["input"] == ""                       # không đẩy KEY=VALUE vào stdin của một lệnh không đọc nó
    assert sb.name == "container:img:1:env-argv" or sb.name == "container:img:1:no-uid:env-argv"


def test_container_mac_dinh_chon_duong_env_theo_he_dieu_hanh(monkeypatch):
    # Chỉ `xagents_core.sandbox` thấy `os.name` giả: đổi `os.name` toàn cục thì test đỏ không báo được lỗi —
    # pytest dựng `Path` khi in báo cáo và sập `INTERNALERROR: cannot instantiate 'WindowsPath'`.
    class OsGia:
        def __init__(self, name: str) -> None:
            self.name = name

        def __getattr__(self, attr: str) -> Any:
            return getattr(os, attr)

    monkeypatch.setattr("xagents_core.sandbox.os", OsGia("nt"))
    assert ContainerSandbox("docker", "img:1").env_via_stdin is False
    monkeypatch.setattr("xagents_core.sandbox.os", OsGia("posix"))
    assert ContainerSandbox("docker", "img:1").env_via_stdin is True


def test_container_khong_co_getuid_thi_noi_thang_trong_ten_sandbox(monkeypatch):
    monkeypatch.delattr(os, "getuid", raising=False)
    monkeypatch.delattr(os, "getgid", raising=False)
    sb = ContainerSandbox("docker", "img:1", env_via_stdin=True)
    assert sb.name == "container:img:1:no-uid" and "-u" not in sb._argv(RunSpec(argv=["x"], cwd=Path(".")), "n")
    monkeypatch.setattr(os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(os, "getgid", lambda: 1000, raising=False)
    sb2 = ContainerSandbox("docker", "img:1", env_via_stdin=True)
    assert sb2.name == "container:img:1" and "1000:1000" in sb2._argv(RunSpec(argv=["x"], cwd=Path(".")), "n")


# ---------- spawn: tiến trình chạy nền ----------

class _FakeProc:
    def __init__(self) -> None:
        self.stdin = None; self.killed = False; self._rc: int | None = None

    def poll(self) -> int | None: return self._rc
    def kill(self) -> None: self.killed = True; self._rc = -9
    def communicate(self, timeout: float = 0) -> tuple[str, str]: return "", "loi cuoi"


def test_proc_handle_without_cleanup_kills_direct_process():
    from xagents_core.sandbox import _ProcHandle

    proc = _FakeProc()
    handle = _ProcHandle(proc)
    handle.kill()
    assert proc.killed and handle.poll() == -9


def test_spawn_tra_handle_poll_kill_stderr_cho_ca_hai_backend(tmp_path, monkeypatch):
    monkeypatch.setattr("xagents_core.sandbox._kill_tree", lambda p: p.kill())
    proc = _FakeProc()
    h = SubprocessSandbox(popen=lambda *a, **k: proc).spawn(_spec(tmp_path))
    assert h.poll() is None
    h.kill(); assert proc.killed and h.poll() == -9
    assert h.stderr_tail(4) == "cuoi" and h.stderr_tail(4) == "cuoi"   # lần hai lấy từ cache

    class _P(_FakeProc):
        def __init__(self) -> None:
            super().__init__()
            self.written: list[str] = []
            self.stdin = type("S", (), {"write": lambda s, t: self.written.append(t), "close": lambda s: None})()

    p2 = _P()
    ContainerSandbox("docker", "img:1", popen=lambda *a, **k: p2, env_via_stdin=True).spawn(
        RunSpec(argv=["x"], cwd=tmp_path, env={"LANG": "vi"}))
    assert p2.written == ["LANG=vi\nPYTHONDONTWRITEBYTECODE=1"]


def test_stderr_tail_rong_khi_khong_lay_duoc_dau_ra():
    class _Hang(_FakeProc):
        def communicate(self, timeout: float = 0) -> tuple[str, str]:
            raise subprocess.TimeoutExpired("x", timeout)

    h = SubprocessSandbox(popen=lambda *a, **k: _Hang()).spawn(RunSpec(argv=["x"], cwd=Path(".")))
    assert h.stderr_tail(10) == ""




# ---------- chọn backend: core nhận giá trị đã đọc sẵn, không tự đọc env ----------

def test_subprocess_va_auto_theo_binary_co_hay_khong():
    assert sandbox_from_settings("subprocess", "docker", "img", "X_SANDBOX", which=lambda _: "/usr/bin/docker").name == "subprocess"
    assert sandbox_from_settings("auto", "docker", "img", "X_SANDBOX", which=lambda _: "/x").name.startswith("container:")


def test_auto_thieu_runtime_phai_dung_va_noi_cach_chon_tuong_minh():
    with pytest.raises(SandboxError) as e:
        sandbox_from_settings("auto", "docker", "img", "X_SANDBOX", which=lambda _: None)
    assert "docker" in str(e.value)
    assert "X_SANDBOX=subprocess" in str(e.value)


def test_khai_container_va_co_binary_thi_dung_image_da_khai():
    sb = sandbox_from_settings("container", "podman", "alpine:3", "X_SANDBOX", which=lambda _: "/usr/bin/podman")
    assert isinstance(sb, ContainerSandbox) and sb.runtime == "podman" and sb.image == "alpine:3"


def test_khai_container_ma_thieu_binary_thi_bao_loi_chu_khong_tut_hang():
    """Fail-closed: `container` khai đích danh mà thiếu binary là LỖI, không bao giờ âm thầm về subprocess."""
    with pytest.raises(SandboxError, match="không tìm thấy `podman`"):
        sandbox_from_settings("container", "podman", "img", "X_SANDBOX", which=lambda _: None)


def test_cau_loi_goi_dung_ten_bien_cua_ben_goi():
    """Core không có prefix của riêng mình: company và studio đặt hai biến khác nhau, người đọc lỗi cần biết gõ
    biến nào. Đây là lý do `env_var` là tham số chứ không phải hằng trong core."""
    for var in ("COMPANY_SANDBOX", "STUDIO_SANDBOX"):
        with pytest.raises(SandboxError) as e:
            sandbox_from_settings("container", "docker", "img", var, which=lambda _: None)
        assert f"{var}=container" in str(e.value) and f"đặt {var}=subprocess" in str(e.value)


def test_che_do_la_thi_bao_loi_thay_vi_doan():
    with pytest.raises(SandboxError, match="không hợp lệ"):
        sandbox_from_settings("kín", "docker", "img", "X_SANDBOX", which=lambda _: "/x")


def test_container_spawn_khi_popen_khong_mo_duoc_stdin(tmp_path):
    """`Popen(stdin=PIPE)` vẫn có thể trả `proc.stdin is None` — hết file descriptor, hay bị wrapper thay thế.

    Không có vế `is not None` thì đây là `AttributeError` ngay khi spawn, và ContainerSandbox mất luôn đường
    báo lỗi tử tế: tiến trình ĐÃ khởi động rồi mới nổ, nên container ở lại mà không ai giữ handle."""
    proc = _FakeProc()                      # `stdin` là None
    h = ContainerSandbox("docker", "img:1", popen=lambda *a, **k: proc).spawn(
        RunSpec(argv=["x"], cwd=tmp_path, env={"LANG": "vi"}))

    assert h.poll() is None                 # vẫn trả handle dùng được, không nổ


def test_clean_env_bo_con_tro_tang_may_cua_adr0016(monkeypatch):
    """`XAGENTS_LLM_CONFIG` trỏ vào file tầng máy — nơi giữ `config_dir`, `base_url`, có thể cả `api_key`.

    Cùng họ với `CLAUDE_CONFIG_DIR`/`CODEX_HOME` đã bị lọc sẵn: không phải bí mật, mà là **đường đến** bí mật,
    và lệnh con (test của khách, ffmpeg, TTS) không có lý do gì cần biết đường đó. ADR-0016 ghi thẳng ở mục hệ
    quả rằng nó mở đường đọc bí mật thứ hai trên máy nên `clean_env`/sandbox phải được rà lại cùng họ
    (`AGENTS.md` luật bắt buộc 5)."""
    monkeypatch.setenv("XAGENTS_LLM_CONFIG", "/nha/toi/.config/xagents/llm.yaml")
    assert "XAGENTS_LLM_CONFIG" not in clean_env()


@pytest.mark.parametrize("ten", ["KEEPER_LLM_PROVIDER", "KEEPER_LLM_BACKENDS", "COMPANY_LLM_PROVIDER"])
def test_clean_env_bo_cau_hinh_llm_cua_moi_cong_ty(monkeypatch, ten):
    """`<PREFIX>_LLM_*` là cấu hình model của một công ty — không lệnh con nào (test của khách, git, gh) cần tới.

    Regex cũ liệt kê tên `COMPANY_LLM|STUDIO_LLM`: core biết tên công ty (trái ADR gốc 0001 §2) và sót keeper, nên
    `KEEPER_LLM_PROVIDER` đi thẳng vào mọi lệnh keeper chạy bằng `clean_env()` (đo 2026-09-28). Ca `COMPANY_LLM_*`
    giữ cho bản viết chung không đánh rơi công ty cũ: test sẵn có chỉ dùng `*_LLM_API_KEY`, thứ `API_?KEY` đã bắt."""
    monkeypatch.setenv(ten, "x")
    assert ten not in clean_env()


# ---------- container không được sống sót sau khi client docker bị giết ----------

def _cleanup_calls(rec: list[dict[str, Any]], runtime: str = "docker") -> list[list[str]]:
    return [c["argv"] for c in rec if c["argv"][:2] == [runtime, "rm"]]


def test_container_run_timeout_thi_xoa_han_container_theo_ten(tmp_path):
    """`subprocess.run(timeout=)` chỉ giết tiến trình client `docker run`; container vẫn chạy tiếp dưới daemon
    (không có `--name` thì không ai gọi tên được nó để dừng). Timeout phải kéo theo `rm -f <tên>`."""
    rec: list[dict[str, Any]] = []
    sb = ContainerSandbox("docker", "img:1", runner=_fake_runner(rec, boom=True), env_via_stdin=True)
    r = sb.run(_spec(tmp_path, timeout=3))
    argv = rec[0]["argv"]
    name = argv[argv.index("--name") + 1]
    assert r.timed_out is True
    assert _cleanup_calls(rec) == [["docker", "rm", "-f", name]]


def test_container_moi_lan_chay_mot_ten_rieng(tmp_path):
    rec: list[dict[str, Any]] = []
    sb = ContainerSandbox("podman", "img:1", runner=_fake_runner(rec), env_via_stdin=True)
    sb.run(_spec(tmp_path)); sb.run(_spec(tmp_path))
    names = [c["argv"][c["argv"].index("--name") + 1] for c in rec]
    assert len(set(names)) == 2 and _cleanup_calls(rec, "podman") == []   # chạy xong bình thường: --rm tự dọn


def test_container_spawn_kill_thi_xoa_han_container(tmp_path):
    """`Handle.kill()` của container: giết client thôi là container (vd server smoke) vẫn giữ cổng."""
    rec: list[dict[str, Any]] = []
    seen: list[list[str]] = []
    proc = _FakeProc()

    def popen(argv: list[str], **kw: Any) -> Any:
        seen.append(argv)
        return proc

    h = ContainerSandbox("docker", "img:1", runner=_fake_runner(rec), popen=popen, env_via_stdin=True).spawn(
        _spec(tmp_path))
    h.kill()
    name = seen[0][seen[0].index("--name") + 1]
    assert proc.killed and _cleanup_calls(rec) == [["docker", "rm", "-f", name]]


def test_container_don_dep_that_bai_khong_nuot_ket_qua(tmp_path):
    """Dọn là nỗ lực tốt nhất: binary biến mất hay `rm` treo không được biến timeout thành ngoại lệ."""
    def runner(argv: list[str], **kw: Any) -> Any:
        if argv[1] == "rm": raise FileNotFoundError(argv[0])
        raise subprocess.TimeoutExpired(argv, 1)

    r = ContainerSandbox("docker", "img:1", runner=runner, env_via_stdin=True).run(_spec(tmp_path, timeout=1))
    assert r.timed_out is True


def test_subprocess_timeout_giet_ca_cay_tien_trinh_khong_treo_vi_chau_giu_ong(tmp_path):
    """Lệnh của khách thường là một CÂY: `uv run pytest` → launcher `.venv/Scripts/python` → python thật. Hết giờ mà
    chỉ giết con trực tiếp thì cháu sống tiếp và vẫn giữ ống stdout: trên Windows `subprocess.run` sau khi kill còn
    `communicate()` KHÔNG trần → cả orchestrator treo tới khi cháu tự xong; trên POSIX không treo nhưng cháu thành
    mồ côi chạy tiếp. Đo được 2026-09-24 (CAMPUS-UNI/TCK-002): `run test` quá 600s, pytest mồ côi ăn 1245s CPU,
    orchestrator 0% CPU, 0 event suốt 20+ phút."""
    marker = tmp_path / "chau-con-song.txt"
    chau = f"import time, pathlib; time.sleep(4); pathlib.Path({str(marker)!r}).write_text('x')"
    cha = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {chau!r}]); time.sleep(30)"
    import time
    t0 = time.monotonic()
    r = SubprocessSandbox().run(RunSpec(argv=[PY, "-c", cha], cwd=tmp_path, timeout=1.5))
    assert r.timed_out and time.monotonic() - t0 < 3.5, "hết giờ phải trả về ngay, không chờ ống do cháu giữ"
    time.sleep(max(0.0, 5.5 - (time.monotonic() - t0)))
    assert not marker.exists(), "cháu phải chết cùng cây, không thành mồ côi chạy tiếp"


class _Proc:
    """Popen giả cho `_kill_tree`/`_run_tree`: ghi lại kill, `communicate` ném theo kịch bản."""
    pid = 42
    returncode = None

    def __init__(self, raises: int = 0):
        self.killed, self.raises = 0, raises

    def kill(self) -> None:
        self.killed += 1

    def communicate(self, input: Any = None, timeout: float | None = None) -> tuple[str, str]:
        if self.raises:
            self.raises -= 1
            raise subprocess.TimeoutExpired("x", timeout or 0)
        return "", ""


def test_kill_tree_tren_windows_goi_taskkill_ca_cay(monkeypatch):
    import xagents_core.sandbox as SB
    monkeypatch.setattr(SB.sys, "platform", "win32")
    seen: list[list[str]] = []
    p = _Proc()
    SB._kill_tree(p, runner=lambda argv, **kw: seen.append(argv))
    assert seen == [["taskkill", "/T", "/F", "/PID", "42"]] and p.killed == 1


def test_kill_tree_tren_posix_giet_ca_nhom(monkeypatch):
    import xagents_core.sandbox as SB
    monkeypatch.setattr(SB.sys, "platform", "linux")
    seen: list[tuple[int, int]] = []
    monkeypatch.setattr(SB.os, "killpg", lambda pid, sig: seen.append((pid, sig)), raising=False)
    monkeypatch.setattr(SB.signal, "SIGKILL", 9, raising=False)
    p = _Proc()
    SB._kill_tree(p)
    assert seen == [(42, 9)] and p.killed == 1


def test_kill_tree_giet_cay_that_bai_van_giet_con_truc_tiep(monkeypatch):
    """Cây đã tự tan (`ProcessLookupError`) hay `taskkill` treo: không được che kết quả timeout."""
    import xagents_core.sandbox as SB
    monkeypatch.setattr(SB.sys, "platform", "win32")
    def boom(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 30)
    p = _Proc()
    SB._kill_tree(p, runner=boom)
    assert p.killed == 1


def test_run_tree_ong_van_khong_dong_sau_khi_giet_thi_bo_cuoc_sau_5s():
    """Sau khi giết cây, chờ ống tối đa 5s; quá nữa vẫn trả TimeoutExpired thay vì treo."""
    import xagents_core.sandbox as SB
    p, killed = _Proc(raises=2), []
    with pytest.raises(subprocess.TimeoutExpired):
        SB._run_tree(["x"], cwd=".", env={}, input=None, timeout=1, popen=lambda *a, **k: p, kill_tree=killed.append)
    assert killed == [p] and p.raises == 0


def test_subprocess_that_chay_xong_tra_exit_stdout_va_nhan_stdin(tmp_path):
    """Đường thường của `_run_tree` (runner mặc định): chạy xong thì trả đúng như `subprocess.run` cũ."""
    r = SubprocessSandbox().run(RunSpec(argv=[PY, "-c", "import sys; print(sys.stdin.read().upper())"], cwd=tmp_path,
                                        env=clean_env() | {"PYTHONIOENCODING": "utf-8"}, stdin="tiếng việt"))
    assert (r.exit_code, r.stdout.strip(), r.timed_out) == (0, "TIẾNG VIỆT", False)


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_spawn_kill_uses_tree_cleanup(tmp_path, monkeypatch, platform):
    import xagents_core.sandbox as SB

    monkeypatch.setattr(SB.sys, "platform", platform)
    proc = _FakeProc()
    spawned, killed = [], []

    def popen(*args, **kwargs):
        spawned.append(kwargs)
        return proc

    def kill_tree(p):
        killed.append(p)
        p.kill()

    monkeypatch.setattr(SB, "_kill_tree", kill_tree)
    handle = SubprocessSandbox(popen=popen).spawn(_spec(tmp_path))
    handle.kill()
    assert killed == [proc]
    assert spawned[0].get("start_new_session", False) == (platform != "win32")
    assert proc.killed


def test_spawn_kill_stops_real_descendant(tmp_path):
    import signal
    import time

    ready, survived = tmp_path / "ready", tmp_path / "survived"
    child = (f"import os, pathlib, time; pathlib.Path({str(ready)!r}).write_text(str(os.getpid())); "
             f"time.sleep(1); pathlib.Path({str(survived)!r}).write_text('alive')")
    parent = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(30)"
    handle = SubprocessSandbox().spawn(RunSpec(argv=[PY, "-c", parent], cwd=tmp_path))
    pid = None
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "child must start before checking termination"
        pid = int(ready.read_text())
        handle.kill()
        handle.stderr_tail(100)
        time.sleep(1.1)
        assert not survived.exists(), "spawned descendants must stop with the parent"
    finally:
        handle.kill()
        handle.stderr_tail(100)
        if pid is not None:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass


def test_subprocess_thieu_binary_tra_127_nhu_container_chu_khong_nem(tmp_path):
    """Repo khách khai stack node mà máy không có `npm`: backend container trả 127 (shell trong container báo),
    backend subprocess từng ném FileNotFoundError xuyên qua `TicketWorkspace.lint/test` — cùng một sự kiện, hai
    chế độ hỏng. Nay cả hai cùng khuôn `Result`, và stderr nói lệnh nào thiếu."""
    r = SubprocessSandbox().run(RunSpec(argv=["khong-co-lenh-nay-xyz", "--version"], cwd=tmp_path, env=clean_env()))
    assert (r.exit_code, r.timed_out, r.sandbox) == (127, False, "subprocess")
    assert "khong-co-lenh-nay-xyz" in r.stderr and r.stdout == ""


@pytest.mark.parametrize('method', ['run', 'spawn'])
def test_s2_subprocess_khong_gia_vo_enforce_domain_allowlist(tmp_path, method):
    spec = RunSpec(argv=['python', '-V'], cwd=tmp_path, allowed_domains=('pypi.org',))
    with pytest.raises(SandboxError, match='allowed_domains'):
        getattr(SubprocessSandbox(), method)(spec)


class _Egress:
    def __init__(self):
        self.closed = 0; self.opened = []
        self.network = 'isolated'; self.env = {'HTTPS_PROXY': 'http://proxy:3128'}

    def open(self, name, domains, port=None):
        self.opened.append((name, domains)); return self

    def close(self):
        self.closed += 1


@pytest.mark.parametrize('outcome', ['ok', 'timeout', 'error'])
def test_s2_run_dung_mang_proxy_va_don_ca_loi(tmp_path, outcome):
    rec = []; proxy = _Egress()
    def run(argv, **kw):
        rec.append((argv, kw))
        if 'rm' in argv: return subprocess.CompletedProcess(argv, 0, '', '')
        if outcome == 'timeout': raise subprocess.TimeoutExpired(argv, 1)
        if outcome == 'error': raise OSError('runtime disappeared')
        return subprocess.CompletedProcess(argv, 0, 'ok', '')
    sb = ContainerSandbox('docker', 'img', runner=run, egress=proxy, env_via_stdin=True)
    spec = RunSpec(argv=['x'], cwd=tmp_path, allowed_domains=('pypi.org',), env={'HTTPS_PROXY': 'http://wrong'})
    if outcome == 'error':
        with pytest.raises(OSError): sb.run(spec)
    else:
        r = sb.run(spec); assert r.timed_out == (outcome == 'timeout')
    argv, kw = rec[0]
    assert argv[argv.index('--network') + 1] == 'isolated'
    assert 'HTTPS_PROXY=http://proxy:3128' in kw['input']
    assert len(proxy.opened) == 1 and proxy.closed == 1


@pytest.mark.parametrize('finish', ['poll', 'kill', 'spawn-error'])
def test_s2_spawn_don_mang_khi_thoat_kill_hoac_khoi_dong_loi(tmp_path, finish):
    proxy = _Egress(); proc = _FakeProc()
    def popen(*a, **kw):
        if finish == 'spawn-error': raise OSError('spawn failed')
        return proc
    sb = ContainerSandbox('docker', 'img', runner=lambda *a, **kw: None, popen=popen, egress=proxy)
    spec = RunSpec(argv=['x'], cwd=tmp_path, network=True, port=8200)
    if finish == 'spawn-error':
        with pytest.raises(OSError): sb.spawn(spec)
    else:
        handle = sb.spawn(spec)
        assert handle.poll() is None and proxy.closed == 0
        if finish == 'poll': proc._rc = 0; assert handle.poll() == 0
        else: handle.kill()
        handle.kill(); handle.poll(); assert handle.stderr_tail(4) == 'cuoi'
    assert proxy.closed == 1


def test_s2_workload_internal_khong_co_dns_ra_ngoai(tmp_path):
    sb = ContainerSandbox('docker', 'img')
    argv = sb._argv(RunSpec(argv=['x'], cwd=tmp_path, network=True, port=8200), 'check', 'internal-net')
    assert argv[argv.index('--dns') + 1] == '127.0.0.1'


def test_s2_spawn_stdin_loi_phai_go_workload_truoc_khi_don_mang(tmp_path):
    proxy = _Egress(); removed = []
    class BrokenInput:
        def write(self, text): raise BrokenPipeError('stdin closed')
    proc = _FakeProc(); proc.stdin = BrokenInput()
    sb = ContainerSandbox('docker', 'img', egress=proxy, popen=lambda *a, **k: proc,
                          runner=lambda argv, **k: removed.append(argv))
    with pytest.raises(BrokenPipeError):
        sb.spawn(RunSpec(argv=['x'], cwd=tmp_path, network=True, port=8200))
    assert len(removed) == 1 and removed[0][:3] == ['docker', 'rm', '-f']
    assert proxy.closed == 1


@pytest.mark.parametrize('stdin_env', [True, False])
def test_s2_container_giu_path_va_venv_cua_image_khong_nhan_host(tmp_path, stdin_env):
    calls = []
    sb = ContainerSandbox('docker', 'img', runner=_fake_runner(calls), env_via_stdin=stdin_env)
    sb.run(RunSpec(argv=['uv', '--version'], cwd=tmp_path,
                   env={'PATH': 'C:/host/bin', 'Virtual_Env': 'C:/host/.venv', 'APP_MODE': 'test'}))
    blob = repr(calls)
    assert 'C:/host' not in blob
    assert 'APP_MODE=test' in blob
