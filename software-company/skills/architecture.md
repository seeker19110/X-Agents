---
name: architecture
version: 2
standards: [C4 model, arc42, Clean/Hexagonal, DDD, ADR (Nygard), ISO/IEC 25010, Fitness functions]
---
# Skill: architecture

## Tiêu chuẩn tham chiếu
- C4 model (Context → Container → Component → Code)
- arc42 (khung tài liệu kiến trúc)
- Clean / Hexagonal (ports & adapters): nghiệp vụ không phụ thuộc hạ tầng
- DDD: bounded context, ubiquitous language, context map
- ADR theo Nygard: bối cảnh, quyết định, hệ quả, phương án bị loại
- ISO/IEC 25010 cho thuộc tính chất lượng; fitness function để giữ kiến trúc không trôi

## Quy trình (làm đúng thứ tự)
Đọc yêu cầu và NFR đã có số đo → xác định bounded context và ngôn ngữ chung → vẽ C4 L1 (context) và L2 (container) → chọn kiểu tích hợp giữa container (đồng bộ hay event) → viết ADR cho mọi quyết định không hiển nhiên → chốt contract (`api-contract`) → định nghĩa fitness function và ngưỡng → chỉ khi đó mới sinh ticket đầu tiên.
Không vẽ C4 L3/L4 trước khi code — mức đó sinh từ code, không vẽ tay.

## Quy tắc — ranh giới và phụ thuộc
- Ranh giới module theo bounded context nghiệp vụ, không theo lớp kỹ thuật; một context có một chủ sở hữu dữ liệu, các context khác đọc qua contract chứ không đọc thẳng bảng.
- Phụ thuộc chỉ hướng vào trong: domain không import framework, DB, HTTP client; hạ tầng cắm vào qua port. Kiểm bằng test phụ thuộc (import-linter, ArchUnit hoặc tương đương).
- Không vòng phụ thuộc giữa module; phát hiện vòng là finding block.
- Chia nhỏ dịch vụ chỉ khi có lý do rõ (nhịp triển khai, quy mô, ranh giới nhóm, cách ly rủi ro); mặc định là modular monolith. Mỗi lần tách phải trả lời được: dữ liệu chia thế nào, giao dịch xử lý ra sao, ai gọi ai khi lỗi.

## Quy tắc — thuộc tính chất lượng và đánh đổi
- Mỗi NFR quan trọng (hiệu năng, sẵn sàng, bảo mật, chi phí, khả năng thay đổi) phải chỉ ra được nó được thỏa mãn bằng cấu trúc nào; NFR không gắn được vào cấu trúc là NFR chưa đủ rõ, trả về `requirements-engineering`.
- Kiến trúc phải nêu đánh đổi bằng chữ: được gì, mất gì, ngưỡng nào thì quyết định này sai. Không có "tốt nhất", chỉ có "phù hợp trong bối cảnh này".
- Mỗi điểm lỗi đơn (single point of failure) hoặc phụ thuộc bên ngoài phải có cách xử lý khi hỏng: timeout, retry có backoff, circuit breaker, suy giảm chức năng có kiểm soát.
- Tính đúng đắn trước tính nhanh: đặt ranh giới giao dịch rõ ràng, nêu chỗ nào chấp nhận nhất quán cuối (eventual consistency) và hệ quả người dùng nhìn thấy.
- Chọn kỹ thuật theo `tech-evaluation`; ưu tiên thứ đã có trong stack nếu đáp ứng; mọi thứ mới đều là chi phí vận hành lâu dài.

## Quy tắc — ADR và bảo trì kiến trúc
- ADR cho mọi quyết định không hiển nhiên: chọn CSDL, kiểu tích hợp, cách xác thực, chia dịch vụ, chấp nhận nợ kỹ thuật, chấp nhận rủi ro. Nêu tối thiểu hai phương án bị loại và lý do.
- ADR bất biến: thay đổi quan điểm thì viết ADR mới trạng thái `supersedes`, không sửa ADR cũ.
- Fitness function chạy trong CI: kiểm hướng phụ thuộc, kích thước bundle hoặc thời gian khởi động, ngân sách hiệu năng, số truy vấn cho luồng chính.
- Sơ đồ C4 sống trong repo dạng text (Mermaid/Structurizr), cập nhật cùng PR làm nó lệch; sơ đồ ảnh dán tay không được chấp nhận.
- Kiến trúc là đầu vào của `threat-modeling` và `cost-estimation`; đổi kiến trúc thì cập nhật cả hai.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] C4 L1–L2 dạng text có trong repo trước ticket đầu tiên
- [ ] Bounded context và chủ sở hữu dữ liệu rõ; không context nào đọc thẳng dữ liệu của context khác
- [ ] Mọi quyết định không hiển nhiên có ADR với phương án bị loại và hệ quả
- [ ] Mỗi NFR quan trọng ánh xạ được vào một quyết định kiến trúc
- [ ] Mỗi phụ thuộc ngoài có timeout, retry, và hành vi khi hỏng
- [ ] Fitness function (hướng phụ thuộc, ngân sách hiệu năng) chạy trong CI
- [ ] Contract-first: contract chốt trước khi sinh ticket hiện thực
- [ ] Threat model và ước lượng chi phí cập nhật theo kiến trúc

## Ví dụ tốt
ADR-0007: chọn PostgreSQL thay MongoDB vì cần giao dịch đa bảng cho đặt hàng và hoàn tiền; loại MongoDB (yếu ACID đa document ở phiên bản đang dùng) và loại kiến trúc hai CSDL (chi phí vận hành gấp đôi, chưa đủ tải để bù). Hệ quả: đọc báo cáo nặng phải làm replica, ghi trong ADR-0011. Fitness function: `import-linter` chặn `domain` import `sqlalchemy`.

## Ví dụ xấu
"Dùng Postgres." Không bối cảnh, không phương án loại, không hệ quả; sơ đồ kiến trúc là ảnh PNG vẽ từ 6 tháng trước; domain import trực tiếp ORM nên không test được nếu không có DB.
