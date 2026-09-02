---
name: dependency-management
version: 1
standards: [Semantic Versioning 2.0, CVSS 4.0, OpenSSF Scorecard, SLSA, CycloneDX SBOM, NIST NVD/KEV, Renovate/Dependabot]
---
# Skill: dependency-management

## Tiêu chuẩn tham chiếu
- Semantic Versioning 2.0 để hiểu mức rủi ro của một bản nâng (patch/minor/major)
- CVSS 4.0 chấm mức nghiêm trọng; EPSS và CISA KEV để ưu tiên theo khả năng bị khai thác thật
- OpenSSF Scorecard đánh giá sức khỏe dự án thượng nguồn; SLSA cho tính toàn vẹn chuỗi cung ứng
- CycloneDX/SPDX SBOM làm danh mục phụ thuộc chính thức (xem `license-compliance`)
- Renovate hoặc Dependabot làm cơ chế nâng cấp tự động, có nhóm và lịch

## Quy trình (làm đúng thứ tự)
Sinh SBOM và biết mình đang phụ thuộc gì → phân tầng phụ thuộc theo mức rủi ro → bật bot nâng cấp với nhóm và lịch khai báo → để CI (test, build, quét SCA, license) quyết định pass/fail → gộp nhóm rủi ro thấp tự động, người xét nhóm rủi ro cao → theo dõi cảnh báo CVE liên tục → vá theo cửa sổ tương ứng mức nghiêm trọng → ghi hồ sơ bản vá vào bản phát hành.
Nâng cấp thường xuyên từng bước nhỏ rẻ hơn nhiều so với một lần nhảy bốn phiên bản major khi bị CVE ép.

## Quy tắc — phân tầng và tự động hoá
- Tầng 1 (runtime, framework, thư viện chạm dữ liệu/xác thực/mã hóa): người xét từng bản nâng, có test hồi quy và ghi chú thay đổi.
- Tầng 2 (thư viện ứng dụng thường): patch và minor gộp tự động khi CI xanh; major cần ticket riêng.
- Tầng 3 (công cụ dev, linter, formatter, type stub): gộp tự động theo lô hằng tuần, không chặn phát hành.
- Bot chạy theo lịch cố định (ví dụ thứ Hai 08:00), giới hạn ≤ 10 PR mở cùng lúc để không làm nghẹt review.
- Nâng cấp và thay đổi tính năng không nằm chung một PR; PR nâng cấp chỉ chứa lockfile và các sửa tương thích tối thiểu.
- Không tự động gộp bất kỳ thứ gì vào nhánh phát hành mà bỏ qua cổng CI đầy đủ, kể cả patch.

## Quy tắc — cửa sổ vá theo mức nghiêm trọng
- Critical (CVSS ≥ 9.0) hoặc có trong CISA KEV: vá hoặc giảm nhẹ trong 24 giờ, tính từ lúc cảnh báo tới hệ thống của công ty.
- High (7.0–8.9): 7 ngày. Medium (4.0–6.9): 30 ngày. Low (< 4.0): gộp vào chu kỳ nâng cấp thường.
- Mốc tính theo khả năng khai thác thực tế trong ngữ cảnh của ta, không theo con số CVSS thô: lỗ hổng ở đường dẫn không đạt tới được có thể hạ mức, nhưng phải ghi lý do và người quyết.
- Không vá kịp trong cửa sổ thì phải có biện pháp giảm nhẹ tạm (tắt tính năng, chặn ở WAF, giới hạn quyền) và ticket có hạn.
- Lỗ hổng chạm dữ liệu cá nhân hoặc thanh toán leo thang theo `security` và `incident-management`, không xử lý như việc thường.

## Quy tắc — pin, lockfile và tương thích
- Lockfile commit vào kho cho mọi ứng dụng phát hành được; build tái lập được từ lockfile, không phụ thuộc "phiên bản mới nhất lúc build".
- Thư viện dùng khoảng phiên bản rộng hợp lý; ứng dụng pin chặt. Base image pin theo digest, không theo tag `latest`.
- Sau nâng cấp: chạy toàn bộ test, kiểm tra ghi chú thay đổi phần breaking, và so đo hiệu năng nếu là thư viện trên đường nóng (xem `performance-testing`).
- Bản nâng major đi kèm ticket có phạm vi, kế hoạch rút lui và, khi cần, cờ tính năng.
- Phụ thuộc bỏ hoang (không phát hành > 24 tháng, không phản hồi issue bảo mật, hoặc Scorecard thấp): mở ticket thay thế trong 90 ngày; nếu buộc phải giữ thì vendor hóa vào kho, ghi ADR và nhận trách nhiệm bảo trì.
- Cấm phụ thuộc mới không cần thiết: mỗi thư viện thêm vào phải nêu lý do trong PR; thư viện một hàm thì tự viết.
- Cảnh giác nhầm tên gói (typosquatting) và tấn công chuỗi cung ứng: kiểm tên, chủ sở hữu, số lượt tải và nguồn kho trước khi thêm.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] SBOM sinh cho mỗi artifact và lưu cùng artifact
- [ ] Phụ thuộc được phân tầng; chính sách tự động gộp khai báo rõ
- [ ] Bot nâng cấp bật, có lịch và giới hạn số PR mở
- [ ] Lockfile commit; base image pin theo digest
- [ ] Quét SCA chạy mỗi PR và chặn High/Critical
- [ ] Cửa sổ vá 24h/7d/30d được tuân thủ hoặc có giảm nhẹ + ticket có hạn
- [ ] PR nâng cấp tách khỏi PR tính năng
- [ ] Bản nâng major có kế hoạch rút lui
- [ ] Phụ thuộc bỏ hoang có ticket thay thế hoặc ADR nhận bảo trì

## Ví dụ tốt
Renovate chạy thứ Hai, tối đa 8 PR: nhóm dev-tools gộp tự động, nhóm framework do backend xét. CVE-2026-1187 trong `libxml` (CVSS 9.1, có trong KEV) được cảnh báo 09:14 → vá và phát hành 16:40 cùng ngày, trong cửa sổ 24h. Nâng ORM 4→5 làm ticket riêng, sau cờ `orm_v5`, đo p95 trước/sau lệch 3%. Thư viện `date-utils` bỏ hoang 31 tháng → thay bằng thư viện chuẩn, đóng ticket sau 6 tuần.

## Ví dụ xấu
Không có lockfile, build hôm nay khác hôm qua; bot gửi 60 PR và không ai xem nên tắt luôn bot; PR "nâng cấp + thêm tính năng + refactor" 4.000 dòng không ai review nổi; CVE Critical để 4 tháng vì "chưa có thời gian", không có giảm nhẹ; base image `node:latest` khiến bản phát hành cũ không dựng lại được.
