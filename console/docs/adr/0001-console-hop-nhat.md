# ADR-0001: Console hợp nhất là một package riêng, stdlib, chỉ đọc theo mặc định

Trạng thái: Accepted · Ngày: 2026-09-03

## Bối cảnh
Hub đã có ba package chạy độc lập (`software-company`, `Studio-creators`, `gateway`). Người vận hành chỉ có một:
chủ dự án. Mọi thứ người đó cần nhìn — gate đang chờ, ticket kẹt, video trong dây chuyền, token và tiền đã tiêu,
gói tài khoản nào đang nghỉ — hiện nằm rải trong `gate_cli`, `orchestrator status`, `report` của từng công ty và
`gateway status`. Trước một hàng đợi gate quá hạn, người duyệt phải mở bốn cửa sổ mới ghép được bức tranh, và
duyệt gate vẫn phải gõ `subject_id` bằng tay ở đúng thư mục công ty.

Cần một mặt kính duy nhất. Nhưng đây cũng là **bề mặt HTTP đầu tiên trong repo cho phép duyệt human gate**, nên
mọi lựa chọn phải trả lời được câu "nếu bề mặt này bị lạm dụng thì mất gì".

## Quyết định
1. **Một package `console/` ở cấp cao nhất, lấy hai công ty qua path dependency** (`[tool.uv.sources]`, editable).
   Console đọc bus SQLite của cả hai và gọi thẳng `HumanGate` của công ty tương ứng, nên `Decision`, four-eyes,
   allowlist người duyệt và `audit-log` luôn khớp phiên bản đang có trong cây repo, không có bản sao nào để lệch.
2. **Chỉ thư viện chuẩn**: `http.server`, `json`, `sqlite3`; trang là một file HTML tĩnh với CSS và JS thuần.
   Console không được là lý do khiến hub phải theo dõi CVE của một stack web, và phải chạy được trên máy không mạng.
3. **Chỉ đọc là mặc định.** Không cờ gì thì mọi POST bị chặn: console mặc định là *cửa sổ*, muốn nó thành *nút bấm*
   thì phải cố ý gõ `--allow-decide`. Trang hiện rõ đang ở chế độ nào và giải thích cách bật.
4. **Token sinh mỗi lần chạy** (`secrets.token_urlsafe(32)`, ghi `console/.console-token` quyền 0600, chèn vào trang),
   gửi ở header `X-Console-Token`. Kèm bind loopback bắt buộc, chặn `Host`/`Origin` lạ (404/403). Token phiên chứ
   không phải mật khẩu lâu dài: tắt server là hết hiệu lực, không có gì để rò rỉ về sau; ở header chứ không phải
   cookie nên một trang lạ trong cùng trình duyệt không giả mạo POST được.
5. **Console không bao giờ dựng event.** `collect` chỉ đọc; `decide` chỉ chuyển tiếp vào `HumanGate.decide(...)`.
   Không có đường nào để console ghi thẳng vào bus.
6. **Trang không được nói dối.** Công ty chưa chạy bao giờ (chưa có file DB) là trạng thái bình thường: `/api/state`
   trả `sources[x].ok=false` kèm lý do và trang hiện trạng thái rỗng có lý do — **không hiện số 0**. Mất liên lạc thì
   hiện dải cảnh báo và giữ nguyên số liệu lần đọc cuối, không thay bằng số rỗng.

## Đã cân nhắc và bỏ
- **Một giao diện web trong mỗi công ty.** Đúng ranh giới package, nhưng người vận hành lại quay về hai cửa sổ và
  hai lần đăng nhập; hai bản sao code hàng đợi gate sẽ lệch nhau; và mỗi công ty lại phải tự lo phần bảo mật HTTP.
  Vấn đề cần giải là *hợp nhất*, đặt trong công ty thì không giải được.
- **Nhúng vào tiến trình orchestrator** (một cờ `--web` của `make run`). Rẻ nhất, nhưng khiến giao diện chỉ sống khi
  vòng lặp đang chạy — trong khi lúc cần nhìn nhất thường là lúc nó đã dừng — và một lỗi trong lớp HTTP sẽ kéo theo
  cả công ty. Vòng lặp agent và mặt kính quan sát phải hỏng riêng.
- **SPA (React/Vue) hoặc một framework web (FastAPI…).** Thêm hàng trăm phụ thuộc và một bước build vào một hub mà
  cổng chất lượng đang là "cài xong là chạy được offline". Trang này là bảng số và vài biểu đồ SVG; `fetch` mỗi 10
  giây đủ dùng. Nếu sau này thật sự cần, đổi lớp trang mà không phải đụng `collect`/`decide`.
- **Cho phép duyệt gate ngay từ bản đầu.** Bỏ, vì rủi ro không đối xứng: đọc nhầm thì mất một phút, duyệt nhầm thì
  mất một bản phát hành. `--allow-decide` là chi phí gõ thêm một lần cho mỗi phiên có ý định duyệt.

## Hệ quả
- Thêm một package vào cổng CI: `console-static` (ruff + mypy) và `console-unit` (pytest + coverage, 3.11 và 3.13),
  cả hai nối vào `needs` của job `quality`; `console` vào vòng `pip-audit` và vào `dependabot.yml`.
- Console luôn chạy sau hai công ty một nhịp: đổi tên topic hay hình dạng event của công ty nào thì `collect` phải
  cập nhật theo. Hợp đồng ba lớp nằm ở `API.md` cho tới khi ổn định.
- Console đọc DB trong lúc orchestrator đang ghi. Vì chỉ đọc và bus là append-only nên chấp nhận được; số liệu có
  thể trễ tối đa một nhịp làm mới (10 giây).
- Chưa có nhiều người dùng, chưa có phân quyền: `--allow-decide` cho phép duyệt dưới bất kỳ tên nào mà công ty chấp
  nhận. Nếu sau này có nhiều người vận hành thì phải bổ sung danh tính thật, không được dựa vào token phiên.
