# ADR-0058: Gate release bị từ chối thì thành change request cho planner

Ngày: 2026-10-13 · Trạng thái: được chấp nhận (vận hành theo lệnh chủ repo "vận hành đi rồi fix dần cho đến khi hoàn
thiện") · Liên quan: ADR-0051 (`REPLAN-*`), ADR-0057 (`REWORK-*`), ADR gốc 0034 (agent duyệt tự động), ADR gốc 0035
(reviewer quyết CR ở phạm vi `toan-bo`).

## Bối cảnh — số đo

Hub thật 2026-10-13, `QLKH-DD-CSV`. Gate release (Gate 3) của REL-037 và REL-038 bị `reviewer:tu-dong` từ chối với cùng
một gap thật: `release.dashboard-alert`. api-contract có 3 endpoint mà infra chỉ nhắc `/healthz`, và không có dashboard,
alert hay runbook.

Đọc `_on_gate_decide` (`orch/gates_flow.py`): gate `release` khác `approve` không làm gì ngoài `_resume_overdue`. RC nằm
lại staging, lý do từ chối không tới agent nào, không ticket nào được lập. RC kế tiếp lên Gate 3 thiếu đúng thứ đó và
bị từ chối y hệt. Vòng chỉ dừng khi người (hôm đó là phiên chính) đọc lý do rồi tự nộp change request (CR-DDCSV-OBS-001).

Escalation release đã có đường đi tiếp: `rework_release_tickets`, rồi ADR-0057 cho phần ngoài ticket. Gate release
chưa có.

## Quyết định

1. **Từ chối gate release → change request `GATE3-<RC>`.** Trong `_on_gate_decide`, nhánh `kind == "release"` và
   `decision == "reject"` gọi `DeliveryLead.request_change_after_release_reject(rid, reason)`. Hàm này phát
   `change-requests` dưới `LEAD_ACTOR` với `decision=pending`, `affects_requirements=[]` (đường `_cr_accepted_direct`
   của ADR-0051) và `impact={"kind": "release_gate_reject", "release_id", "tickets", "reason"}`. `description` mang
   nguyên lý do từ chối (root_cause/hint), vì đó là danh sách việc cần làm. Nó cũng nói rõ RC không đi tiếp và phần
   việc phải thành ticket MỚI.
2. **Đi đúng đường CR thường.** `product[plan]` ước lượng impact, reviewer hoặc người `decide-change`, rồi kế hoạch
   ticket mới ra. Không ai tự động chấp nhận: reviewer vẫn có thể từ chối CR, chẳng hạn khi lý do là hạ tầng tạm thời
   hay trùng một CR đang làm.
3. **Không đổi máy trạng thái.** Không thêm trạng thái hay dòng chuyển nào. RC bị từ chối vẫn nằm lại như trước (bị
   RC sau thay). Ticket của nó không bị đá về làm lại: gate release đánh giá bằng chứng của cả RC, không phải lỗi
   trong một ticket. Lỗi trong ticket đã có đường escalation.
4. **Một lần mỗi quyết định.** CR được nộp lúc xử lý event `gate.decide`. Event đó đánh dấu xử lý một lần (`_mark`),
   còn `DeliveryLead._emit` câm khi replay, nên mở lại bus không nộp lại.

## Cái giá đã biết

- Hai RC liên tiếp bị từ chối cùng lý do sẽ sinh hai CR cùng nội dung (REL-037 và REL-038 hôm đó). Reviewer chấp nhận
  một CR và từ chối CR còn lại. Máy không so lý do để gộp, vì so văn bản dễ gộp nhầm hai việc khác nhau.
- Lý do từ chối có thể chỉ là "chưa đủ bằng chứng" chứ không phải việc. CR vẫn được nộp, và product/reviewer thấy
  ngay rồi từ chối nó. Rẻ hơn để RC sau lại vấp đúng chỗ đó.

## Bổ sung 2026-10-16 — `release.dashboard-alert` đọc cả repo

Đo hub thật 2026-10-16 (QLKH-DD-CSV REL-106): gap `release.dashboard-alert` lặp lại lần thứ ba (sau CR-DDCSV-OBS-001
và GATE3-REL-074), dù DDCSV-93B đã merge `ops/observability/alerts.yaml` + `dashboard.yaml` phủ đủ 3 endpoint của
api-contract. Mục này chỉ đối chiếu artifact `infra` mới nhất. Bản v54 do DDCSV-101 ghi đè, không còn mục
Observability, nên hồ sơ ra [gap]. `reviewer:tu-dong` reject gate release, hub sinh GATE3-REL-106 để lập kế hoạch lần
ba cho việc đã xong. tu-dong giữ CR đó vì trùng việc, và phiên chính bác nó.

- Endpoint không có trong infra thì hồ sơ tìm tiếp trong file alert/dashboard trên nhánh tích hợp: `alert*`,
  `dashboard*` (`.yaml/.yml/.json`), mọi `.yaml/.yml/.json/.md` dưới `observability/`. Fact ghi đúng file nào nhắc
  endpoint; nguồn là `worktree` kèm `files`. Không có repo/nhánh thì như cũ, không đoán.
- Hai chiều: trước khi sửa thì `test_release_dashboard_doc_alert_dashboard_trong_repo_khi_infra_lam_roi` đỏ ([gap],
  0 endpoint được nhắc), sau khi sửa thì xanh. Chạy thử chỉ đọc trên hub thật: REL-107 ra [ok], 2 endpoint trong
  `ops/observability/alerts.yaml` và `dashboard.yaml`.

## Bổ sung 2026-10-16 (2) — CR mang nguyên văn lý do từ chối

Hub thật (QLKH-DD-CSV REL-109): lý do bác escalation dài khoảng 3300 ký tự và có hai nhóm chặn. CR `REWORK-REL-109-1`
cắt mô tả ở 1000 ký tự và `impact.reason` ở 500 ký tự. Vì vậy nhóm chặn 2 (QA đỏ ở `tests/dpia`) không tới product,
cũng không tới agent duyệt CR. Product đoán sai việc cần làm, còn `reviewer:tu-dong` giữ CR vì "mô tả bị cắt ở 'N'".

- `request_change_after_release_reject` dùng cùng trần với `REPLAN-*`/`REWORK-<ticket>-*`: mô tả `HINT_MAX + 1000`,
  `impact.reason` `HINT_MAX`. Lý do từ chối là danh sách việc, cắt đi là mất việc.
- Hai chiều: trước khi sửa thì `test_ly_do_dai_toi_planner_nguyen_van_ca_mo_ta_lan_impact` đỏ (đoạn cuối của lý do
  không có trong mô tả), sau khi sửa thì xanh.

## Phương án đã loại

- **Đá ticket của RC về làm lại như escalation.** Gap của gate release (dashboard, runbook, giao hàng) thường nằm
  ngoài code của ticket trong RC, và đó chính là vòng ADR-0057 vừa chặn.
- **Agent duyệt tự động tự nộp CR.** Nó chỉ đọc hồ sơ và ký. Nộp việc là của coordinator (`delivery-lead`), giống
  `REPLAN-*`/`REWORK-*`.
