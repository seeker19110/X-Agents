# ADR cấp repo

ADR ở đây là cho quyết định kiến trúc chạm **≥ 2 package** (`companies/software-company`, `companies/keeper`,
`platform/gateway`, `platform/console`, `platform/xagents-core`). Quyết định chỉ trong một package thì ADR nằm ở
`<package>/docs/adr/` của package đó.

**Năm dãy số cùng bắt đầu từ 0001, không tiền tố**: `docs/adr/` (đây, cấp repo), `companies/software-company/docs/adr/`,
`companies/keeper/docs/adr/`, `platform/console/docs/adr/`, `platform/gateway/docs/adr/`. Viết "ADR-0004" một mình là
mơ hồ năm chiều — luôn kèm đường dẫn thư mục (`companies/software-company/docs/adr/0004-...`) khi nhắc một ADR không
phải của thư mục này.

Mẫu bốn mục, theo khuôn của ADR-0032 (`companies/software-company/docs/adr/0032-*.md`):

```markdown
# ADR-000N: <tên quyết định>

## Bối cảnh
...

## Quyết định
...

## Hệ quả
...

## Liên quan
...
```

Đánh số tiếp từ ADR gốc cao nhất đã có trong thư mục này.
