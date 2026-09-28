# console — trực ban hợp nhất cho các công ty AI

Một trang web cục bộ cho **người chủ dự án**: nhìn `software-company` (và công ty bảo trì `keeper`) trên
một màn hình, thấy ngay việc gì đang chờ mình duyệt, tiêu bao nhiêu token và tiền, và (khi bật) duyệt
human gate ngay tại chỗ.

Console **đọc bus SQLite của công ty ở chế độ chỉ đọc** và không bao giờ tự dựng event: mọi quyết
định gate đi qua đúng lớp `HumanGate` của công ty tương ứng, nên four-eyes, allowlist người duyệt và
`audit-log` vẫn đi đúng đường của repo.

**Tab Hướng dẫn** trả lời tại chỗ ba câu người mới hay hỏi: hệ này làm gì, sao nút của tôi bị mờ (bảng quyền đọc
đúng cờ của phiên đang chạy), và giao một việc mới thế nào. Nút *Điền yêu cầu mẫu* ở form yêu cầu phần mềm đổ sẵn
một đề bài web app thật (cùng nội dung với `software-company/examples/yeu-cau-mau-web-app.json`) để sửa lại, thay vì
nhìn ô trống rồi viết hai dòng mà `product` (pha spec) phải hỏi lại năm lần.

**Giao việc ngay trên trang** (bật `--allow-submit`): đầu màn *Xưởng phần mềm* có form *Yêu cầu phần mềm*
(`research-requests`, kèm **nơi lưu dự án** = repo git của khách cho riêng dự án đó, ADR-0025) và *Trả lời câu hỏi
làm rõ* (`clarification-answers`). Form chỉ gom trường thành payload; event được publish qua đúng `SQLiteBus` của
công ty nên vẫn bị kiểm theo JSON Schema của topic y như nạp bằng CLI `publish`. Không cần tạo file JSON tay nữa;
agent nhận việc ở nhịp `run --watch` kế tiếp.

Không framework web, không CDN, không phụ thuộc runtime nào ngoài software-company/keeper: server là
`http.server` của thư viện chuẩn, trang là một file HTML tĩnh dùng `fetch`.

**Cập nhật tức thì.** Trang nối `GET /api/stream` (SSE) nên gate mới hiện trong khoảng một giây thay vì
chờ hết nhịp làm mới — nhãn *trực tiếp* ở thanh trên cùng. Stream đứt thì tự lùi về hỏi lại 10 giây một
lần (*hỏi lại 10s*) và thử nối lại, nên mất stream chỉ là chậm hơn chứ không hỏng. Đang mở ngăn kéo hoặc
đã bấm Tạm dừng thì dữ liệu mới được **giữ lại** chứ không vẽ đè, kèm nút *Có dữ liệu mới — xem*.

**Địa chỉ mang chỗ đang đứng.** `#/phan-mem` là một màn, `#/truc-ban/gate/PLAN-1` là màn đó với ngăn kéo
gate đang mở — F5 không văng về Trực ban, Back đóng ngăn kéo thay vì rời trang, và gửi được link tới đúng
một gate cho người khác. Link tới thứ đã bị xoá thì tự rút về màn tương ứng.

**Cài thành app.** Trang là một PWA: mở trong Chrome/Edge rồi bấm biểu tượng cài đặt ở thanh địa chỉ
(hoặc menu → *Cài ứng dụng này*) là có cửa sổ riêng, không thanh địa chỉ, kèm icon ở Start Menu và taskbar.
Vẫn phải chạy `python -m console` trước — PWA chỉ là cái vỏ, dữ liệu vẫn đến từ server cục bộ.

Service worker ở đây **cố ý làm ít nhất có thể**: chỉ cache hai file icon. Nó không bao giờ cache `/api/*`
(số liệu cũ trên một mặt kính trực ban là đúng thứ tệ nhất) và không bao giờ cache `/` (trang mang token
phiên, mà token sinh mới mỗi lần chạy server — cache trang là lần sau ăn 401 toàn tập). Console không dùng
được khi server chưa chạy, nên chạy offline không phải mục tiêu.

Cài đặt chỉ hoạt động ở ngữ cảnh an toàn, tức `127.0.0.1`/`localhost`. Bind ra ngoài loopback bằng
`--i-know` thì trình duyệt từ chối đăng ký service worker; trang vẫn chạy đủ, chỉ là không cài được.

**Tìm và lọc.** Ô tìm chung (phím `/`) lọc gate, ticket, PR, review và audit-log cùng lúc, gấp dấu
tiếng Việt. Bảng ticket có chip lọc theo trạng thái; các bảng sắp xếp được bằng cách bấm tiêu đề cột.
Phím tắt: `/` tìm, `1`–`8` nhảy màn (theo thứ tự ở thanh bên), `g` về Trực ban, `Esc` đóng.

## Chạy nhanh

```bash
cd platform/console
uv sync
uv run python -m console          # mặc định 127.0.0.1:8200, chế độ chỉ đọc
```

Terminal in ra địa chỉ kèm token phiên — mở đúng địa chỉ đó. Muốn duyệt gate ngay trên trang:

