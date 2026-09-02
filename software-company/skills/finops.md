---
name: finops
version: 2
standards: [FinOps Foundation Framework, Unit economics, Showback/chargeback, FOCUS cost data spec]
---
# Skill: finops

## Tiêu chuẩn tham chiếu
- FinOps Foundation: ba giai đoạn Inform → Optimize → Operate
- Unit economics: chi phí trên mỗi ticket, mỗi tính năng, mỗi khách, mỗi 1000 request
- Showback/chargeback: gán chi phí về đúng đội và đúng tính năng
- FOCUS (định dạng dữ liệu chi phí chuẩn) để so sánh giữa nhà cung cấp

## Quy trình (làm đúng thứ tự)
Gắn nhãn chi phí (tag/label) trước khi tạo tài nguyên → thu thập chi phí về một chỗ → phân bổ theo dự án/tính năng/agent → đặt ngân sách và cảnh báo → tối ưu theo thứ tự "bỏ cái không dùng → giảm cỡ → đổi mô hình giá" → theo dõi chi phí đơn vị theo thời gian → báo cáo mỗi sprint.
Không tối ưu khi chưa đo được; con số trước, hành động sau.

## Quy tắc — nhìn thấy chi phí
- Không tài nguyên nào được tạo mà thiếu nhãn bắt buộc: project, env, owner, cost-center (bắt buộc trong IaC, xem `iac-platform`); tài nguyên không nhãn bị coi là rác và phải có chủ trong 7 ngày.
- Chi phí chia được theo dự án, tính năng, agent và môi trường; phần không phân bổ được phải dưới ngưỡng đã thống nhất và phải giảm dần.
- Chi phí LLM/API theo lời gọi (token vào/ra, model, agent, ticket) được ghi như một dòng chi phí thật, không gộp vào "hạ tầng chung" (xem `ai-feature-engineering`).
- Chỉ số chính là chi phí đơn vị, không phải tổng chi phí: tổng tăng vì làm nhiều hơn là chuyện bình thường, chi phí đơn vị tăng mới là vấn đề.

## Quy tắc — ngân sách và kiểm soát
- Mỗi ticket, mỗi tính năng, mỗi dự án có ngân sách; cảnh báo ở 80%, chặn ở 100% (`cost-estimation` đặt con số, FinOps giám sát).
- Vượt ngân sách không được xử lý bằng cách nâng ngân sách âm thầm: phải có người duyệt và ghi lý do.
- Môi trường không phải production tự tắt ngoài giờ; tài nguyên tạm có hạn sống (TTL) và bị dọn tự động.
- Cảnh báo chi phí bất thường theo biến động ngày, không chỉ theo hạn mức tháng — hóa đơn tăng gấp ba chỉ được biết vào cuối tháng là quá muộn.
- Cam kết dài hạn (reserved/savings plan) chỉ mua khi tải đã ổn định và có số liệu chứng minh.

## Quy tắc — tối ưu có kỷ luật
- Thứ tự tối ưu: xóa thứ không ai dùng → giảm cỡ theo mức sử dụng thực → sửa mẫu truy cập tốn kém (truy vấn quét toàn bảng, gọi LLM thừa, ảnh không nén) → mới bàn tới đổi mô hình giá.
- Mỗi đề xuất tối ưu ghi rõ: tiết kiệm ước tính mỗi tháng, rủi ro, công bỏ ra; không làm việc tiết kiệm 5 USD mà tốn 2 ngày công.
- Không đánh đổi ngầm với SLO: tối ưu làm giảm độ tin cậy phải được nêu rõ và có người quyết (xem `observability`).
- Ghi kết quả sau tối ưu (trước/sau) vào `knowledge`; đề xuất không đo được kết quả thì coi như chưa làm.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Mọi tài nguyên có đủ nhãn bắt buộc; phần chi phí không phân bổ được dưới ngưỡng
- [ ] Mỗi dự án/tính năng có ngân sách, cảnh báo 80%, chặn 100%
- [ ] Chi phí LLM/API được ghi riêng theo agent và ticket
- [ ] Có cảnh báo chi phí bất thường theo ngày
- [ ] Môi trường phi production có lịch tắt hoặc TTL
- [ ] Báo cáo sprint có chi phí đơn vị và xu hướng, không chỉ tổng
- [ ] Mỗi đề xuất tối ưu có tiết kiệm ước tính, rủi ro và công bỏ ra
- [ ] Tối ưu ảnh hưởng SLO đều được nêu và có người quyết

## Ví dụ tốt
TCK-42 dùng 92% ngân sách token → cảnh báo tự động tới delivery-lead kèm liên kết audit. Báo cáo sprint: chi phí mỗi ticket giảm từ 0.42 xuống 0.31 USD nhờ bật cache prompt (đo trước/sau); môi trường stage tắt 20h–7h, tiết kiệm 180 USD/tháng, không ảnh hưởng SLO vì stage không có SLO.

## Ví dụ xấu
Không biết tốn bao nhiêu cho tính năng nào; phát hiện hóa đơn tăng gấp ba vào ngày chốt sổ; xử lý bằng cách nâng hạn mức cho hết cảnh báo; cụm test dựng từ tháng trước vẫn chạy mà không ai nhận là của mình.
