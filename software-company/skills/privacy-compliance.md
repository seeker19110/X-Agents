---
name: privacy-compliance
version: 1
standards: [GDPR, Nghị định 13/2023/NĐ-CP, ISO/IEC 27701, DPIA, Privacy by Design]
---
# Skill: privacy-compliance

## Tiêu chuẩn tham chiếu
- GDPR (Art. 5 nguyên tắc, Art. 25 privacy by design, Art. 35 DPIA)
- Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân (Việt Nam)
- ISO/IEC 27701
- Privacy by Design (7 nguyên tắc)

## Quy tắc
- Phân loại dữ liệu: công khai / nội bộ / cá nhân / cá nhân nhạy cảm; ghi trong schema và data contract.
- Mỗi trường PII có: cơ sở pháp lý, mục đích, retention, người có quyền truy cập.
- DPIA bắt buộc khi: xử lý dữ liệu nhạy cảm, theo dõi hành vi, chấm điểm tự động, trẻ em.
- Quyền chủ thể (truy cập, xóa, rút đồng ý) phải có API/quy trình trước khi thu thập.
- Chuyển dữ liệu ra nước ngoài: hồ sơ đánh giá theo NĐ13 trước khi bật.
- Log không chứa PII thô; mask ở biên.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] PII đã phân loại trong schema
- [ ] Retention khai báo và có job xóa
- [ ] DPIA có khi cần
- [ ] Quyền xóa/truy cập hoạt động
- [ ] Log không có PII

## Ví dụ tốt
Trường `phone`: cá nhân, mục đích OTP, retention 90 ngày sau đóng tài khoản, job xóa hàng đêm, mask trong log thành `+84***123`.

## Ví dụ xấu
Lưu số CCCD trong bảng `users` "để sau này cần".
