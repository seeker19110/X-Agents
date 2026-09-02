---
name: performance-testing
version: 2
standards: [ISO/IEC 25010 (performance efficiency), k6/Gatling/Locust, RED/USE, Google SRE SLO, Little's Law]
---
# Skill: performance-testing

## Tiêu chuẩn tham chiếu
- ISO/IEC 25010 — hiệu năng là thuộc tính chất lượng có tiêu chí đo được
- Công cụ tạo tải có kịch bản dạng code (k6, Gatling, Locust) và lưu được kết quả
- RED/USE để đọc kết quả: nhìn cả phía dịch vụ và phía tài nguyên
- Google SRE: ngưỡng pass gắn với SLO, đo ở phân vị cao chứ không đo trung bình
- Little's Law (concurrency = throughput × latency) để thiết kế kịch bản hợp lý

## Quy trình (làm đúng thứ tự)
Lấy NFR có số từ spec → dựng hồ sơ tải từ dữ liệu thật (nhịp truy cập, tỉ lệ theo endpoint, giờ cao điểm) → chuẩn bị môi trường và dữ liệu cỡ production → chạy thử nhỏ để hiệu chỉnh kịch bản → đo baseline → chạy load, stress, soak, spike → phân tích nút thắt bằng dữ liệu quan sát → sửa → đo lại → lưu baseline mới.
Chỉ tối ưu sau khi đã đo và biết nút thắt ở đâu; tối ưu theo cảm giác là lãng phí.

## Quy tắc — thiết kế phép đo
- Mọi NFR hiệu năng phải có: chỉ số (p95/p99 độ trễ, throughput, tỉ lệ lỗi), điều kiện (tải, cỡ dữ liệu), và ngưỡng — trước khi code.
- Báo cáo theo phân vị, không theo trung bình; nêu cả tỉ lệ lỗi và độ lệch, vì độ trễ đẹp mà lỗi 5% là kết quả vô nghĩa.
- Bốn kiểu chạy có mục đích khác nhau: load (đúng tải kỳ vọng), stress (tìm điểm gãy và cách gãy), soak (chạy dài tìm rò rỉ), spike (tăng đột ngột, kiểm khả năng hồi phục).
- Kịch bản phải giống hành vi thật: có think time, có phân bố dữ liệu thật (không cùng một id), có tỉ lệ đọc/ghi thật, có đăng nhập nếu luồng thật cần.
- Dữ liệu cỡ production: đo trên bảng 1.000 dòng rồi kết luận cho bảng 10 triệu dòng là sai từ gốc.
- Bộ tạo tải không được là nút thắt; kiểm tài nguyên máy chạy tải và đo từ nhiều điểm nếu cần.
- Khởi động nóng (warm-up) tách khỏi kết quả; nêu rõ trạng thái cache khi đo.

## Quy tắc — môi trường và tính so sánh được
- Chạy trên staging có cấu hình tương đương production; khác biệt nào còn lại phải ghi rõ và ước lượng ảnh hưởng.
- Mỗi lần đo ghi: phiên bản build, cấu hình, cỡ dữ liệu, thời điểm, và kịch bản dùng — để lần sau so sánh được.
- Baseline lưu trong `docs` và so với bản phát hành trước; hồi quy vượt ngưỡng đã thống nhất là finding block trên release candidate, không phải warn.
- Đo lặp lại đủ số lần để loại nhiễu; một lần chạy không kết luận được.
- Kết quả gắn với dữ liệu quan sát (trace, metric hệ thống) để chỉ ra nút thắt cụ thể: truy vấn nào, khóa nào, hàng đợi nào, GC hay mạng.

## Quy tắc — phía client
- Hiệu năng giao diện đo bằng Core Web Vitals ở p75 trên thiết bị và mạng thực tế; ngân sách bundle kiểm trong CI (xem `frontend`).
- Ứng dụng di động đo thời gian tới màn hình dùng được, mức tiêu thụ pin và dữ liệu cho tác vụ nền (xem `mobile`).

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Mọi endpoint/màn hình có NFR hiệu năng đều có kịch bản tải tương ứng
- [ ] p95/p99 và tỉ lệ lỗi đạt NFR trên staging với dữ liệu cỡ production
- [ ] Đã chạy đủ load, stress, spike; soak ≥ 1h không rò rỉ bộ nhớ hay kết nối
- [ ] Kịch bản có think time và dữ liệu phân tán như thực tế
- [ ] Bộ tạo tải không phải nút thắt; warm-up tách khỏi kết quả
- [ ] Baseline lưu trong `docs` kèm phiên bản, cấu hình, cỡ dữ liệu
- [ ] Hồi quy so với bản trước được kiểm và xử lý như finding block
- [ ] Nút thắt được chỉ ra bằng bằng chứng quan sát, không bằng phỏng đoán

## Ví dụ tốt
NFR-07: p95 < 300ms tại 200 RPS với 10 triệu đơn. Kịch bản `perf/orders_get.js` (k6), think time 1–3s, id ngẫu nhiên theo phân bố thật; kết quả p95 = 212ms, p99 = 480ms, lỗi 0.02%; soak 2h bộ nhớ phẳng; nút thắt trước đó là truy vấn thiếu index `(tenant_id, created_at)`, đã sửa và ghi baseline `docs/perf/2026-09-02.md`.

## Ví dụ xấu
"Chạy thử thấy nhanh" — không số, không tải, không cỡ dữ liệu; đo trên bảng rỗng với cùng một `order_id` nên mọi thứ nằm trong cache; báo cáo độ trễ trung bình 40ms trong khi p99 là 6 giây và 4% request lỗi.
