"""ADR-0054: lệnh `lock` cho builder — sinh lại lockfile Python bằng `uv` với mạng PyPI qua egress (ADR gốc 0010).

Đo hub thật 2026-10-12 (QLKH-DD-CSV/DDCSV-02): ticket thêm ba phụ thuộc vào `pyproject.toml` nhưng không sinh lại
được `requirements.lock` (sandbox tắt mạng, tool `run` chỉ có lint/test) → security chặn ba lần, ticket blocked, CR
replan. Đo hai chiều: không có công thức lock → `lock` không có trong allowlist; có → argv do code ghép từ công thức,
đi qua sandbox với `allowed_domains` PyPI (chỉ chế độ container), không nhận `paths`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from company.stacks import detect, lock_command
from company.tools import ToolError, WorkspaceTools
from test_sandbox_noi_vao_cong_ty import SpySandbox

PYPROJECT = "[project]\nname='app'\nversion='0'\ndependencies=['httpx']\n"
HEADER = (
    "# Lockfile runtime — CI cài frozen + --require-hashes.\n"
    "# Sinh bằng: uv pip compile pyproject.toml --generate-hashes --python-version 3.12 -o requirements.lock\n"
    "httpx==0.27.0 \\\n    --hash=sha256:abc\n"
)


def _repo(tmp_path: Path, **files: str) -> Path:
    root = tmp_path / "khach"
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    for name, body in files.items():
        (root / name).write_text(body, encoding="utf-8")
    return root


# ---------- công thức lock ----------


def test_uv_lock_thi_lenh_la_uv_lock(tmp_path):
    root = _repo(tmp_path, **{"uv.lock": "version = 1\n"})
    assert lock_command(root) == ["uv", "lock"]
    st = detect(root)
    assert st.lock == ["uv", "lock"] and st.commands()["lock"] == ["uv", "lock"]


def test_requirements_lock_doc_cong_thuc_tu_header(tmp_path):
    root = _repo(tmp_path, **{"requirements.lock": HEADER})
    assert lock_command(root) == [
        "uv",
        "pip",
        "compile",
        "pyproject.toml",
        "--generate-hashes",
        "--python-version",
        "3.12",
        "-o",
        "requirements.lock",
    ]


@pytest.mark.parametrize(
    "header",
    [
        "# Sinh bằng: uv pip compile pyproject.toml --index-url https://evil.example -o requirements.lock\n",  # cờ ngoài allowlist
        "# Sinh bằng: uv pip compile pyproject2.toml -o requirements.lock\n",  # file vào không tồn tại
        "# Sinh bằng: uv pip compile pyproject.toml -o ../requirements.lock\n",  # ghi ra ngoài gốc
        "# Sinh bằng: pip-compile pyproject.toml -o requirements.lock\n",  # không phải uv
        "# Sinh bằng: uv pip compile pyproject.toml -o requirements.lock; rm -rf /\n",
    "# Sinh bằng: uv pip compile \"pyproject.toml -o requirements.lock\n",  # ký tự shell
    ],
)
def test_header_khong_hop_le_thi_khong_co_lock(tmp_path, header):
    root = _repo(tmp_path, **{"requirements.lock": header})
    assert lock_command(root) is None, "fail-closed: công thức lạ thì không có lệnh, không đoán"
    assert "lock" not in detect(root).commands()


def test_khong_co_lockfile_thi_khong_co_lenh(tmp_path):
    root = _repo(tmp_path)
    assert lock_command(root) is None and "lock" not in detect(root).commands()
    (tmp_path / "node").mkdir()
    (tmp_path / "node" / "package.json").write_text("{}", encoding="utf-8")
    assert detect(tmp_path / "node").lock is None


# ---------- tool `run lock`: qua sandbox, có mạng PyPI chỉ ở chế độ container, không nhận paths ----------


def test_run_lock_di_qua_sandbox_voi_mang_pypi_o_che_do_container(tmp_path):
    root = _repo(tmp_path, **{"uv.lock": "version = 1\n"})
    spy = SpySandbox(name="container:xagents-qlkh:py3.12")
    out = WorkspaceTools(root, sandbox=spy).run("lock")
    assert out.startswith("exit=0")
    spec = spy.specs[-1]
    assert spec.argv == ["uv", "lock"] and spec.cwd == root.resolve()
    assert spec.allowed_domains == ("pypi.org", "files.pythonhosted.org")
    assert "ANTHROPIC_API_KEY" not in spec.env


def test_run_lock_che_do_subprocess_khong_khai_domain(tmp_path):
    root = _repo(tmp_path, **{"requirements.lock": HEADER})
    spy = SpySandbox(name="subprocess")
    WorkspaceTools(root, sandbox=spy).run("lock")
    assert spy.specs[-1].argv[:3] == ["uv", "pip", "compile"] and spy.specs[-1].allowed_domains == ()


def test_run_lock_khong_nhan_paths(tmp_path):
    root = _repo(tmp_path, **{"uv.lock": "version = 1\n"})
    with pytest.raises(ToolError, match="paths"):
        WorkspaceTools(root, sandbox=SpySandbox()).run("lock", paths=["pyproject.toml"])


def test_bang_tool_neu_ro_lock_co_mang(tmp_path):
    root = _repo(tmp_path, **{"uv.lock": "version = 1\n"})
    tb = WorkspaceTools(root, sandbox=SpySandbox()).toolbox()
    spec = next(t for t in tb.specs() if t.name == "run")
    assert "lock" in spec.parameters["properties"]["command"]["enum"] and "lock" in spec.description
    root2 = _repo(tmp_path / "b")
    spec2 = next(t for t in WorkspaceTools(root2, sandbox=SpySandbox()).toolbox().specs() if t.name == "run")
    assert "lock" not in spec2.parameters["properties"]["command"]["enum"]


def test_lockfile_khong_doc_duoc_thi_khong_co_lenh(tmp_path):
    root = _repo(tmp_path)
    (root / "requirements.lock").write_bytes(b"# Sinh b\xff\xfeng: uv pip compile pyproject.toml\n")
    assert lock_command(root) is None
