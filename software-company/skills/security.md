---
name: security
version: 2
standards: [OWASP ASVS, OWASP Top 10, SLSA L3, SBOM SPDX/CycloneDX, Sigstore, NIST SSDF, CVSS 4.0]
---
# Skill: security

## Tiêu chuẩn tham chiếu
- OWASP ASVS (L2 mặc định; L3 cho tài chính, y tế) và OWASP Top 10 / API Top 10
- NIST SSDF cho vòng đời phát triển an toàn
- SLSA (mức 3 là mục tiêu) cho chuỗi cung ứng: build có nguồn gốc, không sửa được
- SBOM SPDX/CycloneDX và ký artifact bằng Sigstore hoặc tương đương
- CVSS 4.0 để chấm mức nghiêm trọng; EPSS/KEV để ưu tiên theo khả năng bị khai thác thật

## Quy trình (làm đúng thứ tự)
Threat model trước khi code (xem `threat-modeling`) → thiết kế kiểm soát theo ASVS → quét tự động trong CI (SAST, SCA, secret, IaC, container) → review bảo mật phần code chạm dữ liệu và quyền → sinh SBOM và ký artifact → kiểm cấu hình môi trường → theo dõi lỗ hổng mới sau khi phát hành → quy trình xử lý sự cố và báo lỗi từ bên ngoài.
Quét tự động là sàn, không phải trần: công cụ không tìm ra lỗi phân quyền theo nghiệp vụ.

## Quy tắc — trong pipeline
- Mỗi PR chạy: SAST, SCA (phụ thuộc), quét secret (cả lịch sử git), quét IaC, quét image. Kết quả High/Critical là chặn.
- Ngoại lệ phải có hồ sơ: lý do, phạm vi, hạn xử lý, người duyệt. Ngoại lệ hết hạn tự động quay lại trạng thái chặn.
- Lỗ hổng đánh giá theo bối cảnh: CVSS kết hợp khả năng khai thác thực tế (EPSS/KEV) và việc đường mã có thật sự chạm tới. "Không reachable" phải được chứng minh, không phải tuyên bố.
- SLA vá theo mức: Critical trong 7 ngày, High 30 ngày, Medium 90 ngày; lỗ hổng đang bị khai thác ngoài thực địa xử lý như sự cố.
- SBOM sinh cho mỗi artifact; artifact được ký và môi trường chỉ chạy artifact đã ký; nguồn gốc build (provenance) lưu lại.
- Bí mật: không có trong code, log, image, biến build; lộ ra thì xoay vòng ngay và coi là sự cố, xóa commit là chưa đủ.

## Quy tắc — trong sản phẩm
- Xác thực và phiên theo ASVS: băng mật khẩu bằng thuật toán chậm, chống dò tài khoản, giới hạn thử, MFA cho tài khoản quản trị, thu hồi phiên được.
- Phân quyền kiểm ở tầng dữ liệu theo từng đối tượng, không chỉ ở tầng route; test phải có ca người dùng A truy cập tài nguyên của B (xem `backend`).
- Đầu vào validate ở biên, đầu ra escape theo ngữ cảnh, truy vấn tham số hóa, chống SSRF khi gọi URL do người dùng cung cấp, chống upload file thực thi.
- Mã hóa khi truyền và khi lưu; khóa quản lý tập trung, có xoay vòng; không tự chế thuật toán mật mã.
- Ghi nhật ký an ninh cho sự kiện quan trọng (đăng nhập, đổi quyền, truy cập dữ liệu nhạy cảm, hành động quản trị); nhật ký chống sửa và không chứa secret.
- Mặc định an toàn: chức năng mới tắt cho tới khi có kiểm soát; lỗi thì từ chối, không mở.
- Dữ liệu cá nhân xử lý theo `privacy-compliance`; giấy phép phụ thuộc theo `license-compliance`.

## Quy tắc — vận hành và ứng phó
- Có kênh nhận báo lỗi bảo mật từ bên ngoài (security.txt hoặc tương đương) và cam kết thời gian phản hồi.
- Kiểm thử xâm nhập hoặc rà soát độc lập trước các bản phát hành lớn hoặc khi kiến trúc đổi đáng kể.
- Sự cố bảo mật đi theo `incident-management` với yêu cầu bổ sung: giữ nguyên bằng chứng, hạn chế lan rộng, đánh giá nghĩa vụ thông báo theo luật.
- Quyền truy cập production cấp tạm thời có hạn và có ghi log phiên; rà soát quyền định kỳ và thu hồi khi đổi vai trò.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] SAST, SCA, quét secret, quét IaC/image chạy mỗi PR; 0 High/Critical chưa xử lý
- [ ] Ngoại lệ có hồ sơ, hạn và người duyệt
- [ ] SBOM sinh cho mỗi artifact; artifact được ký và nguồn gốc build được lưu
- [ ] Không secret trong code, log, image, hay lịch sử git
- [ ] Có test phân quyền theo đối tượng và test cho các lớp lỗ hổng chính
- [ ] Nhật ký an ninh đủ cho sự kiện quan trọng, không chứa secret
- [ ] SLA vá lỗ hổng được theo dõi và đạt
- [ ] Quyền truy cập production là tạm thời, có log, và được rà soát định kỳ
- [ ] Có kênh tiếp nhận báo lỗi bảo mật từ bên ngoài

## Ví dụ tốt
PR #91: Semgrep 0 High; Trivy 1 Medium (CVE trong `libxyz`, đường mã không chạm tới — chứng minh bằng phân tích gọi hàm, ngoại lệ có hạn 30 ngày do reviewer bảo mật duyệt); gitleaks sạch; SBOM CycloneDX đính kèm và artifact ký bằng Sigstore; test `test_user_cannot_read_other_tenant_order` pass.

## Ví dụ xấu
"Scan lỗi nhưng chắc không sao" rồi merge; API key nằm trong repo từ tháng trước, xử lý bằng cách xóa dòng đó mà không xoay vòng khóa; phân quyền dựa vào việc giao diện không hiện nút; mọi lập trình viên có quyền quản trị production vĩnh viễn.
