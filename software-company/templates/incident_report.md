# INC-<incident_id> — <summary> (SEV<n>)
Dùng khi phát hiện sự cố trên môi trường thật; người trực (on-call) mở ngay và cập nhật liên tục cho tới khi đóng.

- incident_id: INC-xx · severity: SEV1|SEV2|SEV3|SEV4
- release_id: REL-xx · ticket_id: TCK-xx
- root_cause_class: requirement|design|code|ops|external
- Trạng thái: đang xử lý | đã kiểm soát | đã đóng
- Người chỉ huy sự cố: · Người ghi chép:

## Phân loại mức nghiêm trọng
| Mức | Ảnh hưởng người dùng | Ảnh hưởng dữ liệu | Phản hồi mục tiêu | Thông báo mục tiêu |
|---|---|---|---|---|
| SEV1 | Dịch vụ chính ngừng hoặc toàn bộ người dùng không dùng được | Mất/lộ dữ liệu, sai dữ liệu không tự phục hồi | ≤ 15 phút | Khách + lãnh đạo ≤ 30 phút, cập nhật mỗi 30 phút |
| SEV2 | Chức năng quan trọng hỏng hoặc một phần lớn người dùng bị ảnh hưởng, có cách đi vòng | Dữ liệu sai nhưng phục hồi được | ≤ 30 phút | Khách ≤ 2 giờ, cập nhật mỗi 2 giờ |
| SEV3 | Chức năng phụ hỏng, ít người dùng bị ảnh hưởng | Không ảnh hưởng dữ liệu | ≤ 4 giờ (giờ làm việc) | Ghi nhận nội bộ, báo khách trong ngày |
| SEV4 | Lỗi nhỏ, không cản trở sử dụng | Không | ≤ 2 ngày làm việc | Đưa vào release notes |

## Ảnh hưởng
- Người dùng/khách bị ảnh hưởng: <số lượng, nhóm>
- Chức năng bị ảnh hưởng:
- Thời gian gián đoạn: từ <…> đến <…> (tổng <n> phút)
- Dữ liệu: <mất/sai/lộ hay không>

## Dòng thời gian (UTC)
| Thời điểm | Sự việc | Ai |
|---|---|---|
| | Bắt đầu ảnh hưởng | |
| | Phát hiện (alert/khách báo) | |
| | Bắt đầu xử lý | |
| | Kiểm soát được | |
| | Khôi phục hoàn toàn | |

## Biện pháp tạm (mitigation)
- Đã làm: <rollback, tắt flag, chặn traffic, scale>
- Rủi ro còn lại:

## Nguyên nhân gốc
- Nguyên nhân trực tiếp:
- Nguyên nhân sâu xa (root_cause_class = <…>):
- Vì sao không phát hiện sớm hơn:

## Liên kết
- Postmortem: <link `templates/postmortem.md`, bắt buộc với SEV1/SEV2, hoàn thành trong 48h>
- Runbook: · Bug report: BUG-xx · PR khắc phục:

## Checklist đóng sự cố
- [ ] Dịch vụ đã khôi phục và xác minh
- [ ] Khách đã được thông báo theo mức severity
- [ ] Đã tạo ticket cho biện pháp lâu dài
- [ ] Postmortem đã lên lịch/hoàn thành (SEV1/SEV2)
