"""DoD — cổng chặn PR merge khi ô "Definition of Done" hay "BÁO CÁO XÁC THỰC" còn mở.

pe2 P0 (`docs/thi-hanh/pe2.md`): PR không merge được khi mục "Definition of Done" hoặc khối "BÁO CÁO XÁC THỰC" còn ô `- [ ]`,
trừ ô có nhãn `(sau merge)`. Workflow pr-policy chạy script này qua env BODY; stderr in danh sách ô mở.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.cong_repo   # đọc file ngoài gói console → hook chạy cả ở chế độ nhanh (F6)
SCRIPT = ROOT / "scripts" / "pr_dod_check.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_script():
    """Tải script pr_dod_check.py bằng importlib."""
    spec = importlib.util.spec_from_file_location("pr_dod_check", SCRIPT)
    assert spec and spec.loader, f"Không tải được script {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_open_items_o_mo_trong_dod():
    """Ô mở trong DoD → main trả 1."""
    mod = _load_script()
    body = """## Definition of Done

- [x] Source/test/docs cùng PR.
- [ ] Review độc lập trước merge.
"""
    items = mod.open_items(body)
    assert items == ["Review độc lập trước merge."]


def test_open_items_o_mo_trong_bao_cao_xac_thuc():
    """Ô mở trong "BÁO CÁO XÁC THỰC — abc123" → 1."""
    mod = _load_script()
    body = """## BÁO CÁO XÁC THỰC — ae552c4bf2c82b3c9ff3fdc9c74964a34918d191

- [x] TDD: test đỏ trước.
- [ ] Review độc lập trước merge.
"""
    items = mod.open_items(body)
    assert items == ["Review độc lập trước merge."]


def test_open_items_o_mo_co_sau_merge():
    """Ô mở có `(sau merge)` → 0."""
    mod = _load_script()
    body = """## Definition of Done

- [ ] Review độc lập trước merge (sau merge).
"""
    items = mod.open_items(body)
    assert items == []


def test_open_items_o_mo_o_loai_thay_doi():
    """Ô mở ở "Loại thay đổi" → 0."""
    mod = _load_script()
    body = """## Loại thay đổi

- [x] feat
- [ ] breaking change

## Definition of Done

- [x] Source/test/docs.
"""
    items = mod.open_items(body)
    assert items == []


def test_open_items_than_rong():
    """Thân rỗng → 0."""
    mod = _load_script()
    items = mod.open_items("")
    assert items == []


def test_open_items_khong_co_dod():
    """Thân không có mục DoD → 0."""
    mod = _load_script()
    body = """## Tóm tắt

Cập nhật kiến trúc.

## Loại thay đổi

- [x] feat
"""
    items = mod.open_items(body)
    assert items == []


def test_open_items_o_mo_duoi_heading_level_3():
    """Ô mở dưới một `###` nằm trong DoD vẫn bị bắt."""
    mod = _load_script()
    body = """## Definition of Done

### Chi tiết

- [ ] Review độc lập.

## Ranh giới

- [ ] Cái này không kiểm.
"""
    items = mod.open_items(body)
    assert items == ["Review độc lập."]


def test_open_items_fixture_pr335():
    """Thân #335 nguyên văn → trả đúng 2 ô mở."""
    mod = _load_script()
    fixture_file = FIXTURES / "pr335_body.md"
    body = fixture_file.read_text(encoding="utf-8")
    items = mod.open_items(body)
    # Từ fixture: dòng 52 ở Definition of Done, dòng 61 ở BÁO CÁO XÁC THỰC
    assert len(items) == 2
    assert "Review độc lập trước merge." in items
    assert "Review độc lập trước merge; chưa tự merge hoặc bật runtime." in items


def test_main_tro_ve_0_khi_khong_co_o_mo():
    """main(argv) trả 0 khi không có ô mở."""
    mod = _load_script()
    body = """## Definition of Done

- [x] Source/test/docs.
"""
    result = mod.main(argv=[], environ={"BODY": body})
    assert result == 0


def test_main_tro_ve_1_khi_co_o_mo():
    """main(argv) trả 1 khi có ô mở."""
    mod = _load_script()
    body = """## Definition of Done

- [ ] Review độc lập.
"""
    result = mod.main(argv=[], environ={"BODY": body})
    assert result == 1


def test_main_doc_body_tu_env():
    """main đọc BODY từ environ dict."""
    mod = _load_script()
    result = mod.main(argv=[], environ={"BODY": ""})
    assert result == 0


def test_chuanhoa_rn():
    """Chuẩn hoá \\r\\n."""
    mod = _load_script()
    body = "## Definition of Done\r\n\r\n- [ ] Review.\r\n"
    items = mod.open_items(body)
    assert items == ["Review."]


def test_script_exit_code_qua_subprocess():
    """Workflow: script chạy qua subprocess với env BODY, exit 1 khi có ô mở."""
    body = """## Definition of Done

- [ ] Review độc lập.
"""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        # Ép stderr mặc định về ASCII để tái hiện runner Windows (cp1252): script phải tự ghi UTF-8,
        # không để ô tiếng Việt thành `\\u0111` trong log CI (đỏ thật ở #337, console-unit windows).
        env={**os.environ, "BODY": body, "PYTHONIOENCODING": "ascii:backslashreplace"},
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 1
    assert "Review độc lập." in result.stderr
    assert body not in result.stderr  # Không in lại cả thân PR


def test_script_exit_code_0_khi_khong_co_o_mo():
    """Script exit 0 khi không có ô mở."""
    body = """## Definition of Done

- [x] Review độc lập.
"""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env={**os.environ, "BODY": body},
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0


def test_workflow_step_trong_pr_policy():
    """Workflow: một test đọc `.github/workflows/pr-policy.yml` và khẳng định có bước chạy script."""
    pr_policy = ROOT / ".github" / "workflows" / "pr-policy.yml"
    content = pr_policy.read_text(encoding="utf-8")
    # Khẳng định có step chạy pr_dod_check.py với env BODY
    assert "pr_dod_check.py" in content
    assert "BODY:" in content or "${{ github.event.pull_request.body }}" in content


MAU_PR = ROOT / ".github" / "pull_request_template.md"


def test_mau_pr_chua_dien_chi_chan_cac_o_may_khong_kiem_duoc():
    """Audit 2026-10-10 F3+F5: DoD chỉ giữ ô máy không kiểm được (đặc tả/ADR, phạm vi, tài liệu, breaking change).
    Cổng, test đỏ trước, CHANGELOG đã có CI hoặc khối BÁO CÁO; nhật ký phiên chỉ là CẢNH BÁO ở `pr-policy.yml`
    (K8.4), nên không ô bị chặn nào được đòi `docs/sessions/` — trước đây ô CHANGELOG gộp cả nhật ký phiên."""
    o_mo = _load_script().open_items(MAU_PR.read_text(encoding="utf-8"))
    assert len(o_mo) == 4, o_mo
    assert not [o for o in o_mo if "docs/sessions" in o], o_mo


def test_mau_pr_tick_het_dod_thi_qua():
    """Mẫu mới vẫn chạy đúng với script: tick hết các ô DoD là qua, khối BÁO CÁO là code block không có ô."""
    mau = MAU_PR.read_text(encoding="utf-8").replace("- [ ]", "- [x]")
    assert _load_script().main(environ={"BODY": mau}) == 0
