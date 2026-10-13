# ADR-0057: Rework release không đổi code thì thành change request, RC trùng sha đã bị chặn thì không chạy lại

Ngày: 2026-10-13 · Trạng thái: được chấp nhận (chủ repo chọn "cả hai" 2026-10-13) · Liên quan: ADR-0034 (máy trạng thái
tách khỏi orchestrator), ADR-0051 (`REPLAN-*`: coordinator nộp CR, người/reviewer quyết), ADR gốc 0035 (reviewer quyết CR
ở phạm vi `toan-bo`), ADR-0056 (bằng chứng SCA/secret của máy).

## Bối cảnh — số đo

Hub thật 2026-10-13, `QLKH-DD-CSV`, sau CR-DDCSV-SEC-001. Security chặn release vì image nền còn CRITICAL/HIGH và route
đăng nhập chưa mount. Escalation release bị từ chối (`reject`) → `rework_release_tickets` đá **các ticket trong RC** về
`changes_requested`:

| RC | ticket trong RC | integration sha | security |
|---|---|---|---|
| REL-022 | DDCSV-21, 22 | 4ef9665 | block (image, login 404) |
| REL-023 | DDCSV-22 | 4ef9665 | block, y hệt |
| REL-024 | DDCSV-25 | 4ef9665 | block, y hệt |
| REL-025 | DDCSV-21 | 4ef9665 | block, y hệt |
| REL-031…034 | DDCSV-28/29/30 | 4b53291 ×4 | block, y hệt |

Việc mà lý do từ chối đòi (nâng image nền, `apt-get upgrade`, hồ sơ ngoại lệ CVE) **không nằm trong code của ticket nào
trong RC**. Builder đọc hint, đúng đắn kết luận "không có gì để sửa trong phạm vi ticket" (`no_changes_confirmed`,
ADR-0028), nộp lại **đúng commit cũ** → review pass → `approved` → `flush_releases` sinh RC mới trên **cùng sha** →
security chặn y hệt → reject → rework… Mỗi vòng: một lượt builder, qa, security (claude-opus), ops, deploy, quét
trivy/gitleaks/DAST. Không vòng nào đổi một dòng code.

Hai thứ code đã biết mà không dùng:

1. Lúc PR tới, `branch_ahead(o, tid)` (`orch/worktree_flow.py`) trả lời được "nhánh ticket có commit nào chưa nằm trong
   nhánh tích hợp không". Ticket đã tích hợp + nhánh không đi trước = rework không đổi code. Đây là **sự thật git**, không
   phải lời khai của builder.
2. Lúc RC được staged, `release_sha` của mọi RC trước đã có, và `review-results` của security cho từng RC cũng có.

## Quyết định

1. **Rework không đổi code → change request, không review lại.** Dòng `TICKET_TRANSITIONS` mới (`rework_no_change`,
   topic `pull-requests`, chạy sau `superseded`): ticket nằm trong `integrated`, `branch_ahead` là False, ticket đang
   `in_review`. Khi khớp:
   - audit `rework.no_change` (`ticket_id`, `pr_ref`, `releases` chứa ticket);
   - `DeliveryLead.mark_done_already_integrated(tid)`: ticket về `merged` (đường có sẵn từ 2026-09-06), **không**
     `approved` nên `flush_releases` không sinh RC mới;
   - `DeliveryLead.request_change_after_noop_rework(tid)`: phát `change-requests` `REWORK-<ticket>-<retry>` dưới
     `LEAD_ACTOR`, `decision=pending`, `affects_requirements=[]` (đường `_cr_accepted_direct` của ADR-0051),
     `impact={"kind": "rework_no_change", "ticket_id", "retry", "releases", "hint"}`. `description` mang nguyên hint của
     lần từ chối, vì đó là danh sách việc cần làm, và nói rõ việc đó nằm **ngoài** ticket;
   - đánh dấu event xử lý xong, không giao reviewer/qa/security.
   CR đi đúng đường CR thường: `product[plan]` ước lượng impact → reviewer/người `decide-change` → kế hoạch ticket mới.
