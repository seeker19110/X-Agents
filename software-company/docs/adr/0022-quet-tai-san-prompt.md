# ADR-0022: Tài sản prompt của repo là chuỗi cung ứng, phải có cổng quét riêng

## Bối cảnh
`guard.py` (ADR-0012) canh **dữ liệu chạy qua** hệ thống: payload của event, diff repo khách, kết quả web. Nó không
bao giờ nhìn thứ đứng trước nó trong prompt — **file tài sản của chính repo**: `agents/*.md`, `skills/*.md`,
`templates/`, `gates/`, `topics/`. Những file này ghép thành system prompt (`AgentSpec.system_prompt`) và đi vào mọi
lời gọi model mà không qua một lớp lọc nào.

Đó là bất đối xứng nguy hiểm: một chuỗi "bỏ qua hướng dẫn trước" trong payload chỉ hỏng một event, còn cùng chuỗi ấy
nằm trong `skills/testing.md` thì hỏng **mọi agent nạp skill đó, ở mọi ticket, mãi mãi** — và nó vào repo theo đúng
đường hợp lệ: một PR sửa skill, một merge, một đoạn copy từ tài liệu ngoài. Nghiên cứu ToxicSkills (Snyk, 02/2026)
quét 3.984 skill công khai và thấy 36% chứa prompt injection; các CVE của Claude Code (CVE-2025-59536,
CVE-2026-21852) là cùng một bài học ở tầng cấu hình: file cấu hình do repo kiểm soát **là** bề mặt thực thi.

Repo này đã tuyên bố "prompt là code" và có cổng CI cho code (ruff, mypy, pytest, golden, eval, gitleaks). Prompt thì
chưa có cổng nào ngoài mắt người review — và ký tự vô hình thì mắt người không thấy trong diff.

## Quyết định
1. Thêm `company.assetscan`: quét `agents/ skills/ templates/ gates/ topics/` với bốn rule nặng — `injection`
   (dùng lại `guard.PATTERNS`, một nguồn sự thật duy nhất cho cả hai lớp), `hidden-char` (zero-width, bidi override,
   file không phải UTF-8), `dangerous-command` (`curl … | sh`, `rm -rf /`, `eval $(…)`, POST biến môi trường đi
   nơi khác), `secret-literal` — và một rule cảnh báo `remote-fetch` (URL ngoài allowlist tiêu chuẩn).
2. Miễn trừ nằm trong `assetscan-waivers.txt` ở gốc mỗi công ty, cú pháp `đường/dẫn::rule::lý do`. **Lý do bắt buộc**;
   waiver không còn khớp gì bị báo `waiver-unused` để dọn. Hôm nay đúng một waiver mỗi công ty: `ai-governance.md`
   phải trích nguyên văn mẫu injection để dạy agent nhận diện nó.
3. Thêm `company.assetscan budget`: prompt tĩnh (thân agent + toàn văn skill) so với `budget_tokens_per_task` khai
   trong front matter. Vượt 50% là đỏ, skill khai mà không tồn tại cũng đỏ.
4. CI: job `asset-scan` chạy cả hai lệnh cho `software-company` và `Studio-creators`, nối vào `needs` của `quality`.
   Hai test trong `tests/test_assetscan.py` chạy cùng cổng ngay trong `pytest`, nên `make test` cũng bắt được.

## Hệ quả
- Ký tự ẩn và mẫu điều khiển không vào được `main` qua đường prompt nữa; muốn vào phải qua một waiver có tên người
  duyệt trong lịch sử git.
- Công cụ nằm trong package `company` nhưng quét được cả `Studio-creators` (nó chỉ đọc file, không đụng `registry`).
  Đánh đổi có ý thức: một chút phụ thuộc chéo, đổi lấy việc regex injection chỉ có **một** bản trong repo. Nếu sau
  này có công ty thứ ba, tách `assetscan` ra package dùng chung thay vì copy mẫu.
- `budget` là bẫy hồi quy, không phải chỉ tiêu: hôm nay agent nặng nhất mới 18% (`intake`). Nó sẽ kêu khi ai đó nhồi
  skill vào một agent mà quên nâng ngân sách.
- Rule là mẫu, không phải hàng rào: một injection viết khéo vẫn lọt. Lớp trong vẫn là bọc dữ liệu, trần quyền topic,
  và người duyệt ở gate.
