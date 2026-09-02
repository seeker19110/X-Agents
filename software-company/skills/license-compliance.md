---
name: license-compliance
version: 2
standards: [SPDX, OpenChain ISO/IEC 5230, OSI Approved Licenses, REUSE Specification, CycloneDX SBOM]
---
# Skill: license-compliance

## Tiêu chuẩn tham chiếu
- SPDX (định danh license và SBOM); CycloneDX làm định dạng SBOM thay thế
- OpenChain ISO/IEC 5230 (chương trình tuân thủ tối thiểu)
- OSI Approved Licenses làm tham chiếu về giấy phép mã nguồn mở
- REUSE Specification (mỗi file có thông tin bản quyền và giấy phép)

## Quy trình (làm đúng thứ tự)
Xác định hình thức phân phối (SaaS, cài tại chỗ, thư viện, ứng dụng di động) vì nghĩa vụ khác nhau → áp chính sách giấy phép → quét phụ thuộc mỗi build và sinh SBOM → xét từng giấy phép mới theo chính sách → xử lý nghĩa vụ (ghi công, kèm văn bản giấy phép, cung cấp mã nguồn nếu bắt buộc) → cập nhật NOTICE mỗi bản phát hành → lưu hồ sơ để kiểm toán.
Hỏi "chúng ta phân phối cái gì cho ai" trước khi kết luận một giấy phép có dùng được không.

## Quy tắc — chính sách giấy phép
- Cho phép: MIT, Apache-2.0, BSD-2/3, ISC, MPL-2.0 (nghĩa vụ ở mức tệp), Unlicense/CC0.
- Cần ADR có người ký: LGPL, EPL, CDDL, và mọi giấy phép "nguồn mở có điều kiện" hoặc giấy phép tùy chỉnh.
- Cấm trong sản phẩm phân phối: GPL/AGPL/SSPL/BUSL và các giấy phép lây lan mạnh, trừ khi có ADR do người có thẩm quyền ký. AGPL đặc biệt lưu ý vì áp cả với dịch vụ qua mạng.
- Không có giấy phép nghĩa là mọi quyền được giữ lại: mã không ghi giấy phép là mã KHÔNG được dùng, kể cả trên GitHub.
- Chú ý giấy phép kép và ngoại lệ (ví dụ GPL kèm ngoại lệ liên kết): đọc điều khoản thực tế, không đoán theo tên.
- Tài sản phi mã nguồn cũng có giấy phép: font, icon, ảnh, âm thanh, dataset, mô hình AI và trọng số — nhiều mô hình có điều khoản hạn chế mục đích sử dụng, phải xét như phụ thuộc.

## Quy tắc — kiểm soát trong quy trình
- Mọi phụ thuộc mới trong PR phải ghi giấy phép theo định danh SPDX; scan tự động (ScanCode/ORT/FOSSA hoặc tương đương) chạy mỗi build và chặn khi vi phạm.
- SBOM sinh cho mỗi artifact phát hành và lưu cùng artifact (xem `security`).
- Phụ thuộc bắc cầu cũng nằm trong phạm vi; giấy phép nguy hiểm thường đến từ tầng thứ ba, không phải tầng trực tiếp.
- Code do AI sinh: không đưa vào khối lớn sao chép nguyên văn từ nguồn có giấy phép không tương thích; khi có nghi ngờ về nguồn gốc thì viết lại từ đặc tả.
- Code lấy từ Stack Overflow, blog, hay kho công khai phải ghi nguồn và kiểm giấy phép như một phụ thuộc.
- Đóng góp ngược lên dự án nguồn mở tuân theo chính sách của công ty và CLA của dự án đó.

## Quy tắc — nghĩa vụ khi phát hành
- NOTICE / THIRD-PARTY cập nhật mỗi bản phát hành: tên, phiên bản, giấy phép, và bản sao văn bản giấy phép khi được yêu cầu.
- Giấy phép yêu cầu cung cấp mã nguồn (LGPL, MPL trong một số cấu hình) thì phải có quy trình cung cấp thật, không chỉ ghi trong tài liệu.
- Kho ứng dụng di động có yêu cầu riêng về ghi công; kiểm trước khi nộp (xem `mobile`).
- Nhãn hiệu và logo không đi kèm giấy phép mã nguồn; dùng tên hoặc logo của bên khác cần quyền riêng.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Mọi phụ thuộc (kể cả bắc cầu) có định danh SPDX
- [ ] Không có giấy phép thuộc nhóm cấm, hoặc có ADR được ký
- [ ] Scan giấy phép pass trong CI và chặn được vi phạm
- [ ] SBOM sinh cho mỗi artifact phát hành
- [ ] NOTICE/THIRD-PARTY cập nhật đúng bản phát hành
- [ ] Font, icon, ảnh, dataset, mô hình AI đã được xét giấy phép
- [ ] Đoạn mã sao chép từ ngoài có ghi nguồn và giấy phép tương thích
- [ ] Nghĩa vụ cung cấp mã nguồn (nếu có) có quy trình thật

## Ví dụ tốt
PR thêm `pdf-lib` (MIT): SPDX ghi trong PR, scan pass, NOTICE cập nhật ở bản 1.4.0, SBOM CycloneDX đính kèm artifact. Một mô hình nhận dạng có điều khoản cấm dùng thương mại → từ chối, chọn mô hình Apache-2.0 thay thế, ghi trong ADR-0012.

## Ví dụ xấu
Thêm thư viện AGPL vào backend SaaS "vì nó tốt nhất"; copy 200 dòng từ một kho không ghi giấy phép; NOTICE viết một lần từ năm ngoái và đã thiếu 30 phụ thuộc; dùng font thương mại tải trên mạng cho ứng dụng bán ra.
