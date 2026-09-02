---
name: code-ownership
version: 1
standards: [GitHub/GitLab CODEOWNERS, SOC 2 CC8.1 (separation of duties), SOX change control, Google readability/OWNERS, Team Topologies]
---
# Skill: code-ownership

## Tiêu chuẩn tham chiếu
- CODEOWNERS (GitHub/GitLab) làm nguồn sự thật máy đọc được về ai duyệt vùng nào
- SOC 2 CC8.1 và SOX: separation of duties — người viết không tự duyệt và tự phát hành thay đổi của mình
- Mô hình OWNERS của Google: quyền duyệt gắn với thư mục, thừa kế xuống cây
- Team Topologies: quyền sở hữu gắn với đội có bối cảnh, không gắn với cá nhân anh hùng
- Bus factor (truck factor) làm chỉ số rủi ro tri thức

## Quy trình (làm đúng thứ tự)
Chia kho theo vùng trách nhiệm rõ ràng → gán mỗi vùng cho một đội (không phải một người) trong CODEOWNERS → phân loại vùng theo mức rủi ro → đặt số người duyệt tối thiểu và branch protection theo mức đó → đo bus factor mỗi quý → khi bus factor = 1 thì lên kế hoạch chia sẻ tri thức → khi người sở hữu rời đi thì chạy quy trình bàn giao trước ngày cuối.
CODEOWNERS phải là quy tắc được máy cưỡng chế, không phải bảng phân công trong tài liệu.

## Quy tắc — CODEOWNERS và phạm vi
- Mỗi đường dẫn trong kho khớp ít nhất một quy tắc; có quy tắc `*` bắt tất cả để không tồn tại vùng vô chủ.
- Chủ sở hữu là đội (`@org/team-payments`), không phải cá nhân; cá nhân chỉ xuất hiện tạm thời và có hạn ghi trong bình luận.
- Vùng rủi ro cao khai báo tường minh, không dựa vào thừa kế: xác thực/phân quyền, thanh toán, migration cơ sở dữ liệu, IaC và pipeline, mã hóa và bí mật, mã liên quan dữ liệu cá nhân.
- CODEOWNERS được cưỡng chế bằng branch protection "require review from Code Owners"; tắt cưỡng chế cần phê duyệt của người có thẩm quyền và ghi lý do.
- Sửa chính file CODEOWNERS cần duyệt bởi chủ sở hữu kho, không tự thêm mình vào vùng khác.

## Quy tắc — luồng duyệt theo mức rủi ro
- Rủi ro thấp (tài liệu, test, thay đổi nội bộ không đổi hành vi): 1 người duyệt, có thể là bất kỳ ai trong đội.
- Rủi ro trung bình (logic nghiệp vụ thường, thay đổi API tương thích ngược): 1 người duyệt là code owner của vùng.
- Rủi ro cao (xác thực, phân quyền, tiền, migration, IaC, thay đổi phá vỡ contract): 2 người duyệt, trong đó ≥ 1 là code owner, và ≥ 1 ngoài nhóm trực tiếp làm việc đó.
- Separation of duties: tác giả không tự duyệt, không tự gộp vào nhánh bảo vệ, và không tự phê duyệt phát hành thay đổi của mình lên production.
- Ngoại lệ khẩn cấp (break-glass) cho phép gộp với 1 người duyệt bất kỳ trong sự cố SEV1/SEV2, nhưng phải review hậu kiểm trong 24 giờ và ghi vào postmortem (xem `incident-management`).
- Duyệt là trách nhiệm thật: người duyệt chịu trách nhiệm ngang tác giả về chất lượng vùng mình sở hữu (xem `code-review`).
- SLA phản hồi review: rủi ro thấp/trung bình trong 1 ngày làm việc, rủi ro cao trong 2 ngày; quá hạn thì leo thang cho supervisor, không tự bỏ qua cổng duyệt.

## Quy tắc — bus factor và bàn giao
- Đo bus factor mỗi quý theo tỉ lệ đóng góp và số người duyệt được từng vùng; bus factor = 1 ở vùng rủi ro cao là rủi ro phải có ticket khắc phục.
- Mỗi vùng rủi ro cao có ít nhất 2 người duyệt được và 1 người đang được đào tạo; luân phiên review để nuôi người thứ hai.
- Người sở hữu rời dự án: trước ngày cuối phải có ADR/ghi chú kiến trúc cập nhật, buổi truyền đạt được ghi lại, danh sách nợ kỹ thuật đang biết, và CODEOWNERS đã đổi sang người kế nhiệm.
- Không rút tên khỏi CODEOWNERS trước khi người kế nhiệm đã duyệt được ít nhất 3 PR thật trong vùng đó.
- Tri thức chỉ nằm trong đầu một người được ghi lại thành tài liệu hoặc test; "hỏi anh A" không phải là tài liệu (xem `handover`, `technical-writing`).

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Mọi đường dẫn có chủ sở hữu; có quy tắc bắt tất cả
- [ ] Chủ sở hữu là đội, không phải cá nhân
- [ ] Vùng rủi ro cao khai báo tường minh trong CODEOWNERS
- [ ] Branch protection cưỡng chế duyệt bởi code owner
- [ ] Số người duyệt tối thiểu đúng mức rủi ro (1 / 1 owner / 2 gồm 1 owner)
- [ ] Tác giả không tự duyệt và không tự phát hành thay đổi của mình
- [ ] Break-glass có hậu kiểm trong 24h và ghi hồ sơ
- [ ] Bus factor đo mỗi quý; vùng rủi ro cao có ≥ 2 người duyệt được
- [ ] Có kế hoạch bàn giao trước khi người sở hữu rời đi

## Ví dụ tốt
`CODEOWNERS`: `* @org/platform`, `/payments/ @org/team-payments`, `/infra/ @org/sre`, `/auth/ @org/security @org/team-identity`. PR đổi logic hoàn tiền cần 2 duyệt gồm 1 người của team-payments và 1 người của security. Quý III đo bus factor: vùng `/billing/` chỉ có 1 người duyệt được → ticket ENG-812 luân phiên review, sau 6 tuần có người thứ hai. Chị B rời dự án ngày 30/09; ADR-0014 cập nhật, hai buổi truyền đạt ghi hình, người kế nhiệm đã duyệt 5 PR trước khi rút tên.

## Ví dụ xấu
CODEOWNERS chỉ có một dòng `* @anh-a`; anh A duyệt PR của chính mình bằng tài khoản thứ hai; thư mục `/infra/` không ai sở hữu nên PR nào cũng gộp bằng quyền admin; "khẩn cấp" được dùng 14 lần trong một tháng và không lần nào có hậu kiểm; anh A nghỉ việc, không ai biết cụm Kafka được cấu hình ra sao.
