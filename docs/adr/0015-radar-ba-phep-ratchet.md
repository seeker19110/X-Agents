# ADR-0015 — Không xây "arch-health-radar"; chỉ thêm trần `branch = true`

- Trạng thái: được chấp nhận
- Ngày: 2026-09-14

## Bối cảnh

`docs/reports/2026-09-14-doi-chieu-projects-template.md` (#295) xếp `scripts/arch-health-radar.sh` của
`seeker19110/projects-template` vào cột 2 — "đã có nhưng nông hơn" — và **hoãn** với lý do "PR riêng có test".
Phiên này làm PR đó: dựng `keeper.radar` với ba phép ratchet rút từ `docs/TASK-PACK.md` §tám phép đo, đủ test,
100% dòng + nhánh, cổng `keeper` xanh.

Rồi `make test` đỏ ở `platform/console/tests/test_cong_repo.py::test_skip_xfail_khong_vuot_tran`. Đọc file đó
mới thấy **hai trong ba phép đã có cổng từ 2026-09-12**, và cổng có sẵn mạnh hơn bản đang viết:

| Phép định làm | Đã có | Mạnh hơn ở chỗ |
|---|---|---|
| R1 — sổ miễn trừ (A5) | `test_pragma_no_cover_khong_vuot_tran`, `test_skip_xfail_khong_vuot_tran`, `test_omit_khong_vuot_tran` | **bằng đúng**, không phải "không vượt": bớt một lối thoát cũng đỏ, nên sổ không trôi được theo chiều nào; lại tách trần theo từng package |
| R3 — cổng còn hiệu lực (A8) | `test_quality_needs_phu_moi_job_con` (dòng 91) | cùng thuật toán (parse YAML, `set(jobs) - needs - {"quality"}`), đã nằm trong CI |
| R2 — độ sâu phép đo (A6) | **không có gì** | — |

Bản radar còn vấp đúng bẫy mà cổng có sẵn đã giải xong: bộ đếm tự khớp chính nó (dòng định nghĩa regex chứa
`skipif`; khoá `skip_xfail` chứa `xfail`) cho 19 thay vì 9. `test_cong_repo.py` giải bằng một hằng số ba chữ —
`_TU_NO = "test_cong_repo.py"`, bỏ chính nó ra khỏi phép đếm.

## Quyết định

**Không xây radar.** Xoá `keeper/radar.py` + `tests/test_radar.py` đã viết trong phiên này thay vì sửa cho
chúng sống chung với cổng có sẵn: hai bộ đếm cùng một thứ, hai baseline phải khớp nhau bằng tay, là một nguồn
lệch mới — đúng thứ `AGENTS.md` luật cấm 5 chặn ở bản dẫn xuất.

**Thêm đúng phép còn thiếu**: `test_branch_coverage_khong_tut` trong `test_cong_repo.py`, theo đúng khuôn sổ
`TRAN_*` của file đó. `fail_under = 100` trên **dòng** vẫn để lọt nhánh chưa đi (A6); ba package đã bật
`branch = true` (`software-company`, `keeper`, `xagents-core`), `gateway` và `console` chưa. Sổ ghi đúng tập
chưa bật; một package tụt khỏi danh sách đã bật ⇒ đỏ; bật xong một package ⇒ cũng đỏ tới khi hạ sổ.

## Từ chối

**Không port `arch-health-radar.py`.** Docstring của nó tự khai đo "độ phủ cổng CI trên từng script, mật độ
chú thích, nợ TODO" và **cố ý không đo coupling/complexity** vì repo đó là tài liệu + script. Không phép nào
trong đó nói được gì về năm package Python có đồ thị import thật.

**Không có "điểm tổng"** kiểu `100/100`: một con số gộp che mất phép nào đang đỏ, và mời người ta tối ưu con số
thay vì sửa thứ nó đo.

**A1/A2/A3/A4/A7 vẫn của người.** A1/A2 đã có cổng (`test_readme_goc.py`, `test_cong_repo.py`); A4 tự khai
"chậm và không tự động hoá được"; A7 đo được nhưng "bao nhiêu là cũ" chưa có cơ sở. A3 bị loại **sau khi đo**:
bộ dò thử (chữ số + số đếm tiếng Việt trước chữ "package", đã bỏ `CHANGELOG.md`/`docs/sessions`/`docs/reports`/
`docs/archive`/`docs/adr` vì đó là bản ghi lịch sử) trả **42 hit trên `main` @`f1dffa5`, gần như toàn bộ dương
tính giả** — "ba package" ở `README.md:134` nghĩa là *ba trong số các package*. Phân biệt hai nghĩa cần đọc câu.

## Hệ quả

- Bài học đắt hơn tính năng: đối chiếu repo ngoài (`docs/PROMPT-SHEET.md` §H) phải grep **cổng đang chạy**,
  không chỉ đọc văn xuôi mô tả vấn đề. `docs/TASK-PACK.md` A5 vẫn viết "không có trần, không ai đếm" — câu đó
  đã **lỗi thời** từ 2026-09-12; sửa nó là việc của phiên audit kế tiếp, ghi ở "Việc để lại".
- Sau PR này, ba trong bốn lối thoát khỏi `fail_under = 100` có trần, và độ sâu của chính `fail_under` có sổ.
- Khoảng cách thật còn lại: `gateway` và `console` bật `branch = true`. Sổ mới làm việc đó **nhìn thấy được**
  thay vì nằm trong một comment ở `companies/keeper/pyproject.toml`. **Đã đóng 2026-09-28 (#366)**: cả hai bật,
  sổ `CHUA_PHU_NHANH` rỗng; `# pragma: no branch` được đếm chung trần `TRAN_PRAGMA`
  (`docs/reports/2026-09-27-audit-hoan-thien.md` F-C, F-E).

## Liên quan

- `docs/TASK-PACK.md` §"Gói việc thường trực: audit toàn dự án" — tám phép A1–A8.
- `docs/reports/2026-09-14-doi-chieu-projects-template.md` cột 2 — chỗ ghi "hoãn, PR riêng có test".
- `platform/console/tests/test_cong_repo.py` — sổ `TRAN_*`, và `_TU_NO` (cách giải bẫy tự-đếm-mình).
