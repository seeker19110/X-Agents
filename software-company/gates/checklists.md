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
- [ ] Mọi test và scan pass (SAST, SCA, DAST, license), SBOM có, artifact ký
- [ ] Ticket có risk_tags đều có review security pass
- [ ] Runbook và rollback đã thử; mỗi PR trong release có rollback plan
- [ ] Dashboard + alert (có runbook) cho dịch vụ/tính năng mới
- [ ] Changelog, docs, NOTICE cập nhật
- [ ] Error budget không âm
- [ ] Người duyệt ≠ người tạo release
Kết quả: approve / hold / rollback

## Gate bất thường (supervisor escalate)
- Ticket retry ≥ 3, timeout, vượt budget, nghi injection, cùng lỗi lặp ≥ 2 lần
- Quyết định: retry với hướng dẫn / cắt phạm vi / hoãn / dừng / rollback prompt version

## Chỉ người được ký
- Chấp nhận rủi ro bảo mật (threat accepted)
- Ngoại lệ license (copyleft)
- Chuyển dữ liệu cá nhân ra nước ngoài
- Bật A/B test chạm PII
