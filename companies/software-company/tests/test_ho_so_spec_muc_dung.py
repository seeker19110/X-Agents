"""Hồ sơ gate spec đọc ĐÚNG mục NFR / ngoài phạm vi của PRD, không phải heading đầu tiên có chữ khớp.

Hub thật 2026-10-15 (QLKH-DD-CSV, SPEC-CR-DDCSV-SEC-006, prd v19): PRD có "### 0.2 Lỗi (2) của hint: NFR thiếu số
đo" (2 dòng, ghi lại lỗi đã sửa) đứng trước "## 5. NFR — rà theo ISO 25010" (11 dòng, đủ số đo). `_section` lấy heading
khớp ĐẦU TIÊN nên đếm 2 dòng không số đo, `reviewer:tu-dong` reject vì "bằng chứng máy nói khác ruling".
"""

from __future__ import annotations

from company.gate_brief import _NFR_HEAD, _OOS_HEAD, _section

PRD = """# PRD bổ sung v12

## 0. Thay đổi so với v11

### 0.2 Lỗi (2) của hint: NFR thiếu số đo
Bản trước thiếu ngưỡng. Đã sửa ở §5.

### 0.3 Out-of-scope đổi gì
- bỏ W-07

## 5. NFR — rà theo ISO 25010
| Mục | Ngưỡng |
|---|---|
| Thời gian chạy kiểm mới | ≤ 60 s |
| Tỉ lệ ca đỏ khi gỡ bản sửa | 100 % |
| Bộ test reachability | ≤ 30 s |

## 8. Out-of-scope (3 mục)
- W-01 không tách role DB
- W-02 không ký cosign
- W-03 không đẩy registry
"""


def test_nfr_doc_muc_nfr_that_khong_phai_dong_nhac_ten():
    sec = _section(PRD, _NFR_HEAD)
    assert sec is not None and "≤ 60 s" in sec and "Đã sửa ở §5" not in sec


def test_out_of_scope_doc_muc_that():
    sec = _section(PRD, _OOS_HEAD)
    assert sec is not None and "W-03" in sec and "bỏ W-07" not in sec


def test_mot_heading_khop_thi_nhu_cu():
    prd = "# P\n\n## NFR\n- p95 ≤ 200 ms\n\n## Khác\n- x\n"
    assert _section(prd, _NFR_HEAD) == "\n- p95 ≤ 200 ms\n\n"
    assert _section(prd, _OOS_HEAD) is None
