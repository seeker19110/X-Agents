# Gợi ý nâng cấp — rà soát 2026-10-13

> Lấy từ đợt rà soát chéo 19 repo của chủ sở hữu (ma trận vệ sinh ở [seeker19110/stored, mục 23 §8.1](https://github.com/seeker19110/stored/blob/main/23-own-repos-lessons/README.md); gợi ý tích hợp ở §7b của cùng file). Số liệu đo bằng lệnh trên HEAD (đếm `uses:` ghim SHA 40 ký tự, khối `permissions:`, `dependabot.yml`, `.claude/settings.json`), không suy ra từ văn xuôi. Đây là **đề xuất**, chưa sửa code. Mỗi mục kèm bằng chứng để kiểm lại trước khi làm; mục nào đã xử lý thì đánh dấu hoặc xoá.

## Hiện trạng đo được

| HEAD đọc | Action ghim SHA | Workflow thiếu `permissions:` cấp đầu | Dependabot | LICENSE · SECURITY | File test |
|---|---|---|---|---|---|
| `8bf4890` (2026-10-12) | 0/42 | `ci.yml`, `eval-record.yml`, `pr-policy.yml` | uv, github-actions | có · có | 255 |

## Đề xuất (🔴 cao · 🟠 trung bình · 🟢 nhẹ)

| # | Mức | Đề xuất | Bằng chứng | Kiểm xong khi |
|---|---|---|---|---|
| 1 | 🟠 | Ghim cả **42** `uses:` theo SHA 40 ký tự (kèm comment tag) bằng pinact hoặc ratchet; Dependabot `github-actions` đã có nên sẽ tự bump SHA | `grep -hE "uses:" .github/workflows/*.yml \| grep -vcE "@[0-9a-f]{40}"` → 42 (ví dụ `ci.yml:20` `actions/checkout@v7`). Repo anh em projects-template, xboss, Sales-Hunter đều đã 100% | Lệnh trên trả về 0 |
| 2 | 🟢 | Thêm `permissions: contents: read` ở cấp đầu của `ci.yml`, `eval-record.yml` và `pr-policy.yml`; giữ quyền riêng ở cấp job | Ba file này chỉ khai `permissions:` ở cấp job (`ci.yml` có 19 khối). Job mới thêm sau này sẽ thừa hưởng quyền mặc định của repo | `grep -L "^permissions:" .github/workflows/*.yml` rỗng |
| 3 | 🟢 | Ghim digest cho base image: `FROM python:3.13-slim@sha256:…`, và thêm ecosystem `docker` vào Dependabot | `Dockerfile` đang dùng `FROM python:3.13-slim` (tag trôi) | Dependabot mở PR bump digest |

## Giữ nguyên (điểm mạnh)

- `verified_by` do code điền, eval record/replay, human gate 24h, keeper.
- Dependabot uv + github-actions, CODEOWNERS, rulesets-as-code.

## Gợi ý tích hợp từ catalog `stored`

- Mẫu middleware của Decepticon: HITL cho hành động tác động cao, audit ledger HMAC, untrusted-output (stored mục 12 §3g).
- promptfoo cho eval record/replay (stored mục 07).

## Ghi chú chung

- Ghim action theo SHA bằng [pinact](https://github.com/suzuki-shunsuke/pinact) hoặc [ratchet](https://github.com/sethvargo/ratchet), giữ comment tag (`# v7.0.1`), rồi để Dependabot `github-actions` tự nâng SHA. Đây là cách projects-template, xboss và Sales-Hunter đang làm.
- Chuẩn tham chiếu là `seeker19110/projects-template`: 25/25 action ghim SHA, mọi workflow có `permissions:` cấp đầu, Dependabot cho npm, github-actions và pip.
