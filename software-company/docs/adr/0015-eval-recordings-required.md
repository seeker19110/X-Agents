# ADR-0015: Bản ghi eval bắt buộc cho agent

Trạng thái: Accepted · Ngày: 2026-09-02 · Bổ sung ADR-0010

## Bối cảnh
ADR-0010 đặt cổng "đổi prompt phải chạy eval". Trên CI, job eval-replay SKIP đủ 20 agent rồi exit 0: cổng
không cưỡng chế được gì. Một prompt đổi tuỳ ý vẫn merge được với CI xanh.

Gọi model thật trong CI thì tốn kém và không tất định, nên cổng phải kiểm được offline.

## Quyết định
CI chạy `evals all --replay --strict`. `evals/recordings/REQUIRED.txt` liệt kê agent bắt buộc có bản ghi tươi:
thiếu bản ghi là đỏ, và bản ghi tạo ở phiên bản prompt cũ hơn agent hiện tại cũng đỏ. Quy trình thêm tên
(`make eval-record AGENT=<id>` bằng model thật, commit bản ghi, thêm id vào danh sách) nằm ngay trong file.

## Hệ quả
- Từ lúc một agent có tên trong danh sách, mọi thay đổi prompt hoặc skill của agent ấy buộc phải chạy lại eval.
- Giới hạn hiện tại: **danh sách còn trống**, vì chưa bản ghi nào được tạo bằng model thật. Cơ chế đã có răng
  nhưng chưa cắn ai — đừng đọc CI xanh như bằng chứng eval đã pass.
- Bản ghi là artifact có phiên bản, không phải cache: xoá đi thì mất bằng chứng, không phải mất tốc độ.