```bash
uv run python -m console --allow-decide
uv run python -m console --allow-config    # cho phép sửa model/backend của từng công ty ngay trên trang
uv run python -m console --allow-engine    # cho phép BẬT/TẮT orchestrator của từng xưởng ngay trên trang
```

**Bật động cơ ngay trên trang** (`--allow-engine`, ADR-0004). Ô *Động cơ* ở đầu màn Trực ban có một dòng cho mỗi
xưởng: đang chạy hay không, pid, nhịp, ai bật, và đuôi log khi nó chết. Bấm *Bật* là console chạy đúng lệnh mà
bạn vẫn gõ tay (`orchestrator run --watch`, in nguyên văn vào đầu file log `console/.engine/<xưởng>.log`) trong
đúng thư mục công ty. Model vẫn là gói thuê bao khai trong `llm.yaml` — console không truyền model, không truyền
API key. Không có ô này thì giao việc xong mà quên bật orchestrator là **việc nằm im, không lỗi, không dấu hiệu**.

Bốn giới hạn cố ý: động cơ do console bật **chết khi tắt console** (chạy dài ngày thì vẫn bật ở terminal như cũ);
ô này **không thấy** orchestrator do người khác bật; `--allow-engine` là cờ riêng, `--allow-decide` không mở nó
— ký gate và đốt hạn mức model là hai quyền khác nhau; và **mặc định động cơ KHÔNG giao hàng**.

Giao hàng phải nêu tên remote lúc chạy console:

```bash
uv run python -m console --allow-decide --allow-engine --deliver-remote origin
```

Không có `--deliver-remote` thì orchestrator chạy không `--deliver --push-remote`, nên release đã duyệt **không**
được tag và đẩy lên repo khách — sự cố 2026-09-10 (QA pass, gate ký, khách nghiệm thu, sản phẩm nằm lại máy) đúng
là chế độ này. Ô Động cơ khai `delivers` cho từng xưởng để chế độ đó không im lặng. Remote đến từ dòng lệnh của
người trực, **không bao giờ** từ `POST /api/engine`: argv chốt cứng trong `SPECS`, không nhận tham số client.

Mục **Cài đặt model** trong trang cho từng công ty: chọn model cho tier mạnh/tiêu chuẩn/nhẹ trên từng backend,
đặt ưu tiên backend theo tier, bật/tắt backend. Giá trị hiển thị là đúng cái đang chạy (`llm.yaml`); lưu là ghi
thẳng vào file, bản cũ để lại `llm.yaml.bak`. Không muốn mở trang thì dùng CLI:

```bash
uv run python -m console models
uv run python -m console models --company software-company --set antigravity.standard=gemini-3.8-flash-medium
uv run python -m console models --company software-company --prefer standard=antigravity --disable chatgpt-sub
```

Đường dẫn DB không phải mặc định thì chỉ ra bằng `--company-db` / `--keeper-db`; công ty nào chưa
chạy bao giờ (chưa có file DB) cũng không sao — trang báo phần đó đang trống và vì sao, không hiện số 0 giả.

## Bảo mật

Đây là bề mặt HTTP đầu tiên cho phép duyệt human gate, nên mặc định khoá chặt:

- **Chỉ loopback.** Server chỉ bind `127.0.0.1`/`::1`; `--host` khác thì từ chối khởi động (trừ `--i-know`,
  và có in cảnh báo). Request có `Host` không phải loopback bị trả 404, `Origin` lạ bị trả 403 — chống DNS rebinding.
- **Token mỗi lần chạy.** `secrets.token_urlsafe(32)`, sinh mới mỗi lần khởi động, ghi `console/.console-token`
  quyền 0600 (đã nằm trong `.gitignore`) và chèn vào trang. Mọi `/api/*` phải kèm header `X-Console-Token`;
  token ở header chứ không phải cookie nên trang ngoài không giả mạo POST được.
- **Chỉ đọc là mặc định.** Không có `--allow-decide` thì mọi POST bị chặn 403 và trang khoá sẵn các nút
  quyết định kèm giải thích cách bật. Bốn quyền ghi tách riêng và không cái nào mở cái nào:
  `--allow-decide` (ký gate) · `--allow-submit` (giao việc) · `--allow-config` (đổi model) ·
  `--allow-engine` (bật/tắt động cơ — nặng nhất, tạo tiến trình con gọi model).
- **Dòng lệnh của động cơ không nhận gì từ trang.** `argv` dựng từ bảng chốt cứng trong `engine.py`; thứ duy
  nhất client đặt được là nhịp (giây, kẹp 5–3600). Không `shell=True`, không đường dẫn từ body.
- **Không log token, không log body.**

## Trang có gì

