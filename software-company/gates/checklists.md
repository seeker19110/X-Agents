# Human gate — checklist

Nguyên tắc: separation of duties, four-eyes cho production, timeout 24h (supervisor nhắc 12h), quá hạn KHÔNG tự đi tiếp.

Mỗi gate dưới đây tách làm hai phần:
- **Code gửi kèm** — đúng các khoá trong `GateRequest(...).checklist` mà `src/company/orchestrator.py` và
  `src/company/delivery.py` sinh ra; đây là thứ hiện lên trong `gate_cli list`. Code dựng danh sách và điều kiện
  mở gate, còn việc từng mục có đạt hay không thì người duyệt xác nhận.
- **Người tự kiểm thêm** — không có trong payload, không có tên khoá; người duyệt phải tự đọc và trả lời.

`GateKind` hiện có đúng bốn giá trị: `spec`, `plan`, `release`, `escalation` (`src/company/gates.py`).

## Gate 1 — Duyệt spec (kind `spec`, subject `SPEC-<project>`)
Code gửi kèm: `prd`, `acceptance-criteria`, `ux-flow`, `risks`
- [ ] `prd` — PRD tồn tại, mọi yêu cầu truy vết được về nguồn
- [ ] `acceptance-criteria` — 100% Must có Gherkin
- [ ] `ux-flow` — 100% story Must có UX flow trong `design`, đủ 4 trạng thái
- [ ] `risks` — rủi ro High có mitigation và owner

Người tự kiểm thêm:
- [ ] NFR có số đo
- [ ] Out-of-scope rõ
- [ ] PII đã phân loại; DPIA có nếu cần
- [ ] Câu hỏi mở chỉ còn assumption đã ghi nhận

Kết quả: approve / request_changes(lý do) / reject

## Gate 2 — Duyệt plan (kind `plan`, subject `PLAN-<project>-<n>`)
Code gửi kèm: `tickets`, `estimate_tokens`, `risk_tags`, `depends_on`, `threat-model`, `architecture`, `api-contract`
- [ ] `tickets` — danh sách ticket của plan; ticket ≤ 1 ngày / ≤ 200k token
- [ ] `estimate_tokens` — mọi ticket có `estimate_tokens`, `budget_tokens ≥ estimate × 1.5`
- [ ] `risk_tags` — ticket chạm auth/payment/pii/crypto/upload/admin/external-api có `risk_tags`
- [ ] `depends_on` — phụ thuộc giữa ticket khai đúng, không vòng
- [ ] `threat-model` — threat model v1 trong `threat-model`; High/Critical có mitigation hoặc ADR có người ký
- [ ] `architecture` — C4 L1–L2 và ADR trên blackboard trước khi gate mở
- [ ] `api-contract` — API contract tồn tại

Người tự kiểm thêm:
- [ ] Ước lượng có cơ sở (tham chiếu `knowledge` hoặc PERT)
- [ ] Phụ thuộc ngoài đã xác nhận; license dependency dự kiến hợp lệ
- [ ] Ngân sách token cho dự án được đặt; tổng estimate sprint ≤ ngân sách

Ghi chú: một phần các mục trên đã bị `_check_plan` chặn trước khi gate mở (plan có `problems` thì bị từ chối,
không xin gate). Gate là lớp thứ hai, không phải lớp duy nhất.

Kết quả: approve / request_changes / reject

## Gate 3 — Duyệt release production (kind `release`, subject `<release_id>`)
Điều kiện mở: delivery-lead chỉ xin gate khi đã có review `qa` pass (cộng `security` pass nếu release chứa
ticket có `risk_tags`).

Code gửi kèm: `tests`, `scan`, `regression-staging`, `perf`, `a11y`, `runbook`, `rollback`
- [ ] `tests` — mọi test pass
- [ ] `scan` — SAST, SCA, DAST, license pass; SBOM có; artifact ký
- [ ] `regression-staging` — QA hồi quy trên staging pass (`review-results` ticket_id=release_id)
- [ ] `perf` — perf so NFR trên staging pass
- [ ] `a11y` — a11y (axe + thủ công) trên staging pass
- [ ] `runbook` — runbook đã thử
- [ ] `rollback` — rollback đã thử; mỗi PR trong release có rollback plan

Người tự kiểm thêm:
- [ ] Dashboard + alert (có runbook) cho dịch vụ/tính năng mới
- [ ] Changelog, docs, NOTICE cập nhật
- [ ] Error budget không âm
- [ ] Người duyệt ≠ người tạo release

Kết quả: approve / hold / rollback

## Gate 4 — Nghiệm thu của khách (kind `acceptance`, subject = `UAT-<release_id>`)
Khi `release-events` báo đã deploy production, orchestrator mở gate `acceptance`. Đây là gate thật: có trong
`gate_cli`, có hạn 24h, nhắc ở 12h, quá hạn thì supervisor escalate. Account-manager tổ chức UAT; khách ký và
kết quả vào topic `acceptance-results` (key = `release_id`), chính chữ ký đó đóng gate — `signed_by` phải khác
`account-manager` (four-eyes), nên công ty không tự ký thay khách. `verdict = conditional` đóng gate ở dạng
`request_changes` và phần còn lại đi qua `change-requests`; ticket chỉ `closed` khi khách accepted.

Code gửi kèm: `uat-script`, `acceptance-criteria`, `known-issues`, `signed_by`
- [ ] `uat-script` — kịch bản UAT map 1-1 với Must requirement trong PRD đã duyệt; không tiêu chí mới
- [ ] `acceptance-criteria` — tiêu chí nghiệm thu trong SOW đã được đối chiếu từng mục
- [ ] `known-issues` — lỗi đã biết được nêu trước khi ký, không giấu
- [ ] `signed_by` — người ký là người của khách (code từ chối nếu trùng account-manager)

Người tự kiểm thêm:
- [ ] Chạy trên bản production (hoặc staging nếu hợp đồng quy định) với dữ liệu khách chấp thuận
- [ ] Finding truy vết về requirement_id; yêu cầu ngoài spec đi vào `change-requests`, không vào biên bản

Kết quả (ghi vào `acceptance-results`): accepted / conditional(danh sách còn lại + hạn) / rejected(lý do)

## Gate bất thường (kind `escalation`, subject = ticket_id)
Orchestrator mở gate khi ticket `blocked` (hết retry) hoặc supervisor `escalate` (cùng lỗi lặp, im lặng quá timeout).

Code gửi kèm: `root_cause`, `decision:reopen|close`, `hint`
- [ ] `root_cause` — nguyên nhân đã rõ
- [ ] `decision:reopen|close` — chọn mở lại hay đóng
- [ ] `hint` — đủ cụ thể để agent làm khác lần trước

Người tự kiểm thêm:
- [ ] Ngân sách còn

`gate_cli approve <ticket> --reason "<hint>"` = mở lại ticket với hint, retry về 0, resume; `reject` = đóng ticket.

## Chỉ người được ký
- Chấp nhận rủi ro bảo mật (threat accepted)
- Ngoại lệ license (copyleft)
- Chuyển dữ liệu cá nhân ra nước ngoài
- Bật A/B test chạm PII
