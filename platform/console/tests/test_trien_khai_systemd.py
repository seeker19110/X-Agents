"""Cổng cho triển khai bằng systemd user unit (ADR gốc 0032): `deploy/systemd/` + `scripts/systemd.sh`.

Unit file là cấu hình mà KHÔNG chạy trong CI nào — sai một cờ (`--watch` gõ nhầm, module đổi tên) thì chỉ lộ ra lúc
máy chủ khởi động lại, tức lúc không ai nhìn. Nên mỗi phép ở đây đo cái thật: render bằng chính script người vận
hành chạy, `systemd-analyze verify` trên file vừa render, và mọi cờ trong `ExecStart` phải có trong `--help` thật
của module đó.

Đặt ở `platform/console/tests/` theo lối `test_cong_khung.py`: console là nơi repo đặt các phép canh cấp gốc.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "systemd.sh"
MAU = ROOT / "deploy" / "systemd"
DICH_VU = ("xagents-gateway", "xagents-orchestrator", "xagents-console", "xagents-keeper", "xagents-reviewer")
CHO_TRONG = re.compile(r"@[A-Z_]+@")

pytestmark = pytest.mark.cong_repo


def _chay(*args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **env},
        cwd=ROOT,
    )


@pytest.fixture(scope="module")
def da_render(tmp_path_factory: pytest.TempPathFactory) -> Path:
    dich = tmp_path_factory.mktemp("units")
    kq = _chay("render", str(dich))
    assert kq.returncode == 0, kq.stderr
    return dich


def _unit(dich: Path, ten: str) -> dict[str, list[str]]:
    """Khoá → mọi giá trị (systemd cho phép một khoá lặp lại), bỏ dòng chú thích và tiêu đề mục."""
    out: dict[str, list[str]] = {}
    for dong in (dich / f"{ten}.service").read_text(encoding="utf-8").splitlines():
        if not dong or dong.startswith(("#", ";", "[")) or "=" not in dong:
            continue
        k, v = dong.split("=", 1)
        out.setdefault(k.strip(), []).append(v.strip())
    return out


def test_render_sinh_du_bon_unit_khong_con_cho_trong(da_render: Path) -> None:
    assert sorted(p.stem for p in da_render.glob("*.service")) == sorted(DICH_VU)
    for ten in DICH_VU:
        than = (da_render / f"{ten}.service").read_text(encoding="utf-8")
        assert not CHO_TRONG.search(than), f"{ten}: còn chỗ trống chưa thay: {CHO_TRONG.findall(than)}"
        u = _unit(da_render, ten)
        exe = shlex.split(u["ExecStart"][0])[0]
        assert Path(exe).is_absolute() and os.access(exe, os.X_OK), (
            f"{ten}: ExecStart phải là đường dẫn tuyệt đối chạy được: {exe}"
        )
        wd = Path(u["WorkingDirectory"][0])
        assert wd.is_dir() and ROOT in (wd, *wd.parents), (
            f"{ten}: WorkingDirectory phải là thư mục có thật trong repo: {wd}"
        )


def test_systemd_analyze_verify_chap_nhan_moi_unit(da_render: Path) -> None:
    """Đúng trình phân tích systemd dùng lúc nạp: khoá gõ sai, `Type=` lạ, binary không có đều đỏ ở đây."""
    sa = shutil.which("systemd-analyze")
    assert sa is not None, "repo chỉ chạy trên Linux (ADR gốc 0031) — thiếu systemd-analyze là môi trường hỏng"
    kq = subprocess.run(
        [sa, "verify", *map(str, sorted(da_render.glob("*.service")))],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    loi = [d for d in (kq.stdout + kq.stderr).splitlines() if "xagents-" in d]
    assert kq.returncode == 0 and not loi, kq.stdout + kq.stderr


def _help(mod: str, *sub: str) -> str:
    kq = subprocess.run(
        ["uv", "run", "--no-sync", "python", "-m", mod, *sub, "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    assert kq.returncode == 0, f"{mod} {' '.join(sub)} --help: {kq.stderr}"
    return kq.stdout


@pytest.mark.parametrize("ten", DICH_VU)
def test_moi_co_trong_execstart_co_that_trong_cli(da_render: Path, ten: str) -> None:
    """Cờ gõ nhầm trong unit = dịch vụ chết vòng lặp `Restart=` lúc 3 giờ sáng; đo bằng `--help` thật."""
    argv = shlex.split(_unit(da_render, ten)["ExecStart"][0])
    mod = argv[argv.index("-m") + 1]
    sau = [a for a in argv[argv.index("-m") + 2 :] if not a.startswith("$")]
    goc = _help(mod)
    lenh_con = re.search(r"\{([a-z,_-]+)\}", goc)
    sub = [a for a in sau if lenh_con and a in lenh_con.group(1).split(",")]
    van_ban = goc + "".join(_help(mod, s) for s in sub)
    thieu = [c for c in sau if c.startswith("--") and not re.search(rf"(?<![\w-]){re.escape(c)}(?![\w-])", van_ban)]
    assert not thieu, f"{ten}: cờ không có trong CLI của {mod}: {thieu}"


def test_dung_bang_sigint_va_tu_khoi_dong_lai_khi_chet(da_render: Path) -> None:
    """SIGINT chứ không SIGTERM: orchestrator bắt `KeyboardInterrupt` để trả lease, console để xoá file token
    (`cli_cmds.run`, `console.__main__`). SIGTERM giết thẳng, bỏ qua cả hai."""
    for ten in DICH_VU:
        u = _unit(da_render, ten)
        assert u.get("KillSignal") == ["SIGINT"], ten
        assert u.get("Restart") == ["on-failure"], ten
        assert any(v.startswith("-%h/.config/x-agents/hub.env") for v in u.get("EnvironmentFile", [])), ten


def test_python_khong_dem_stdout_de_log_vao_journal_ngay(da_render: Path) -> None:
    """stdout ra pipe (journald) thì Python đệm theo khối: đo thật 2026-10-11, console + orchestrator chạy dưới
    systemd mà `journalctl` có 0 dòng của chương trình — địa chỉ kèm token của console không bao giờ hiện ra."""
    for ten in DICH_VU:
        assert "PYTHONUNBUFFERED=1" in _unit(da_render, ten).get("Environment", []), ten


def test_console_khong_tu_bat_dong_co_va_chi_nghe_loopback(da_render: Path) -> None:
    """Orchestrator đã có unit riêng: console mà cũng `--allow-engine` thì hai tiến trình tranh một lease. Và console
    không có xác thực ngoài token phiên — chỉ nghe 127.0.0.1, từ xa thì SSH tunnel."""
    argv = _unit(da_render, "xagents-console")["ExecStart"][0]
    assert "--allow-engine" not in argv and "--i-know" not in argv and "0.0.0.0" not in argv


def test_install_chep_env_mau_quyen_0600_va_khong_de_env_co_san(tmp_path: Path) -> None:
    cfg = tmp_path / "cfg"
    kq = _chay("install", XDG_CONFIG_HOME=str(cfg), SYSTEMCTL="true")
    assert kq.returncode == 0, kq.stderr
    env = cfg / "x-agents" / "hub.env"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert not CHO_TRONG.search(env.read_text(encoding="utf-8"))
    assert sorted(p.stem for p in (cfg / "systemd" / "user").glob("*.service")) == sorted(DICH_VU)
    env.write_text("ORCHESTRATOR_ARGS=--repo /srv/khach\n", encoding="utf-8")
    assert _chay("install", XDG_CONFIG_HOME=str(cfg), SYSTEMCTL="true").returncode == 0
    assert env.read_text(encoding="utf-8") == "ORCHESTRATOR_ARGS=--repo /srv/khach\n", "cài lại không được đè cấu hình"


def test_env_mau_khong_mang_gia_tri_bi_mat() -> None:
    for dong in (MAU / "hub.env.example").read_text(encoding="utf-8").splitlines():
        if dong.startswith("#") or "=" not in dong:
            continue
        k, v = dong.split("=", 1)
        if re.search(r"TOKEN|KEY|SECRET|PASSWORD", k):
            assert v == "", f"{k} trong file mẫu phải để trống — bí mật chỉ điền trên máy chủ"


def test_env_mau_claude_code_bang_bien_moi_truong_du_chay_mot_du_an(monkeypatch: pytest.MonkeyPatch) -> None:
    """Đo 2026-10-12 trên hub thật: chỉ đặt `COMPANY_LLM_PROVIDER=claude-code` (ghi đè llm.yaml, xoá `backends:`) thì
    dự án đầu tiên kẹt hai lần — product thiếu model tier `strong`, rồi `research-findings` thiếu vòng tool. Khối mẫu
    bỏ dấu `#` phải tự đủ: model cho cả ba tier và cầu MCP (ADR-0024), đọc bằng đúng `load_config` orchestrator dùng."""
    from company.llm import load_config

    khoi = [
        d.removeprefix("# ").split("=", 1)
        for d in (MAU / "hub.env.example").read_text(encoding="utf-8").splitlines()
        if re.match(r"# COMPANY_[A-Z_]+=\S", d)
    ]
    assert khoi, "hub.env.example thiếu khối mẫu cấu hình model bằng biến môi trường"
    for k in [k for k in os.environ if k.startswith("COMPANY_")]:
        monkeypatch.delenv(k)
    for k, v in khoi:
        monkeypatch.setenv(k, v)
    cfg = load_config(Path("/khong/co/llm.yaml"))
    assert cfg.provider == "claude-code"
    tier = ("strong", "standard", "light")
    assert {t: cfg.models.get(t) for t in tier} == {t: cfg.model_for(t) for t in tier}, "mỗi tier một model riêng"
    assert cfg.mcp_tools, "claude-code không có cầu MCP thì agent cần tool (product research-findings, dev…) kẹt"


def test_script_systemd_co_bit_thuc_thi_trong_git() -> None:
    kq = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-s", "scripts/systemd.sh"], capture_output=True, text=True
    )
    assert kq.stdout.startswith("100755 "), "người vận hành gọi thẳng scripts/systemd.sh — cần 100755"
