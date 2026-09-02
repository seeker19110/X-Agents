---
name: disaster-recovery
version: 1
standards: [ISO 22301 (BCMS), NIST SP 800-34, quy tắc sao lưu 3-2-1-1-0, AWS Well-Architected Reliability Pillar, ISO/IEC 27031]
---
# Skill: disaster-recovery

## Tiêu chuẩn tham chiếu
- ISO 22301: hệ thống quản lý liên tục kinh doanh (BCMS), phân tích tác động kinh doanh (BIA)
- NIST SP 800-34: lập kế hoạch dự phòng cho hệ thống thông tin
- Quy tắc 3-2-1 mở rộng 3-2-1-1-0: 3 bản sao, 2 loại phương tiện, 1 bản ngoài site, 1 bản bất biến/ngoại tuyến, 0 lỗi khi kiểm tra khôi phục
- AWS Well-Architected — Reliability: các chiến lược backup/restore, pilot light, warm standby, multi-site active/active
- ISO/IEC 27031 cho sẵn sàng CNTT phục vụ liên tục kinh doanh

## Quy trình (làm đúng thứ tự)
Phân tích tác động kinh doanh và xếp tầng dịch vụ → đặt RTO/RPO cho từng tầng, có người ký → chọn chiến lược DR đủ đáp ứng RTO/RPO đó → hiện thực sao lưu theo 3-2-1-1-0 và hạ tầng dự phòng bằng IaC → viết runbook khôi phục theo bước kiểm chứng được → diễn tập khôi phục định kỳ và lưu bằng chứng → đo RTO/RPO thực đạt và so với cam kết → sửa khoảng cách rồi diễn tập lại.
Sao lưu chưa từng khôi phục thành công thì coi như không có sao lưu.

## Quy tắc — RTO/RPO theo tầng dịch vụ
- Tầng 1 (dịch vụ doanh thu, mất là dừng kinh doanh): RTO ≤ 1 giờ, RPO ≤ 5 phút; cần multi-AZ và khả năng chuyển vùng.
- Tầng 2 (nghiệp vụ quan trọng, có đường vòng thủ công): RTO ≤ 8 giờ, RPO ≤ 1 giờ; warm standby hoặc pilot light.
- Tầng 3 (nội bộ, báo cáo, công cụ): RTO ≤ 72 giờ, RPO ≤ 24 giờ; backup/restore là đủ.
- RTO/RPO là cam kết có chi phí: mỗi nấc chặt hơn phải đi kèm ngân sách và được khách hoặc lãnh đạo ký (xem `cost-estimation`, `customer-acceptance`).
- Số cam kết với khách trong hợp đồng không được chặt hơn con số đã diễn tập chứng minh được.
- Tầng của một dịch vụ được xem lại mỗi năm hoặc khi mô hình kinh doanh đổi.

## Quy tắc — sao lưu
- 3 bản sao trên ≥ 2 loại phương tiện/nhà cung cấp, ≥ 1 bản ở vùng địa lý khác, ≥ 1 bản bất biến (WORM/object lock) chống ransomware và chống xóa nhầm.
- Sao lưu được mã hóa khi lưu và khi truyền; khóa quản lý tách khỏi hệ thống được sao lưu (xem `secrets-management`), và bản thân khóa cũng có kế hoạch khôi phục.
- Thời gian lưu trữ khai báo theo yêu cầu pháp lý và hợp đồng, không giữ vô hạn (xem `privacy-compliance`).
- Kiểm tra tự động tính toàn vẹn (checksum) mỗi bản sao và cảnh báo khi job sao lưu thất bại hoặc không chạy; im lặng không phải là thành công.
- Sao lưu bao gồm cả cấu hình, IaC, secret store, định nghĩa pipeline và dữ liệu quan sát cần cho điều tra — không chỉ cơ sở dữ liệu.
- Tài khoản chạy sao lưu không có quyền xóa bản sao; quyền xóa tách riêng và cần hai người.

## Quy tắc — diễn tập và khôi phục đa vùng
- Diễn tập khôi phục thật: tầng 1 mỗi quý, tầng 2 mỗi 6 tháng, tầng 3 mỗi năm; ít nhất một lần mỗi năm là diễn tập chuyển vùng đầy đủ.
- Bằng chứng lưu lại cho kiểm toán: ngày giờ bắt đầu/kết thúc, người thực hiện, RTO và RPO thực đo được, dữ liệu đã đối chiếu, sự cố gặp phải và ticket khắc phục.
- Khôi phục vào môi trường sạch, cách ly, từ đúng runbook — không dùng máy đã có sẵn dữ liệu, vì như vậy không chứng minh được gì.
- Đối chiếu sau khôi phục theo số liệu nghiệp vụ (số bản ghi, tổng tiền, mốc thời gian cuối), không chỉ "dịch vụ khởi động được".
- Hạ tầng dự phòng dựng lại được từ IaC trong ≤ RTO; cấu hình chỉnh tay không tồn tại trong kế hoạch DR (xem `iac-platform`).
- Kế hoạch nêu rõ ai tuyên bố thảm họa, ai kích hoạt chuyển vùng, cách liên lạc khi kênh chính hỏng, và điều kiện quay lại vùng chính (failback).
- Phụ thuộc bên thứ ba nằm trong kế hoạch: nhà cung cấp hỏng thì có phương án gì, và RTO của họ có phù hợp với ta không.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] BIA hoàn thành; mỗi dịch vụ có tầng và RTO/RPO có người ký
- [ ] Chiến lược DR tương xứng với RTO/RPO đã cam kết
- [ ] Sao lưu đạt 3-2-1-1-0, có bản bất biến ngoài vùng
- [ ] Sao lưu mã hóa; khóa tách khỏi hệ thống được sao lưu
- [ ] Job sao lưu có cảnh báo khi thất bại hoặc không chạy
- [ ] Runbook khôi phục kiểm chứng được, hạ tầng dựng lại từ IaC
- [ ] Diễn tập đúng nhịp (tầng 1 hằng quý) vào môi trường sạch
- [ ] RTO/RPO thực đo được và không tệ hơn cam kết
- [ ] Bằng chứng diễn tập lưu đủ cho kiểm toán; khoảng cách có ticket

## Ví dụ tốt
`orders` xếp tầng 1: RTO 1h, RPO 5 phút bằng replica đồng bộ đa AZ và WAL shipping sang vùng thứ hai. Sao lưu hằng ngày vào S3 có object lock 35 ngày, thêm bản sao ở nhà cung cấp thứ hai. Diễn tập quý III ngày 14/08: khôi phục vào tài khoản sạch từ IaC, RTO thực 41 phút, RPO thực 3 phút, đối chiếu 1.284.902 bản ghi và tổng doanh thu ngày khớp tuyệt đối. Hai thiếu sót (thiếu quyền đọc secret, DNS TTL 3600 quá dài) có ticket, sửa xong, diễn tập lại tháng 09 đạt 28 phút.

## Ví dụ xấu
Sao lưu chạy hằng đêm suốt hai năm nhưng chưa từng khôi phục; job đã fail 4 tháng mà không ai biết vì không có cảnh báo; bản sao duy nhất nằm cùng tài khoản và cùng vùng với production, ransomware xóa cả hai; hợp đồng cam kết RTO 4 giờ trong khi khôi phục thật mất 3 ngày vì hạ tầng dựng tay và người biết cách làm đã nghỉ việc.