2. **RC trùng sha với một RC đã bị security chặn → không chạy lại.** Sau `release.staged`, nếu một RC **trước** của cùng
   dự án có cùng `release_sha` và `review-results` của security mang `verdict=block`, thì RC mới không giao ops/security/qa.
   Thay vào đó (trong `_act_integrate_rc`, dòng `integrate_rc` có sẵn — không thêm dòng chuyển): audit `release.duplicate_sha` (`release_id`, `sha`, `same_as`), huỷ RC (`_void`) và đưa ticket của nó về
   `merged` (`mark_done_already_integrated`, cùng lý do như nhánh `_superseded_release`: không thì `flush_releases`
   tạo RC trùng ngay nhịp sau). Escalation của RC trước vẫn là nơi quyết. Đây là lưới thứ hai: quyết định 1 chặn vòng
   ở gốc; quyết định 2 bắt các đường khác cùng sinh ra RC không đổi gì (approve rồi chạy lại, mở lại bus…).
3. **Không đổi `rework_release_tickets`.** Từ chối escalation release vẫn đá ticket về làm lại: khi finding đúng là lỗi
   trong code của ticket, builder sửa, nhánh đi trước, và quyết định 1 không khớp. Máy không đoán finding thuộc ticket
   nào. Nó đo kết quả: có commit mới hay không.
4. **Máy trạng thái ticket/release không thêm trạng thái.** Thêm một dòng chuyển (`rework_no_change` ở
   `TICKET_TRANSITIONS`) và một nhánh trong `_act_integrate_rc` (dòng `integrate_rc` có sẵn). Cả hai dùng chuyển đã
   có (`in_review→approved→merged`, `_void`).

## Cài đặt

Một PR, hai commit: quyết định 1 + 3 (`orch/ticket_fsm.py`, `delivery.py`), rồi quyết định 2
(`orch/release_fsm.py::_blocked_same_sha`, gọi trong `_act_integrate_rc` ngay sau `_integrate`).

## Cái giá đã biết

- Một CR mỗi (ticket, retry). Một reject release chứa n ticket không đổi code sinh n CR cùng nội dung. Reviewer gộp
  bằng cách chấp nhận một CR và từ chối các CR còn lại. Chấp nhận được vì RC đo được chỉ có 1–2 ticket.
- `branch_ahead` cần worktree ticket còn tồn tại. Worktree đã dọn thì nó trả False, nhưng ticket không có worktree thì
  builder cũng không nộp PR được, nên ca này không xảy ra trên đường PR.
- Quyết định 2 dựa vào `verdict=block` của security, không so từng finding. Hai RC cùng sha thì cùng code, cùng image,
  cùng bằng chứng máy (ADR-0056 quét theo sha). Khác biệt duy nhất có thể có là chính sách đã được miễn (approve/waive),
  mà khi đó RC trước đã qua chứ không còn block.

## Phương án đã loại

- **Cho reviewer tự duyệt `approve` (miễn) thay `reject`.** Chấp nhận rủi ro CVE thay khách, đổi chính sách bảo mật của
  dự án. Agent duyệt tự động đã từ chối đúng lý do đó.
- **Phân loại finding theo file ticket chạm.** Finding image/DPIA/route chưa mount không có `location` nằm trong diff,
  nhưng finding code thì có thể nằm ở file ticket không chạm. Đoán, không đo.
- **Chặn ở builder (cấm `no_changes_confirmed` sau rework release).** Builder nói đúng. Chặn nó chỉ đổi vòng lặp thành
  `invalid_output` → blocked → escalation, đúng vòng ADR-0051 §Bối cảnh đã tả.

## Đo hai chiều

- Bỏ dòng `rework_no_change` ⇒ test "rework release không đổi code thành CR, không review lại" đỏ (reviewer bị gọi, RC
  mới sinh ra).
- Nhánh có commit mới sau rework ⇒ review chạy như cũ (chiều ngược, cùng test file).
- Bỏ nhánh `_blocked_same_sha` ⇒ `test_rc_trung_sha_voi_rc_da_bi_security_chan_thi_khong_chay_lai` đỏ; RC trước cùng
  sha mà security pass ⇒ RC mới chạy như cũ (`test_rc_trung_sha_voi_rc_da_qua_thi_chay_binh_thuong`).
