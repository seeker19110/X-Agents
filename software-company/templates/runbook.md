# Runbook: <tên dịch vụ>
Dùng khi vận hành/trực sự cố dịch vụ này; platform-engineer (hoặc owner dịch vụ) điền và cập nhật mỗi lần đổi deploy/alert.

- service: <tên> · env: dev|staging|prod · repo: <link>
- Owner: <team/agent> · On-call: <ai> · Cập nhật lần cuối: <ngày>

## Kiến trúc tóm tắt
- Thành phần: <api, worker, cron, db, cache>
- Vào/ra: <endpoint, queue, topic>
- Dashboard: <link> · Log: <link>

## Phụ thuộc
| Thành phần | Loại (nội bộ/bên thứ ba) | Hỏng thì sao | Fallback |
|---|---|---|---|

## Deploy
- Cách chạy: `<lệnh/pipeline>`
- Điều kiện trước: <gate, migration, feature flag>
- Kiểm tra sau deploy: <health check, smoke test>

## Rollback
- Cách: revert release | flag `<tên>` off | migration down `<id>`
- Lệnh: `<lệnh>`
- Thời gian mục tiêu: < <n> phút · Dữ liệu mất/không mất: <ghi rõ>
- Ai được quyền quyết định rollback: <vai trò>

## Alert và ngưỡng
| Alert | Điều kiện | Ngưỡng | Severity | Việc cần làm |
|---|---|---|---|---|

## Sự cố thường gặp
| Triệu chứng | Nguyên nhân hay gặp | Bước xử lý | Kiểm chứng đã xong |
|---|---|---|---|

## Leo thang
| Mức | Sau bao lâu | Liên hệ | Kênh |
|---|---|---|---|

## Checklist trước khi coi runbook là "đã thử" (Gate 3)
- [ ] Deploy chạy thật ít nhất 1 lần theo đúng lệnh trên
- [ ] Rollback đã diễn tập và đo được thời gian
- [ ] Mọi alert có việc cần làm tương ứng
- [ ] Liên hệ leo thang còn hiệu lực
