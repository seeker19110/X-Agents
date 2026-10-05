"""ADR-0040 D1c: `COMPANY_DEPLOY=process` — khách không dùng Docker (QLKH: tiến trình trần trên WSL).

Cùng khuôn tiêm runner với `test_deploy_compose.py` (ADR-0039): máy chạy test không có `wsl.exe`/`bash` thật, nên
`run`/`which` được tiêm giả — đo đường đi và kết luận, không đo hành vi thật của script.

Đo hai chiều (AGENTS.md luật 4) — bỏ từng vế của `ok` thì đúng một ca dưới đây phải đỏ:
- bỏ kiểm smoke sau `up` (chỉ tin exit code) → `test_smoke_do_thi_khong_ok_va_co_down` đỏ;
- bỏ `down` ở nhánh hỏng → `test_up_that_bai_thi_khong_ok_va_co_down`/`test_smoke_do_...` đỏ ở phần "down" trong `subs`;
- `COMPANY_DEPLOY=process` mà `which` trả None mà không raise → `test_process_khai_dich_danh_ma_thieu_binary_thi_raise` đỏ;
- bỏ thay `.` bằng `repo_root` trong prefix → `test_prefix_thay_dau_cham_bang_duong_dan_repo` đỏ.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from company.deploy import (
    DEFAULT_RUNTIME_PROCESS,
    ENV_MODE,
    ENV_RUNTIME,
    PROCESS_SUB,
    DeployError,
    _process_argv,
    _process_prefix,
    deploy,
    deploy_script,
    deploy_settings,
)
from company.smoke import Runtime

RT = Runtime(
    ("python", "-m", "http.server", "{port}"),
    path="/healthz",
    timeout_s=2,
    port=8080,
    deploy="infra/staging/wsl/deploy_process.sh",
)


class FakeProcess:
    """Runner giả cho mode `process`: ghi lại argv, trả kết quả dựng sẵn theo lệnh con CUỐI (`up`/`down`)."""

    def __init__(self, **rc: tuple[int, str, str]):
        self.calls: list[list[str]] = []
        self._rc = {"up": (0, "", ""), "down": (0, "", "")} | rc

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        code, out, err = self._rc[argv[-1]]
        return subprocess.CompletedProcess(argv, code, out, err)

    @property
    def subs(self) -> list[str]:
        return [c[-1] for c in self.calls]


def _repo(tmp_path: Path, script: str = "infra/staging/wsl/deploy_process.sh") -> Path:
    p = tmp_path / script
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    return tmp_path


def _deploy(tmp_path, rt=RT, *, which=lambda b: f"/usr/bin/{b}", **kw):
    fake = FakeProcess(**kw)
    return deploy(_repo(tmp_path), "P1", "staging", rt, mode="process", binary="bash", run=fake, which=which), fake


def _probe_tra(monkeypatch, status):
    import company.deploy as D

    monkeypatch.setattr(D, "http_probe", lambda url: status)


# ---------- đường đi chính: hai phần (up + smoke), không có `ps` như compose ----------


def test_duong_hanh_phuc_ok_khong_goi_down(tmp_path, monkeypatch):
    _probe_tra(monkeypatch, 200)
    r, fake = _deploy(tmp_path)
    assert r.ok is True and r.error == "" and r.skipped == ""
    assert r.port == 8080 and r.smoke["http_status"] == 200 and r.started_at
    assert r.services == () and r.container_ids == (), "process mode không có khái niệm container"
    assert fake.subs == ["up"], f"đường hạnh phúc KHÔNG được gọi down: {fake.subs}"


def test_up_that_bai_thi_khong_ok_va_co_down(tmp_path, monkeypatch):
    r, fake = _deploy(tmp_path, up=(1, "", "loi khoi dong"))
    assert r.ok is False and "up:" in r.error and "loi khoi dong" in r.error
    assert fake.subs == ["up", "down"]


def test_smoke_do_thi_khong_ok_va_co_down(tmp_path, monkeypatch):
    _probe_tra(monkeypatch, 500)
    r, fake = _deploy(tmp_path)
    assert r.ok is False and "smoke" in r.error
    assert r.port == 8080 and r.smoke["ok"] is False
    assert fake.subs == ["up", "down"], "smoke hỏng cũng phải down — không bỏ lại tiến trình nửa sống"


def test_smoke_khong_tra_loi_trong_timeout_thi_ghi_ly_do(tmp_path, monkeypatch):
    _probe_tra(monkeypatch, None)
    r, fake = _deploy(tmp_path)
    assert r.ok is False and r.smoke.get("error", "").startswith("không trả lời")
    assert fake.subs == ["up", "down"]


def test_thieu_cong_rt_port_thi_bao_loi_khong_the_probe(tmp_path):
    rt = Runtime(RT.command, path=RT.path, timeout_s=2, port=0, deploy=RT.deploy)
    r, fake = _deploy(tmp_path, rt=rt)
    assert r.ok is False and "cổng" in r.error
    assert fake.subs == ["up", "down"], "up đã chạy (thành công) nhưng không có cổng để probe vẫn phải down"


# ---------- `runtime.deploy` là script, không dò tên mặc định (khác compose) ----------


def test_khong_khai_deploy_thi_skipped_khong_doan_ten(tmp_path):
    rt = Runtime(RT.command, path=RT.path, timeout_s=2, port=8080, deploy="")
    r, _ = _deploy(tmp_path, rt=rt)
    assert r.skipped and "không khai" in r.skipped


def test_khai_script_khong_ton_tai_thi_skipped(tmp_path):
    rt = Runtime(RT.command, path=RT.path, timeout_s=2, port=8080, deploy="khong-co-that.sh")
    r, _ = _deploy(tmp_path, rt=rt)
    assert r.skipped


def test_deploy_script_doc_dung_tu_spec(tmp_path):
    repo = _repo(tmp_path)
    assert deploy_script(repo, RT) == "infra/staging/wsl/deploy_process.sh"
    assert deploy_script(repo, Runtime(RT.command, deploy="")) == ""


# ---------- fail-closed đúng khuôn compose ----------


def test_process_khai_dich_danh_ma_thieu_binary_thi_raise(tmp_path):
    with pytest.raises(DeployError, match="wsl"):
        deploy(
            _repo(tmp_path),
            "P1",
            "staging",
            RT,
            mode="process",
            binary="wsl.exe --cd . bash",
            run=FakeProcess(),
            which=lambda b: None,
        )


def test_runtime_thieu_dau_nhay_dong_thi_deploy_error_khong_phai_value_error(tmp_path):
    """`COMPANY_DEPLOY_RUNTIME` là cấu hình người vận hành gõ tay (đường dẫn Windows có dấu nháy). Gõ thiếu nháy
    đóng thì `shlex.split` ném `ValueError` — `verify.py` chỉ bắt `DeployError` (fail-closed nhưng không giết
    orchestrator), nên lỗi cấu hình phải đi đúng đường đó và nói rõ biến nào hỏng."""
    with pytest.raises(DeployError, match=ENV_RUNTIME):
        deploy(
            _repo(tmp_path),
            "P1",
            "staging",
            RT,
            mode="process",
            binary='wsl.exe --cd "C:\\khach bash',
            run=FakeProcess(),
            which=lambda b: b,
        )


def test_mac_dinh_binary_process_la_cau_noi_wsl(monkeypatch):
    monkeypatch.delenv(ENV_MODE, raising=False)
    monkeypatch.delenv(ENV_RUNTIME, raising=False)
    monkeypatch.setenv(ENV_MODE, "process")
    assert deploy_settings() == ("process", DEFAULT_RUNTIME_PROCESS)
    assert DEFAULT_RUNTIME_PROCESS.split()[0] == "wsl.exe"


def test_mac_dinh_binary_compose_khong_doi(monkeypatch):
    monkeypatch.delenv(ENV_MODE, raising=False)
    monkeypatch.delenv(ENV_RUNTIME, raising=False)
    assert deploy_settings() == ("auto", "docker")


# ---------- argv/prefix do CODE ghép ----------


def test_process_argv_chi_up_down():
    assert _process_argv(["bash"], "s.sh", "up") == ["bash", "s.sh", "up"]
    assert _process_argv(["bash"], "s.sh", "down") == ["bash", "s.sh", "down"]
    with pytest.raises(DeployError, match=r"up \| down"):
        _process_argv(["bash"], "s.sh", "logs")
    assert PROCESS_SUB == ("up", "down")


def test_prefix_thay_dau_cham_bang_duong_dan_repo(tmp_path):
    assert _process_prefix("wsl.exe --cd . bash", tmp_path) == ["wsl.exe", "--cd", str(tmp_path), "bash"]
    assert _process_prefix("bash", tmp_path) == ["bash"], "không có dấu chấm thì giữ nguyên (chạy bash trần)"


# ---------- bằng chứng giữ đúng hình dạng DeployRecord của ADR-0039 ----------

# ---------- `run` ném lỗi hệ thống: đọc được, không phải crash orchestrator ----------


def test_binary_bien_mat_giua_chung_thi_ly_do_doc_duoc(tmp_path):
    def raise_not_found(argv, **kw):
        raise FileNotFoundError

    r = deploy(
        _repo(tmp_path),
        "P1",
        "staging",
        RT,
        mode="process",
        binary="bash",
        run=raise_not_found,
        which=lambda b: f"/usr/bin/{b}",
    )
    assert r.ok is False and "không có trên máy" in r.error


def test_qua_gio_thi_ly_do_doc_duoc(tmp_path):
    def raise_timeout(argv, **kw):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kw.get("timeout", 0))

    r = deploy(
        _repo(tmp_path),
        "P1",
        "staging",
        RT,
        mode="process",
        binary="bash",
        run=raise_timeout,
        which=lambda b: f"/usr/bin/{b}",
    )
    assert r.ok is False and "quá" in r.error and "s" in r.error


def test_record_ok_co_verified_by_va_khong_co_container(tmp_path, monkeypatch):
    _probe_tra(monkeypatch, 200)
    r, _ = _deploy(tmp_path)
    rec = r.record()
    assert rec["verified_by"] == "orchestrator" and rec["ok"] is True
    assert "services" not in rec and "container_ids" not in rec, "rỗng thì record() không đưa vào (khớp compose)"
    assert rec["port"] == 8080 and "smoke" in rec


# ---------- output không phải UTF-8 của repo khách (họ lỗi #329) ----------

# Script khách in thẳng byte 0xe3 0x28 (không phải UTF-8 hợp lệ); viết bằng escape để file test chỉ có ASCII.
_IN_BYTE_LA = "import sys; sys.stdout.buffer.write(b'truoc \\xe3\\x28 sau\\n'); sys.stdout.flush()\n"


def test_process_giu_output_khi_script_khach_in_byte_khong_phai_utf8(tmp_path: Path) -> None:
    """Giải mã `encoding="utf-8"` không kèm `errors=`: Linux ném UnicodeDecodeError khỏi deploy, Windows chết ở luồng
    đọc và trả `stdout=None` → output mất lặng lẽ. Cùng khuôn #329 (git/gh), còn sót ở `deploy.py`."""
    import sys

    from company.deploy import _process_cmd

    (tmp_path / "run.py").write_text(_IN_BYTE_LA, encoding="utf-8")
    ok, out = _process_cmd(subprocess.run, [sys.executable], tmp_path, "run.py", "up", timeout=60)
    assert ok and "truoc" in out and "sau" in out, out


def test_compose_giu_output_khi_in_byte_khong_phai_utf8(tmp_path: Path) -> None:
    import sys

    from company.deploy import _compose

    (tmp_path / "compose").write_text(_IN_BYTE_LA, encoding="utf-8")  # `python compose ...` chạy chính file này
    ok, out = _compose(subprocess.run, sys.executable, tmp_path, "p", "docker-compose.yml", "ps", timeout=60)
    assert ok and "truoc" in out and "sau" in out, out
