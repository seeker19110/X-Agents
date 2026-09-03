# console — trực ban hợp nhất cho các công ty AI

Một trang web cục bộ cho **người chủ dự án**: nhìn cả `software-company` và `Studio-creators` trên cùng
một màn hình, thấy ngay việc gì đang chờ mình duyệt, tiêu bao nhiêu token và tiền, và (khi bật) duyệt
human gate ngay tại chỗ.

Console **đọc bus SQLite của hai công ty ở chế độ chỉ đọc** và không bao giờ tự dựng event: mọi quyết
định gate đi qua đúng lớp `HumanGate` của công ty tương ứng, nên four-eyes, allowlist người duyệt và
`audit-log` vẫn đi đúng đường của repo.

Không framework web, không CDN, không phụ thuộc runtime nào ngoài hai công ty: server là `http.server`
của thư viện chuẩn, trang là một file HTML tĩnh dùng `fetch`.

## Chạy nhanh

```bash
cd console
uv sync
uv run python -m console          # mặc định 127.0.0.1:8200, chế độ chỉ đọc
```

Terminal in ra địa chỉ kèm token phiên — mở đúng địa chỉ đó. Muốn duyệt gate ngay trên trang:

```bash
uv run python -m console --allow-decide
uv run python -m console --allow-config    # cho phép sửa model/backend của từng công ty ngay trên trang
```

Mục **Cài đặt model** trong trang cho từng công ty: chọn model cho tier mạnh/tiêu chuẩn/nhẹ trên từng backend,
đặt ưu tiên backend theo tier, bật/tắt backend. Giá trị hiển thị là đúng cái đang chạy (`llm.yaml`); lưu là ghi
thẳng vào file, bản cũ để lại `llm.yaml.bak`. Không muốn mở trang thì dùng CLI:

```bash
uv run python -m console models
uv run python -m console models --company software-company --set antigravity.standard=gemini-3.8-flash-medium
uv run python -m console models --company software-company --prefer standard=antigravity --disable chatgpt-sub
```

Đường dẫn DB không phải mặc định thì chỉ ra bằng `--company-db` / `--studio-db`; công ty nào chưa
chạy bao giờ (chưa có file DB) cũng không sao — trang báo phần đó đang trống và vì sao, không hiện số 0 giả.

## Bảo mật

Đây là bề mặt HTTP đầu tiên cho phép duyệt human gate, nên mặc định khoá chặt:

- **Chỉ loopback.** Server chỉ bind `127.0.0.1`/`::1`; `--host` khác thì từ chối khởi động (trừ `--i-know`,
  và có in cảnh báo). Request có `Host` không phải loopback bị trả 404, `Origin` lạ bị trả 403 — chống DNS rebinding.
- **Token mỗi lần chạy.** `secrets.token_urlsafe(32)`, sinh mới mỗi lần khởi động, ghi `console/.console-token`
  quyền 0600 (đã nằm trong `.gitignore`) và chèn vào trang. Mọi `/api/*` phải kèm header `X-Console-Token`;
  token ở header chứ không phải cookie nên trang ngoài không giả mạo POST được.
- **Chỉ đọc là mặc định.** Không có `--allow-decide` thì mọi POST bị chặn 403 và trang khoá sẵn các nút
  quyết định kèm giải thích cách bật.
- **Không log token, không log body.**

## Trang có gì

| Màn hình | Nội dung |
|---|---|
| **Trực ban** | Hàng đợi human gate của cả hai xưởng, xếp theo mức quá hạn (`over` ≥ 24 giờ, `warn` ≥ 12 giờ — khớp `GATE_TIMEOUT_H`/`GATE_REMIND_H`); ô số event, lời gọi model, token, tỉ lệ làm lại, PR chưa kiểm; chi phí 14 ngày tách theo tier; bảng gói tài khoản đang xoay; 10 bản ghi audit gần nhất |
| **Xưởng phần mềm** | Bảng ticket theo trạng thái kèm mức tiêu ngân sách, pull request chờ review (lint/test do code chạy thật), kết quả review của reviewer · qa · security |
| **Xưởng video** | Dây chuyền video theo trạng thái, số liệu sau khi đăng kéo từ YouTube Analytics, đường giữ chân người xem |
| **Chi phí & hạn mức** | Chi phí dự án so với trần, lời gọi chưa có giá (gói thuê bao), hiệu chỉnh ước lượng, ngân sách token từng ticket, chi phí theo agent, mọi lần supervisor can thiệp |
| **Nhật ký** | Toàn bộ `audit-log` (tối đa 200 bản ghi mới nhất), lọc theo sản phẩm agent / gate / supervisor / người / lỗi |

Bấm vào một gate mở ngăn kéo: hồ sơ, checklist phải tick hết mới duyệt được, ô ghi tên người duyệt và
lý do (bắt buộc với mọi quyết định không phải `approve`).

Trang tự làm mới **10 giây một lần**, có nút tạm dừng, và tự ngưng làm mới khi ngăn kéo đang mở.
Mất liên lạc với server thì hiện dải cảnh báo trên cùng và **giữ nguyên số liệu lần đọc cuối** — không
bao giờ thay dữ liệu thật bằng số rỗng.

## Cấu trúc

```
src/console/collect.py   đọc SQLite bus của hai công ty + trạng thái gateway → dict thuần
src/console/decide.py    ghi quyết định gate qua HumanGate của từng công ty
src/console/server.py    ThreadingHTTPServer stdlib: trang tĩnh + /api/state + /api/gate/decide
src/console/static/      trang trực ban (HTML + CSS + JS thuần, không phụ thuộc ngoài)
API.md                   hợp đồng nội bộ giữa ba lớp — đọc trước khi sửa bất kỳ lớp nào
```

Hai công ty vào bằng path dependency (`[tool.uv.sources]`), nên console luôn dùng đúng `HumanGate`,
`Decision` và schema event của phiên bản đang có trong cây repo.

## Phát triển

```bash
uv run ruff check src tests
uv run mypy src/console --ignore-missing-imports
uv run pytest -q --cov --cov-report=term
```

Quyết định thiết kế: [`docs/adr/0001-console-hop-nhat.md`](docs/adr/0001-console-hop-nhat.md).
