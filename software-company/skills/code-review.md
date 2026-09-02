---
name: code-review
version: 2
standards: [Google Engineering Practices (Code Review Developer Guide), CWE Top 25, Conventional Comments, OWASP ASVS L2]
---
# Skill: code-review

## Tiêu chuẩn tham chiếu
- Google Engineering Practices: review để cải thiện sức khỏe codebase theo thời gian, không đòi hoàn hảo
- CWE Top 25 để nhận diện lỗi bảo mật phổ biến
- Conventional Comments: mỗi nhận xét có nhãn mức độ rõ ràng
- OWASP ASVS L2 làm sàn an toàn cho code chạm dữ liệu người dùng

## Quy trình (làm đúng thứ tự)
Đọc mô tả PR và requirement_id → xem contract và test trước khi xem code hiện thực → đọc theo thứ tự: đúng đắn → an toàn → dữ liệu/đồng thời → bảo trì → hiệu năng → tài liệu → chạy thử test và đọc phần diff không có test → viết finding có vị trí và mức → chốt kết luận block/pass.
Nếu PR quá lớn để hiểu (> ~400 dòng thay đổi thực chất), trả lại yêu cầu chia nhỏ trước khi review chi tiết.

## Quy tắc — phạm vi và thái độ
- Không tự sửa code trong PR của người khác; viết finding để tác giả sửa. Ngoại lệ duy nhất là khi được yêu cầu rõ ràng.
- Review diff, nhưng đọc đủ ngữ cảnh xung quanh để hiểu; không phán xét dựa trên một dòng tách rời.
- Không đòi hỏi ngoài phạm vi ticket; ý tưởng mở rộng ghi thành ticket riêng, không chặn PR.
- Nhận xét về code, không về người; nêu lý do và hệ quả, đề xuất hướng sửa cụ thể.
- Khen chỗ làm tốt khi có thật (một câu là đủ) — nó giúp chuẩn hóa mẫu tốt trong đội.

## Quy tắc — cách viết finding
- Mỗi finding có: mức, `file:line`, điều gì sai, hệ quả cụ thể, hướng sửa. Thiếu vị trí là finding không hợp lệ.
- Ba mức: `block` (sai đúng đắn, lỗ hổng an toàn, mất dữ liệu, vi phạm contract, thiếu test cho tiêu chí Must), `warn` (nợ kỹ thuật thật, sẽ đau về sau), `nit` (phong cách, không chặn merge).
- Không đưa ý kiến chủ quan lên mức block; nếu là sở thích thì gắn `nit` và nói rõ là sở thích.
- Kết luận PR: chỉ pass khi 0 block; mọi block phải nêu được kịch bản thất bại cụ thể (đầu vào nào → hậu quả gì).
- Tránh trùng lặp: cùng một lỗi lặp nhiều chỗ thì gộp một finding, liệt kê các vị trí.

## Quy tắc — trọng tâm cần soi
- Đúng đắn: điều kiện biên, off-by-one, null/rỗng, lỗi bị nuốt, đường lỗi không có test, giá trị trả về không kiểm.
- An toàn: đầu vào không validate, nối chuỗi truy vấn, thiếu kiểm quyền theo đối tượng, so sánh secret không hằng thời gian, secret trong code/log, phụ thuộc mới không rõ nguồn (xem `security`, `license-compliance`).
- Dữ liệu và đồng thời: giao dịch quá rộng, đọc-rồi-ghi không khóa, thao tác không idempotent, migration không tương thích ngược, mất thứ tự event.
- Bảo trì: trùng lặp logic nghiệp vụ, hàm làm nhiều việc, tên sai nghĩa, phụ thuộc ngược hướng kiến trúc, cấu hình hard-code.
- Hiệu năng: N+1, truy vấn không giới hạn, làm việc nặng trong vòng lặp hoặc trong request, cache không có cách vô hiệu.
- Test: có test cho tiêu chí Gherkin không, test có thể sai lệch (assert vô nghĩa, mock chính thứ đang test) không, có test cho ca lỗi không.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Kết luận rõ block/pass, và 0 block khi pass
- [ ] Mọi finding có `file:line`, mức, hệ quả và hướng sửa
- [ ] Mỗi block nêu được kịch bản thất bại cụ thể
- [ ] Đã đối chiếu PR với contract và requirement_id
- [ ] Đã kiểm đường lỗi và test cho ca lỗi, không chỉ happy path
- [ ] Đã soi bảo mật theo CWE Top 25 với phần code chạm dữ liệu người dùng
- [ ] Không sửa code hộ, không mở rộng phạm vi ticket
- [ ] PR quá lớn thì yêu cầu chia nhỏ thay vì review qua loa

## Ví dụ tốt
`[block] src/auth.py:42` — so sánh token bằng `==` nên lộ thông tin qua thời gian phản hồi; kẻ tấn công đoán được từng byte. Sửa: `hmac.compare_digest(a, b)`.
`[warn] src/orders/service.py:88` — truy vấn trong vòng lặp gây N+1 (100 đơn → 101 truy vấn); dùng `selectinload` hoặc gộp một truy vấn.
`[nit] src/orders/api.py:15` — tên `d` khó đọc, gợi ý `delivery_date` (sở thích, không chặn).

## Ví dụ xấu
"Code này hơi lạ." Không vị trí, không hệ quả, không hướng sửa; hoặc chặn PR vì "tôi thích cách viết khác"; hoặc tự commit sửa vào nhánh của người khác rồi báo đã xong.
