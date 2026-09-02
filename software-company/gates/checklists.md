# Human gate — checklist

Nguyên tắc: separation of duties, four-eyes cho production, timeout 24h (supervisor nhắc 12h), quá hạn KHÔNG tự đi tiếp.

## Gate 1 — Duyệt spec (sau khối nghiên cứu)
- [ ] Mọi yêu cầu truy vết được về nguồn
- [ ] NFR có số đo
- [ ] 100% Must có Gherkin
- [ ] Out-of-scope rõ
- [ ] Rủi ro High có mitigation và owner
- [ ] Câu hỏi mở chỉ còn assumption đã ghi nhận
Kết quả: approve / request_changes(lý do) / reject

## Gate 2 — Duyệt plan (sau delivery-lead planning)
- [ ] C4 L1–L2 và ADR có
- [ ] API contract tồn tại
- [ ] Ước lượng có cơ sở, ticket ≤ 1 ngày
- [ ] Phụ thuộc ngoài đã xác nhận
- [ ] Ngân sách token cho dự án được đặt
Kết quả: approve / request_changes / reject

## Gate 3 — Duyệt release production
- [ ] Mọi test và scan pass, SBOM có
- [ ] Runbook và rollback đã thử
- [ ] Changelog và docs cập nhật
- [ ] Error budget không âm
- [ ] Người duyệt ≠ người tạo release
Kết quả: approve / hold / rollback

## Gate bất thường (supervisor escalate)
- Ticket retry ≥ 3, timeout, vượt budget, nghi injection
- Quyết định: retry với hướng dẫn / cắt phạm vi / hoãn / dừng