| Màn hình | Nội dung |
|---|---|
| **Trực ban** | Hàng đợi human gate của xưởng phần mềm và keeper, xếp theo mức quá hạn (`over` ≥ 24 giờ, `warn` ≥ 12 giờ — khớp `GATE_TIMEOUT_H`/`GATE_REMIND_H`); ô số event, lời gọi model, token, tỉ lệ làm lại, PR chưa kiểm; chi phí 14 ngày tách theo tier; bảng gói tài khoản đang xoay; 10 bản ghi audit gần nhất |
| **Phễu sản phẩm** | Một hàng cho MỖI sản phẩm: yêu cầu → đặc tả → ticket → RC → staging (smoke) → production (smoke) → nghiệm thu. Ô không có dữ liệu là **ô xám gạch đứt**, không bao giờ xanh; bậc staging/production chỉ tính khi có `smoke` (bằng chứng máy sinh, ADR-0029 của company) — `status: deployed` do agent tự khai thì bậc đó vẫn xám |
| **Xưởng phần mềm** | Bảng ticket theo trạng thái kèm mức tiêu ngân sách, pull request chờ review (lint/test do code chạy thật) và cột **commit vượt integration** (`git rev-list --count company/integration..ticket/<id>` — `0` là đã gộp hết, `—` là không đo được), kết quả review theo nguồn `reviewer` · `qa` · `security` (hai nguồn đầu đều do agent `qa` chấm) kèm **nguồn ngữ cảnh bị cắt** ngay cạnh verdict |
| **Chi phí & hạn mức** | Chi phí dự án so với trần, lời gọi chưa có giá (gói thuê bao), hiệu chỉnh ước lượng, ngân sách token từng ticket, chi phí theo agent, mọi lần supervisor can thiệp |
| **Nhật ký** | Toàn bộ `audit-log` (tối đa 200 bản ghi mới nhất), lọc theo sản phẩm agent / gate / supervisor / người / lỗi |
| **Hướng dẫn** | Cách dùng ngay trong trang: hệ thống làm gì, ba quyền và **trạng thái thật của phiên đang chạy** (cờ nào đang bật, cờ nào chưa), các bước giao việc, bốn điểm dừng chờ người, cách duyệt gate, lệnh dòng lệnh tương đương, ba lỗi hay gặp |

Đầu màn **Trực ban** có hai cảnh báo đỏ tách riêng: *bế tắc im lặng* (ticket kẹt mà **không gate nào chờ** — không
ai được hỏi, loại duy nhất sẽ không tự kêu) đứng trên bảng bế tắc chung.

Bấm vào một gate mở ngăn kéo: hồ sơ, checklist phải tick hết mới duyệt được, **hậu quả cả hai chiều** (duyệt thì
agent nào chạy lại, từ chối thì ticket về trạng thái nào), nút **Dựng hồ sơ bằng chứng** (`gate_brief` — cùng một
văn bản với `/gate-brief` của CLI, `GET`, không cần `--allow-decide`), ô ghi tên người duyệt và lý do (bắt buộc với
mọi quyết định không phải `approve`; escalation cần ≥ 20 ký tự vì lý do đi thẳng cho agent làm hint — có nút chèn
mẫu `root_cause` / `decision` / `hint`, và ô xem trước **nguyên văn** chuỗi agent sẽ nhận).

Trang tự làm mới **10 giây một lần**, có nút tạm dừng, và tự ngưng làm mới khi ngăn kéo đang mở.
Mất liên lạc với server thì hiện dải cảnh báo trên cùng và **giữ nguyên số liệu lần đọc cuối** — không
bao giờ thay dữ liệu thật bằng số rỗng.

## Cấu trúc

```
src/console/collect.py   đọc SQLite bus của software-company + keeper + trạng thái gateway → dict thuần
src/console/truth.py     "sự thật giao hàng": phễu release, phễu sản phẩm, bế tắc im lặng, quyết định chưa áp
src/console/git_truth.py commit vượt nhánh tích hợp (`git rev-list --count`, chỉ đọc; repo lấy từ bus)
src/console/brief.py     hồ sơ gate_brief cho trang, gọi thẳng company.gate_brief (chỉ đọc)
src/console/decide.py    ghi quyết định gate qua HumanGate của từng công ty
src/console/server.py    ThreadingHTTPServer stdlib: trang tĩnh + /api/state + /api/gate/{decide,brief}
src/console/static/      trang trực ban (HTML + CSS + JS thuần, không phụ thuộc ngoài)
API.md                   hợp đồng nội bộ giữa ba lớp — đọc trước khi sửa bất kỳ lớp nào
```

Các công ty vào bằng path dependency (`[tool.uv.sources]`), nên console luôn dùng đúng `HumanGate`,
`Decision` và schema event của phiên bản đang có trong cây repo.

## Phát triển

```bash
uv run ruff check src tests
uv run mypy src/console --ignore-missing-imports
uv run pytest -q --cov --cov-report=term
```

Quyết định thiết kế: [`docs/adr/0001-console-hop-nhat.md`](docs/adr/0001-console-hop-nhat.md) ·
[`0002` đẩy trạng thái bằng SSE](docs/adr/0002-day-trang-thai-va-dia-chi-la-trang-thai.md) ·
[`0003` mỗi ô trả lời một câu hỏi, ô rỗng là ô xám](docs/adr/0003-moi-o-tra-loi-mot-cau-hoi-o-rong-la-o-xam.md).
