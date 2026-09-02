---
name: iac-platform
version: 2
standards: [Terraform/OpenTofu, CIS Benchmarks, OPA/Conftest, Well-Architected, NSA/CISA Kubernetes Hardening]
---
# Skill: iac-platform

## Tiêu chuẩn tham chiếu
- Terraform/OpenTofu module conventions; state remote có khóa và mã hóa
- CIS Benchmarks cho cloud và Kubernetes
- OPA/Conftest — chính sách là code, chạy trong CI
- Well-Architected Framework (vận hành, bảo mật, tin cậy, hiệu năng, chi phí, bền vững)
- NSA/CISA Kubernetes Hardening Guide

## Quy trình (làm đúng thứ tự)
Viết module dùng chung → tham số hóa theo môi trường → `plan` trong PR kèm ước tính chi phí → chính sách (policy) chạy tự động trên plan → duyệt → `apply` qua pipeline → kiểm tra sau khi áp dụng (drift, health) → ghi runbook và alert.
Không có đường tắt qua console: thứ tạo bằng tay không tồn tại đối với hệ thống.

## Quy tắc — hạ tầng khai báo
- Mọi tài nguyên qua IaC; `plan` hiện trong PR, `apply` chỉ qua pipeline; state ở nơi lưu trữ từ xa, có khóa (lock) và mã hóa, không nằm trong repo.
- Một module dùng cho ba môi trường (dev/stage/prod), khác nhau chỉ ở biến; khác biệt bắt buộc phải ghi rõ lý do.
- Ghim phiên bản provider và module; nâng cấp là PR riêng có plan.
- Thay đổi có `destroy` ngoài ý muốn là chặn; muốn xóa tài nguyên có dữ liệu thì phải có bước sao lưu và người duyệt.
- Rollback bằng revert + apply, và phải thử ở môi trường thấp trước khi lên prod.
- Tag bắt buộc trên mọi tài nguyên: project, env, owner, cost-center (xem `finops`); drift detection chạy hằng ngày, lệch thì đưa vào code hoặc hoàn nguyên.

## Quy tắc — bảo mật nền tảng
- Least privilege: không IAM `*`, không bucket công khai, không mở 0.0.0.0/0 vào cổng quản trị; chính sách tự động chặn, không dựa vào người nhớ.
- Mã hóa mặc định at-rest và in-transit; khóa KMS có xoay vòng và có kiểm soát ai dùng được.
- Không secret trong code, biến IaC, hay state; dùng dịch vụ quản lý secret và tham chiếu lúc chạy.
- Mạng phân tầng: tài nguyên dữ liệu ở subnet riêng không ra Internet trực tiếp; truy cập quản trị qua bastion hoặc dịch vụ có ghi log phiên.
- Nhật ký kiểm toán của nền tảng bật ở mọi tài khoản, chuyển về nơi lưu tách biệt, không thể xóa bởi tài khoản bị xâm nhập.
- Tài khoản/dự án tách theo môi trường; quyền vào prod cấp tạm thời có hạn, không cấp cố định.

## Quy tắc — Kubernetes và thời gian chạy
- Mỗi workload có resource request/limit, chạy non-root, hệ thống tệp chỉ đọc, bỏ capability không cần, không chạy đặc quyền.
- Network policy mặc định từ chối, mở theo nhu cầu; dịch vụ có SLO thì có PodDisruptionBudget và tối thiểu hai bản sao ở các vùng khác nhau.
- Image ghim theo digest, quét lỗ hổng trước khi chạy, chỉ chạy image đã ký từ registry nội bộ (xem `security`).
- Probe đúng nghĩa: liveness không phụ thuộc dịch vụ ngoài, readiness phản ánh phụ thuộc thật; tắt êm có `preStop` và thời gian drain.
- Tự động mở rộng dựa trên chỉ số phản ánh tải thật; đặt trần để sự cố không thành hóa đơn khổng lồ.

## Quy tắc — vận hành nền tảng
- Mọi dịch vụ hạ tầng dùng chung có chủ sở hữu, SLO, dashboard và runbook; nền tảng cũng là sản phẩm có khách hàng nội bộ.
- Thay đổi nền tảng ảnh hưởng nhiều đội phải thông báo trước, có cửa sổ, và có đường lùi.
- Diễn tập khôi phục (khôi phục DB, mất một vùng, mất quyền truy cập) định kỳ và ghi kết quả thật.
- Chi phí ước tính đi kèm mọi PR tạo tài nguyên mới.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] `plan` đính kèm PR, không có `destroy` ngoài ý muốn
- [ ] Policy (OPA/Conftest) pass; không IAM `*`, không public bucket, không mở cổng quản trị ra Internet
- [ ] Không secret trong code, biến, hay state; state remote có khóa và mã hóa
- [ ] Đủ tag bắt buộc; drift detection chạy và không có lệch tồn đọng
- [ ] Workload k8s có request/limit, non-root, network policy, PDB nếu có SLO
- [ ] Image ghim digest, đã quét và đã ký
- [ ] Chi phí ước tính có trong PR
- [ ] Có runbook và alert cho dịch vụ nền tảng mới; đã diễn tập khôi phục gần đây

## Ví dụ tốt
PR thêm RDS: dùng module chung, mã hóa bằng KMS có xoay vòng, đặt ở subnet riêng, backup 7 ngày và đã thử restore ở dev, tag đủ 4 nhãn, ước tính 58 USD/tháng, `plan: 4 add, 0 change, 0 destroy`, policy pass; runbook RB-14 mô tả cách failover.

## Ví dụ xấu
Tạo bucket công khai bằng console để thử rồi quên; state Terraform commit vào git; pod chạy root với `hostNetwork` vì "cho tiện"; IAM role gắn `AdministratorAccess` cho ứng dụng.
