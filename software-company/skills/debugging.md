---
name: debugging
version: 2
standards: [Scientific debugging (Zeller), Delta debugging, Five whys, Observability-driven debugging]
---
# Skill: debugging

## Tiêu chuẩn tham chiếu
- Scientific debugging (Zeller): giả thuyết → dự đoán → thí nghiệm → quan sát → kết luận, ghi lại từng vòng
- Delta debugging: thu nhỏ đầu vào và thu nhỏ khoảng thay đổi (git bisect) để cô lập
- Five whys để đi từ triệu chứng tới nguyên nhân hệ thống, không dừng ở nguyên nhân gần nhất
- Debug bằng dữ liệu quan sát được (log, trace, metric) thay vì đoán (xem `observability`)

## Quy trình (làm đúng thứ tự)
Tái hiện ổn định → thu nhỏ ca tái hiện → xác định phạm vi (bisect theo commit, theo cấu hình, theo dữ liệu) → nêu giả thuyết kiểm được → thí nghiệm một biến mỗi lần → xác minh nguyên nhân gốc bằng cách bật/tắt được lỗi theo ý muốn → viết test đỏ tái hiện lỗi → đề xuất sửa → kiểm xem lỗi cùng loại còn ở đâu nữa.
Chưa tái hiện được thì chưa được sửa; sửa mù là đổi triệu chứng, không phải sửa lỗi.

## Quy tắc — điều tra
- Một biến mỗi thí nghiệm; ghi lại giả thuyết, thao tác, và kết quả kể cả khi sai — giả thuyết bị bác bỏ cũng là kết quả có giá trị.
- Đọc dữ liệu trước khi đọc code: log có trace_id, trace phân tán, metric quanh thời điểm lỗi, diff cấu hình và diff phiên bản.
- Xác nhận điều "chắc chắn đúng" (phiên bản đang chạy, cấu hình thực tế, dữ liệu thật) — phần lớn thời gian mất vì tin vào giả định chưa kiểm.
- Với lỗi không ổn định (đồng thời, thời gian, thứ tự): chạy lặp có công cụ, thêm áp lực (tải, độ trễ giả), hoặc dựng lại thứ tự bằng test; "không tái hiện được" chỉ được kết luận sau khi đã thử có phương pháp và ghi rõ đã thử gì.
- Nếu bằng chứng bị mất do thiếu quan sát, thì phát hiện đầu ra là "thiếu observability ở X" và đó là một finding thật.
- Timebox mỗi hướng điều tra; hết giờ thì đổi hướng và ghi lại, không đi mãi một ngõ cụt.

## Quy tắc — báo cáo
- Bug report có: môi trường và phiên bản, bước tái hiện tối thiểu, kết quả mong đợi, kết quả thực tế, tần suất, mức độ theo tác động nghiệp vụ, bằng chứng (log/trace/ảnh) và phạm vi ảnh hưởng (bao nhiêu người dùng, từ khi nào).
- Nêu nguyên nhân gốc bằng cơ chế cụ thể ("hai worker cùng đọc số dư trước khi ghi"), không bằng phỏng đoán ("chắc do cache").
- Đề xuất hướng sửa và, nếu có, cách giảm nhẹ tạm thời; nêu cả rủi ro của bản sửa.
- Không tự sửa code của người khác trong vai trò gỡ lỗi; giao lại cho chủ sở hữu kèm test đỏ.
- Ghi lỗi lặp lại và bài học vào `knowledge`; lỗi cùng loại xuất hiện lần thứ hai phải sinh chốt chặn (test, lint, hoặc kiểm trong CI), không chỉ sửa điểm.
- Lỗi trên production đi kèm quy trình `incident-management`; gỡ lỗi không thay thế việc khôi phục dịch vụ trước.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Có bước tái hiện tối thiểu và ổn định (hoặc ghi rõ đã thử gì nếu không tái hiện được)
- [ ] Có nguyên nhân gốc nêu bằng cơ chế, chứng minh được bằng cách bật/tắt lỗi
- [ ] Có test đỏ tái hiện lỗi trước khi sửa
- [ ] Nêu phạm vi ảnh hưởng và mức độ theo tác động nghiệp vụ
- [ ] Có đề xuất sửa và rủi ro của bản sửa
- [ ] Đã kiểm lỗi cùng loại ở chỗ khác trong codebase
- [ ] Bài học và chốt chặn được ghi vào `knowledge` nếu lỗi lặp

## Ví dụ tốt
Tái hiện: 2 request hoàn tiền song song cùng `order_id` → số dư trừ hai lần (10/10 lần). Bisect: xuất hiện từ `4b5a64b` khi bỏ `FOR UPDATE`. Nguyên nhân gốc: đọc-rồi-ghi không khóa ở mức cô lập read committed. Test đỏ `test_concurrent_refund_double_debit`. Đề xuất: khóa lạc quan bằng cột `version` (rẻ hơn `FOR UPDATE` ở đường nóng). Đã tìm thấy mẫu tương tự ở `wallet/topup.py:61`.

## Ví dụ xấu
"Đôi khi bị lỗi, chắc do mạng." Không phiên bản, không bước tái hiện, không bằng chứng; sửa bằng cách thêm `try/except` nuốt lỗi rồi đóng ticket.
