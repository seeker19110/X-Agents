---
name: devops
version: 2
standards: [DORA, NIST SSDF, SLSA, CIS Benchmarks, IaC, OpenTelemetry, Trunk-based development]
---
# Skill: devops

## Tiêu chuẩn tham chiếu
- DORA: lead time, tần suất triển khai, tỉ lệ thất bại khi đổi, thời gian khôi phục
- NIST SSDF và SLSA cho chuỗi cung ứng phần mềm (build có nguồn gốc, artifact ký)
- CIS Benchmarks cho cấu hình nền tảng
- IaC: hạ tầng khai báo, có review, có state (xem `iac-platform`)
- OpenTelemetry cho quan sát (xem `observability`)
- Trunk-based development + feature flag

## Quy trình (làm đúng thứ tự)
Nhánh ngắn từ trunk → CI chạy nhanh (lint, test, SAST/SCA, secret scan) → build một lần ra artifact bất biến có SBOM và chữ ký → triển khai cùng artifact đó lên dev/stage/prod, chỉ khác cấu hình → migration DB tách khỏi deploy → phát hành từ từ theo `release` → quan sát và có đường lùi.
Không build lại cho từng môi trường; artifact đi qua các môi trường, không đi qua các bản build.

## Quy tắc — pipeline
- CI là cổng bắt buộc: lint, test, SAST, SCA, secret scan, kiểm license, build. Đỏ thì không merge; không có nút bỏ qua riêng cho ai.
- Pipeline nhanh: mốc mục tiêu là phản hồi CI dưới 10 phút cho PR; test chậm tách nhánh riêng chạy song song hoặc theo lịch, không làm chậm vòng lặp chính.
- Build có thể tái lập: phiên bản phụ thuộc ghim (lockfile), image gốc ghim theo digest, không `latest`.
- Mỗi artifact có SBOM và chữ ký; môi trường chỉ chạy artifact đã ký (xem `security`).
- Bí mật lấy từ vault lúc chạy, không nằm trong image, không trong biến build, không in ra log; xoay vòng có lịch.
- Pipeline không có bước thủ công chép tay; quyền deploy prod qua pipeline, không qua tay người.

## Quy tắc — môi trường và hạ tầng
- Mọi tài nguyên qua IaC, `plan` hiện trong PR, `apply` qua pipeline; không sửa tay trên server hay console. Sửa tay là sự cố cấu hình, phải hoàn nguyên và ghi nhận.
- Ba môi trường dùng chung một module IaC, chỉ khác biến; stage phải giống prod ở những điểm ảnh hưởng kết quả kiểm thử.
- Drift detection chạy định kỳ; phát hiện lệch thì hoặc đưa vào code hoặc hoàn nguyên, không để lệch âm thầm.
- Máy chủ là bò không phải thú cưng: thay vì vá tại chỗ thì thay mới từ image; không SSH sửa cấu hình.

## Quy tắc — vận hành và đo lường
- Mỗi dịch vụ có SLO, dashboard RED, alert theo burn rate, và runbook trước khi nhận traffic thật.
- Mọi alert phải có runbook và người nhận; alert không ai hành động được thì xóa.
- Đo và báo cáo DORA mỗi sprint; tỉ lệ thất bại khi đổi tăng thì siết pipeline chứ không siết người.
- Feature flag cho tính năng rủi ro, có đường tắt tức thì; flag có chủ sở hữu và hạn dọn dẹp, không tồn tại vĩnh viễn.
- Khả năng lùi phải được kiểm chứng bằng diễn tập, không chỉ nằm trên giấy (xem `release`).

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Mọi thay đổi hạ tầng qua PR IaC, có `plan` đính kèm
- [ ] CI đủ cổng (lint, test, SAST, SCA, secret scan, license) và không thể bỏ qua
- [ ] Artifact bất biến, ghim phiên bản, có SBOM và chữ ký; cùng artifact chạy qua các môi trường
- [ ] Secret lấy từ vault lúc chạy, không có trong image/log
- [ ] Mỗi alert có runbook và người nhận
- [ ] SLO và dashboard có trước khi nhận traffic
- [ ] Không có thay đổi thủ công trên production; drift được phát hiện và xử lý
- [ ] DORA được đo và báo cáo mỗi sprint

## Ví dụ tốt
PR đổi cấu hình autoscaling: `terraform plan` trong PR (2 thay đổi, 0 hủy), apply qua pipeline sau khi merge; image ghim theo digest, SBOM đính kèm và ký bằng Sigstore; alert "burn rate 14.4× trong 1h" trỏ tới runbook RB-07; feature flag `new_checkout` có owner và hạn dọn 30/09.

## Ví dụ xấu
SSH vào máy sửa file cấu hình cho kịp; build lại image riêng cho prod "để chắc"; alert CPU > 80% gửi cả nhóm không kèm hành động; secret đặt trong biến môi trường của pipeline và in ra khi debug.
