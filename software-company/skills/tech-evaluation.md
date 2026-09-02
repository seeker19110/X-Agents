---
name: tech-evaluation
version: 2
standards: [ADR (Nygard), TCO 24 tháng, OSS license compatibility, Trial/spike có tiêu chí, Sức khỏe dự án nguồn mở]
---
# Skill: tech-evaluation

## Tiêu chuẩn tham chiếu
- ADR theo Nygard: quyết định kèm bối cảnh, phương án bị loại, và hệ quả (xem `architecture`)
- TCO trên 24 tháng: giấy phép + hạ tầng + công tích hợp + công vận hành + chi phí rời bỏ
- Tương thích giấy phép theo `license-compliance`
- Spike có tiêu chí và timebox thay vì tranh luận suông
- Sức khỏe dự án nguồn mở: nhịp phát hành, số người bảo trì, thời gian xử lý lỗi, chính sách bảo mật

## Quy trình (làm đúng thứ tự)
Viết nhu cầu thật và tiêu chí bắt buộc (must-have) trước khi nhìn công cụ → liệt kê phương án gồm cả "dùng cái đã có" và "tự làm tối thiểu" → loại nhanh theo tiêu chí bắt buộc → chấm phương án còn lại theo bộ tiêu chí có trọng số → spike có timebox cho hai phương án đầu → quyết định và viết ADR → định nghĩa tín hiệu để xem lại quyết định.
Tiêu chí phải viết trước khi khảo sát công cụ; viết sau thì tiêu chí sẽ mô tả đúng công cụ mình đã thích.

## Quy tắc — phương án và tiêu chí
- Luôn có ít nhất hai phương án thực chất, cộng thêm hai phương án mặc định phải xét: dùng thứ đã có trong stack, và không làm gì (hoặc làm tối thiểu bằng tay).
- Ưu tiên thứ đã có trong stack nếu đáp ứng: mỗi công nghệ mới là chi phí học, vận hành, tuyển dụng và bảo mật kéo dài nhiều năm.
- Tiêu chí gồm tối thiểu: phù hợp chức năng, giấy phép, độ trưởng thành và sức khỏe dự án, hiệu năng ở quy mô của ta, độ khó vận hành, bảo mật và lịch sử CVE, chất lượng tài liệu, năng lực sẵn có của đội, chi phí, và mức khóa nhà cung cấp.
- Đánh giá ở quy mô và ràng buộc của mình, không theo bài viết chuẩn hóa của người khác; điểm chuẩn (benchmark) chỉ có nghĩa khi tái lập được với dữ liệu của ta.
- Khóa nhà cung cấp: nêu rõ chi phí rời bỏ và đường thoát trước khi cam kết; với thành phần lõi, ưu tiên chuẩn mở và interface trung lập.
- Không chọn theo độ phổ biến nhất thời; hỏi dự án còn được bảo trì bởi ai, và điều gì xảy ra nếu người đó dừng.

## Quy tắc — kiểm chứng
- Spike có timebox và tiêu chí thành công viết trước: thử đúng ca khó nhất của mình, không thử phần "hello world".
- Kết quả spike ghi lại số liệu thật (thời gian tích hợp, hiệu năng đo được, chỗ vướng), kể cả khi kết luận là loại.
- Với dịch vụ trả tiền: đọc điều khoản về SLA, giới hạn tốc độ, quyền sở hữu dữ liệu, và cách xuất dữ liệu ra.
- Với thành phần xử lý dữ liệu cá nhân: kiểm hợp đồng xử lý dữ liệu và nơi lưu trữ trước khi chọn (xem `privacy-compliance`).

## Quy tắc — quyết định và duy trì
- Quyết định viết thành ADR: khuyến nghị, lý do, phương án bị loại kèm lý do loại, hệ quả, và chi phí ước tính 24 tháng.
- Nêu điều kiện xem lại: chỉ số hoặc sự kiện nào xảy ra thì quyết định này cần đánh giá lại (ví dụ vượt quy mô X, dự án ngừng bảo trì).
- Ghi lại cả phần chưa chắc chắn; đánh giá trung thực hữu ích hơn đánh giá tự tin sai.
- Sau 3–6 tháng, đối chiếu thực tế với dự đoán và ghi vào `knowledge` — đây là cách bộ tiêu chí lần sau tốt hơn.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Tiêu chí bắt buộc viết trước khi khảo sát công cụ
- [ ] Có ≥ 2 phương án thực chất, cộng phương án "dùng cái đã có" và "làm tối thiểu"
- [ ] Giấy phép tương thích và đã được kiểm theo chính sách
- [ ] Có đánh giá độ trưởng thành, sức khỏe dự án và lịch sử bảo mật
- [ ] Có chi phí vận hành và TCO 24 tháng, gồm chi phí rời bỏ
- [ ] Spike có timebox, tiêu chí và số liệu thật
- [ ] ADR ghi khuyến nghị, phương án bị loại và hệ quả
- [ ] Có điều kiện xem lại quyết định

## Ví dụ tốt
Nhu cầu: xác thực tập trung, bắt buộc chạy tại chỗ (ràng buộc hợp đồng). Phương án: Keycloak (Apache-2.0, trưởng thành, tự host), Auth0 (SaaS, nhanh, tính theo người dùng hoạt động), tự làm tối thiểu bằng thư viện OIDC. Loại Auth0 vì không đáp ứng ràng buộc tại chỗ; loại tự làm vì chi phí vận hành và rủi ro bảo mật cao hơn giá trị. Chọn Keycloak; TCO 24 tháng ≈ 9.400 USD gồm 0.4 người-tháng vận hành; xem lại nếu vượt 50.000 người dùng hoặc nếu thời gian vá CVE của dự án vượt 60 ngày. ADR-0009.

## Ví dụ xấu
"Dùng thư viện X vì đang hot" — một phương án, không tiêu chí, không giấy phép, không chi phí vận hành; đánh giá dựa trên một bài viết so sánh của chính nhà cung cấp; sáu tháng sau dự án đó ngừng bảo trì và không có đường thoát.
