---
name: mobile
version: 2
standards: [Apple HIG, Material 3, OWASP MASVS, App Store / Google Play policies, Android & iOS privacy manifest]
---
# Skill: mobile

## Tiêu chuẩn tham chiếu
- Apple Human Interface Guidelines và Material 3 (chi tiết tương tác ở `ui-ux-design`)
- OWASP MASVS/MASTG (L1 mặc định; L2 cho ứng dụng tài chính, y tế)
- Chính sách App Store và Google Play: quyền riêng tư, thanh toán trong ứng dụng, nội dung, xóa tài khoản
- Khai báo quyền riêng tư của nền tảng (privacy manifest / data safety form)

## Quy trình (làm đúng thứ tự)
Đọc flow và token → dựng màn hình với trạng thái đầy đủ → nối dữ liệu qua contract → xử lý vòng đời và nền (background, bị kill, quay lại) → offline và đồng bộ → quyền và riêng tư → hiệu năng khởi động và pin → kiểm trên thiết bị thật (máy yếu, mạng 3G, cỡ chữ lớn) → chuẩn bị hồ sơ phát hành lên kho.
Kiểm trên máy ảo đời mới không thay được kiểm trên thiết bị thật đời cũ.

## Quy tắc — dữ liệu và an toàn
- Token và secret trong Keychain (iOS) / Keystore (Android); không trong `UserDefaults`, `SharedPreferences`, file thường, hay log.
- Không nhúng khóa API riêng tư trong ứng dụng: mọi thứ trong gói cài đặt đều đọc được. Phân quyền và giới hạn nằm ở máy chủ.
- Kênh mạng TLS; ghim chứng chỉ nếu mô hình đe dọa yêu cầu, kèm kế hoạch xoay vòng để không tự khóa mình ra ngoài.
- Dữ liệu nhạy cảm không lưu ở cache dùng chung, không hiện trong ảnh chụp màn hình chuyển tác vụ, không sao chép ngầm vào clipboard.
- Deep link và intent là đầu vào không tin cậy: xác thực nguồn, không thực hiện hành động có hệ quả chỉ vì mở một liên kết.
- Ứng dụng phải hoạt động đúng khi thiết bị đã root/jailbreak bị từ chối (nếu chính sách yêu cầu), nhưng không dựa vào phát hiện đó như biện pháp bảo mật duy nhất.

## Quy tắc — quyền và riêng tư
- Xin quyền tối thiểu, đúng lúc người dùng thấy được lợi ích, kèm giải thích ngắn trước hộp thoại hệ thống; từ chối quyền vẫn phải dùng được phần còn lại.
- Khai báo dữ liệu thu thập đúng và đầy đủ trong hồ sơ nền tảng; sai lệch giữa khai báo và hành vi thật là rủi ro bị gỡ ứng dụng.
- SDK bên thứ ba là nguồn thu thập dữ liệu ẩn: kiểm SDK thu gì, gửi đi đâu, và khai báo (xem `privacy-compliance`, `license-compliance`).
- Có đường xóa tài khoản và dữ liệu ngay trong ứng dụng nếu kho ứng dụng yêu cầu.
- Định danh quảng cáo chỉ dùng khi có cơ sở hợp pháp và có đồng ý; không dựng định danh thay thế bằng dấu vân tay thiết bị.

## Quy tắc — trải nghiệm và độ tin cậy
- Offline-first cho luồng chính khi hợp lý: xếp hàng thao tác, đồng bộ khi có mạng, giải quyết xung đột theo quy tắc khai báo trước (ai thắng, hay hỏi người dùng) — không im lặng ghi đè.
- Thao tác mạng đều idempotent phía máy chủ để retry an toàn; hiển thị trạng thái đồng bộ để người dùng biết dữ liệu đã lên hay chưa.
- Tôn trọng vòng đời: khôi phục trạng thái sau khi bị hệ điều hành kết thúc; tác vụ nền dùng API chính thức, không giữ thức máy vô cớ.
- Hiệu năng: thời gian tới màn hình dùng được có ngân sách, danh sách dài dùng tái sử dụng ô, ảnh giải mã ngoài luồng chính; đo mức tiêu thụ pin và dữ liệu cho tác vụ nền.
- Kích thước gói cài đặt có ngân sách; tài nguyên lớn tải sau theo nhu cầu.
- Tương thích ngược: ứng dụng cũ vẫn phải chạy được sau khi máy chủ đổi (xem `api-contract`); có cơ chế buộc nâng cấp cho trường hợp bắt buộc, kèm thông báo rõ.
- Crash-free session ≥ 99.5%; theo dõi crash và ANR theo phiên bản, có ngưỡng chặn phát hành (xem `release`).

## Checklist (supervisor và human gate dùng để chấm)
- [ ] MASVS L1 pass (L2 nếu ứng dụng tài chính/y tế)
- [ ] Token trong Keychain/Keystore; không secret trong gói cài đặt
- [ ] Quyền tối thiểu, xin đúng lúc, có giải thích; từ chối quyền vẫn dùng được
- [ ] Khai báo dữ liệu trên kho ứng dụng khớp hành vi thật, gồm cả SDK bên thứ ba
- [ ] Offline và đồng bộ có quy tắc xung đột rõ; thao tác retry an toàn
- [ ] Khôi phục trạng thái đúng sau khi bị kết thúc; deep link được xác thực
- [ ] Crash-free ≥ 99.5%; ANR trong ngưỡng; theo dõi theo phiên bản
- [ ] Đã kiểm trên thiết bị thật đời thấp, mạng chậm, cỡ chữ hệ thống lớn nhất
- [ ] Tuân chính sách kho ứng dụng, gồm đường xóa tài khoản

## Ví dụ tốt
Xin quyền camera ngay khi người dùng bấm "Chụp ảnh hóa đơn", có màn hình giải thích trước; từ chối thì vẫn tải ảnh từ thư viện được. Token trong Keystore; thao tác tạo đơn xếp hàng khi offline, gửi lại với `Idempotency-Key` khi có mạng, xung đột giải quyết theo "máy chủ thắng, báo người dùng". Crash-free 99.7% trên bản 2.4.0, đo trên Android 9 máy 2GB RAM.

## Ví dụ xấu
Xin toàn bộ quyền ngay khi mở ứng dụng; lưu access token trong `SharedPreferences`; nhúng khóa API bên thứ ba trong gói cài; đồng bộ offline ghi đè im lặng làm mất bản ghi người dùng nhập; chỉ kiểm trên máy ảo đời mới.
