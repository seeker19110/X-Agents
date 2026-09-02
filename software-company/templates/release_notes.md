# Release notes: <tên sản phẩm> v<x.y.z>
Dùng khi phát hành một phiên bản ra staging/prod; release-manager điền, theo chuẩn Keep a Changelog.

- release_id: REL-xx · Ngày phát hành: <YYYY-MM-DD> · Môi trường: staging|prod

## Added
- <tính năng mới> (TCK-xx)

## Changed
- <thay đổi hành vi> (TCK-xx)

## Fixed
- <lỗi đã sửa> (BUG-xx)

## Removed
- <tính năng/endpoint đã gỡ>

## Security
- <vá lỗ hổng, đổi cấu hình bảo mật> (T-xx)

## Thay đổi phá vỡ tương thích (breaking)
| Thay đổi | Ai bị ảnh hưởng | Phải làm gì |
|---|---|---|
- Không có: ghi rõ "Không có".

## Hướng dẫn nâng cấp
1. <migration cần chạy: `<id>`>
2. <biến môi trường/flag mới>
3. <thứ tự deploy nếu nhiều service>

## Ticket liên quan
| Ticket | Requirement | Tóm tắt |
|---|---|---|

## Rollback
- Cách: revert release | flag `<tên>` off | migration down `<id>`
- Thời gian mục tiêu: < <n> phút · Dữ liệu mất/không mất:
- Runbook: <link>
