# Human gate — checklist

Nguyên tắc: separation of duties, four-eyes cho production, timeout 24h (supervisor nhắc 12h), quá hạn KHÔNG tự đi tiếp.

## Gate 1 — Duyệt spec (sau khối nghiên cứu)
- [ ] Mọi yêu cầu truy vết được về nguồn
- [ ] NFR có số đo
- [ ] 100% Must có Gherkin
- [ ] 100% story Must có UX flow trong `design`, đủ 4 trạng thái
- [ ] Out-of-scope rõ
- [ ] Rủi ro High có mitigation và owner
- [ ] PII đã phân loại; DPIA có nếu cần
- [ ] Câu hỏi mở chỉ còn assumption đã ghi nhận
Kết quả: approve / request_changes(lý do) / reject

## Gate 2 — Duyệt plan (sau delivery-lead planning)
- [ ] C4 L1–L2 và ADR có
- [ ] API contract tồn tại
- [ ] Threat model v1 trong `threat-model`; High/Critical có mitigation hoặc ADR có người ký
- [ ] Ước lượng có cơ sở (tham chiếu `knowledge` hoặc PERT), ticket ≤ 1 ngày / ≤ 200k token
- [ ] Mọi ticket có `estimate_tokens`, `budget_tokens ≥ estimate × 1.5`
- [ ] Ticket chạm auth/payment/pii/crypto/upload/admin/external-api có `risk_tags`
- [ ] Phụ thuộc ngoài đã xác nhận; license dependency dự kiến hợp lệ
- [ ] Ngân sách token cho dự án được đặt; tổng estimate sprint ≤ ngân sách
Kết quả: approve / request_changes / reject

## Gate 3 — Duyệt release production
- [ ] Đã deploy staging; QA hồi quy + perf (so NFR) + a11y trên staging pass (`review-results` ticket_id=release_id)
- [ ] Mọi test và scan pass (SAST, SCA, DAST, license), SBOM có, artifact ký
- [ ] Ticket có risk_tags đều có review security pass
- [ ] Runbook và rollback đã thử; mỗi PR trong release có rollback plan
- [ ] Dashboard + alert (có runbook) cho dịch vụ/tính năng mới
- [ ] Changelog, docs, NOTICE cập nhật
- [ ] Error budget không âm
- [ ] Người duyệt ≠ người tạo release
Kết quả: approve / hold / rollback

## Gate 4 — Nghiệm thu của khách (account-manager tổ chức, khách ký)
- [ ] Kịch bản UAT map 1-1 với Must requirement trong PRD đã duyệt; không tiêu chí mới
- [ ] Chạy trên bản production (hoặc staging nếu hợp đồng quy định) với dữ liệu khách chấp thuận
- [ ] Finding truy vết về requirement_id; yêu cầu ngoài spec đi vào `change-requests`, không vào biên bản
- [ ] Người ký là người của khách; công ty không tự ký
Kết quả: accepted / conditional(danh sách còn lại + hạn) / rejected(lý do)

## Gate bất thường (supervisor escalate)
Orchestrator mở gate `escalation` (subject = ticket_id) khi ticket `blocked` (hết retry) hoặc supervisor `escalate`
(cùng lỗi lặp, im lặng quá timeout). `gate_cli approve <ticket> --reason "<hint>"` = mở lại ticket với hint, retry về 0,
resume; `reject` = đóng ticket. Checklist: root_cause đã rõ; hint đủ cụ thể để agent làm khác lần trước; ngân sách còn.

## Chỉ người được ký
- Chấp nhận rủi ro bảo mật (threat accepted)
- Ngoại lệ license (copyleft)
- Chuyển dữ liệu cá nhân ra nước ngoài
- Bật A/B test chạm PII
