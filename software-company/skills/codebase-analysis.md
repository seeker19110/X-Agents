---
name: codebase-analysis
version: 2
standards: [C4 model, SBOM (SPDX/CycloneDX), Static analysis, Code archaeology, SPACE/DORA]
---
# Skill: codebase-analysis

## Tiêu chuẩn tham chiếu
- C4 model để mô tả cái đang có (không phải cái mong muốn)
- SBOM SPDX/CycloneDX cho phụ thuộc và license
- Phân tích tĩnh: call graph, dependency graph, coverage, độ phức tạp
- Code archaeology: lịch sử git (tần suất đổi, đồng biến đổi, chủ sở hữu thực tế)
- DORA/SPACE để nhìn chỗ nghẽn của việc thay đổi, không chỉ nhìn code

## Quy trình (làm đúng thứ tự)
Chạy được dự án và test trước đã (nếu không chạy được, đó là phát hiện số một) → dựng bản đồ phụ thuộc và điểm vào → xác định module chạm tới từng goal → đọc lịch sử git các file đó → đo (coverage, phức tạp, tần suất đổi) → viết impact map theo file path → nêu rủi ro và nợ kỹ thuật CHẶN yêu cầu → nêu điểm chưa chắc chắn.
Dùng công cụ quét trước, đọc tay sau và chỉ đọc phần trọng yếu; không đọc tuần tự toàn bộ repo.

## Quy tắc — bằng chứng
- Mọi khẳng định gắn với đường dẫn thật (`src/orders/service.py:120`) hoặc kết quả lệnh cụ thể; không suy đoán tên module chưa kiểm chứng.
- Không tồn tại thì nói không tồn tại. "Có lẽ có ở đâu đó" là câu bị cấm; thay bằng "đã tìm bằng X, không thấy".
- Phân biệt ba loại: sự thật đã kiểm, suy luận có căn cứ, và giả định cần xác nhận — ghi nhãn rõ từng loại.
- Trích số đo thật (coverage %, số truy vấn, thời gian build, số dòng, số phụ thuộc), không dùng tính từ.

## Quy tắc — nội dung phân tích
- Impact map: mỗi goal → danh sách file/module chạm tới, kiểu tác động (đọc/sửa/thêm), có cần migration DB không, có phá contract không, có ảnh hưởng consumer nào không.
- Điểm vào và ranh giới: API công khai, job nền, event tiêu thụ, tích hợp bên ngoài, cấu hình bắt buộc.
- Sức khỏe test: có chạy được không, mất bao lâu, phủ phần nào; vùng không có test là vùng rủi ro cao khi sửa.
- Lịch sử: file đổi thường xuyên cùng nhau (đồng biến đổi) là ranh giới module đang sai; file đổi nhiều và không có test là chỗ dễ vỡ nhất.
- Phụ thuộc: mỗi dep có phiên bản, license SPDX, còn được bảo trì không, có CVE không (chuyển `security`/`license-compliance` xử lý tiếp).
- Nợ kỹ thuật chỉ ghi khi nó CHẶN hoặc làm đắt lên yêu cầu hiện tại, kèm chi phí ước lượng nếu xử lý; nợ không liên quan để danh sách riêng, không nhét vào phạm vi.

## Quy tắc — bàn giao
- Đầu ra dùng được ngay cho `architecture` và `cost-estimation`: ai đọc cũng biết sửa ở đâu, rủi ro gì, tốn bao nhiêu.
- Kèm cách tái lập: lệnh đã chạy, phiên bản công cụ, commit hash đã phân tích. Phân tích không nêu commit là phân tích hết hạn.
- Không đề xuất viết lại toàn bộ trừ khi có số liệu chứng minh sửa dần đắt hơn; nếu đề xuất thì phải kèm đường đi từng bước.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Nêu commit hash và lệnh đã chạy để tái lập
- [ ] impact_map phủ mọi goal, theo file path có thật
- [ ] Mọi dependency có phiên bản và license SPDX
- [ ] Có số đo thật (coverage, thời gian build, số truy vấn...) thay cho tính từ
- [ ] Vùng không có test được chỉ ra rõ
- [ ] Nợ kỹ thuật ghi kèm lý do nó chặn yêu cầu hiện tại
- [ ] Không suy đoán về module không tồn tại; giả định được ghi nhãn riêng

## Ví dụ tốt
Commit `a91c45d`. GOAL-2 chạm `src/orders/service.py:88-140`, `src/orders/models.py`, cần migration thêm cột `coupon_code`; `service.py` đổi 23 lần/6 tháng, coverage nhánh 41%, không có test cho đường hoàn tiền → rủi ro cao, đề xuất viết test đặc tả trước khi sửa. Consumer bị ảnh hưởng: client mobile v2 (đọc field `total`).

## Ví dụ xấu
"Chắc chỗ nào đó trong module orders; code hơi cũ và rối, nên viết lại toàn bộ cho sạch."
