# Triển khai hub trên Ubuntu bằng systemd

> ADR gốc [0032](adr/0032-trien-khai-hub-bang-systemd.md). Hub (gateway, orchestrator, console, keeper) chạy
> **trên máy chủ** dưới systemd **user** unit của chính người vận hành; Docker chỉ dùng cho sản phẩm và sandbox của
> khách. Mục 6 ghi rõ cái gì đã đo thật, cái gì chưa.

## 1. Chuẩn bị máy (một lần)

Ubuntu có systemd (máy chủ thật hoặc VPS; WSL2 bật systemd dùng được để thử). Cần sẵn, dưới **user sẽ chạy hub**
(không phải root):

| Thứ | Kiểm | Ghi chú |
|---|---|---|
| `uv`, `git` | `uv --version`, `git --version` | |
| Docker Engine + compose plugin | `docker info` chạy được không cần `sudo` | user trong nhóm `docker` — orchestrator dựng sandbox và deploy khách qua đây |
| `claude` CLI đã đăng nhập | `claude auth status` | nếu dùng gói Claude |
| `gh` đã đăng nhập | `gh auth status` | nếu giao hàng bằng PR (`--deliver-pr`); `GH_TOKEN` trong env **không** dùng được (bị lọc) |
| Tài khoản gateway | `cd platform/gateway && uv run python -m gateway status` | nếu dùng Antigravity; xem §5 cho máy không có trình duyệt |

```bash
git clone https://github.com/seeker19110/X-Agents.git ~/X-Agents
cd ~/X-Agents
uv sync --locked                 # unit chạy `uv run --no-sync`: môi trường phải dựng sẵn ở đây
cp companies/software-company/llm.example.yaml companies/software-company/llm.yaml   # rồi sửa theo gói tài khoản
```

Không dùng `llm.yaml` mà cấu hình model bằng `hub.env` (`COMPANY_LLM_PROVIDER=…`) thì biến đó **ghi đè** llm.yaml
và bỏ `backends:` — phải đặt đủ khối mẫu trong `hub.env.example` (model ba tier + `COMPANY_CLAUDE_MCP=1` cho
claude-code). Thiếu một dòng là dự án đầu tiên kẹt ở gate escalation chứ không lỗi lúc khởi động.

## 2. Cài unit

```bash
scripts/systemd.sh install
```

Script sinh 4 unit vào `~/.config/systemd/user/` (đường dẫn repo và `uv` điền sẵn) và, **chỉ lần đầu**, tạo
`~/.config/x-agents/hub.env` quyền `0600` từ [`deploy/systemd/hub.env.example`](../deploy/systemd/hub.env.example).
Cài lại (sau `git pull`) không đè `hub.env`.

Sửa `~/.config/x-agents/hub.env` — tối thiểu là repo khách:

```bash
ORCHESTRATOR_ARGS=--repo /srv/khach/web-khoa-hoc
CONSOLE_ARGS=--allow-decide --notify-ntfy https://ntfy.sh/<topic-khó-đoán>
```

Bật và cho chạy cả khi không ai đăng nhập, tự bật lại sau reboot:

```bash
systemctl --user enable --now xagents-gateway xagents-orchestrator xagents-console
```

```bash
loginctl enable-linger "$USER"
```

Keeper là tùy chọn: `systemctl --user enable --now xagents-keeper`.

| Unit | Chạy | Thư mục |
|---|---|---|
| `xagents-gateway` | `gateway start --foreground` (127.0.0.1:1123) | `platform/gateway` |
| `xagents-orchestrator` | `company.orchestrator $ORCHESTRATOR_ARGS run --watch 10` | `companies/software-company` |
| `xagents-console` | `console $CONSOLE_ARGS` (127.0.0.1:8200) | `platform/console` |
| `xagents-keeper` | `keeper.cli watch --db keeper.sqlite --repo <repo này> --interval 600` | `companies/keeper` |

Ba quy tắc cứng (có test canh ở `platform/console/tests/test_trien_khai_systemd.py`):

- **Console không `--allow-engine`** — orchestrator đã có unit riêng; console bật thêm một cái thì hai tiến trình
  tranh một lease.
- **Console chỉ nghe 127.0.0.1** — không `--host 0.0.0.0`, không `--i-know`. Từ xa thì SSH tunnel (§3).
- **Dừng bằng SIGINT** — orchestrator trả lease, console xoá file token. `Restart=on-failure` cho mọi unit.

## 3. Theo dõi

**Dashboard:** console tại `http://127.0.0.1:8200` trên máy chủ — token phiên đã chèn sẵn vào trang. Từ máy của bạn:

```bash
ssh -N -L 8200:127.0.0.1:8200 user@may-chu
```

rồi mở `http://127.0.0.1:8200`. Các màn: Trực ban (gate chờ duyệt, bế tắc im lặng, chi phí), Phễu sản phẩm, Xưởng
phần mềm, Chi phí & hạn mức, Nhật ký — xem [`platform/console/README.md`](../platform/console/README.md).

**Không mở trang vẫn biết có việc:** thêm `--notify-ntfy` hoặc `--notify-telegram` vào `CONSOLE_ARGS` (token bot
Telegram đặt `CONSOLE_TELEGRAM_TOKEN` trong `hub.env`).

**Dịch vụ và log:**

```bash
scripts/systemd.sh status
```

```bash
scripts/systemd.sh logs orchestrator
```

```bash
cd companies/software-company && uv run python -m company.orchestrator status
```

`logs console` / `logs gateway` / `logs keeper` cho unit khác. `journalctl --user -u xagents-console -n 30` có dòng
`Mở trang:` của lần khởi động gần nhất.

## 4. Cập nhật, dừng, gỡ

| Việc | Lệnh |
|---|---|
| Cập nhật mã | `git pull && uv sync --locked && scripts/systemd.sh install && systemctl --user restart xagents-gateway xagents-console` — orchestrator `--watch` **tự khởi động lại** khi mã nguồn đổi |
| Đổi `hub.env` | `systemctl --user restart xagents-orchestrator xagents-console` |
| Dừng khẩn toàn hệ thống | `systemctl --user stop xagents-orchestrator` — xem [`TRUC-VA-DUNG-KHAN.md`](TRUC-VA-DUNG-KHAN.md) §1 |
| Gỡ | `scripts/systemd.sh uninstall` — giữ `hub.env` và mọi `*.sqlite` |

## 5. Máy chủ không có trình duyệt

`gateway login`, `claude login`, `codex login` mở trình duyệt. Trên máy chủ:

- Gateway: `uv run python -m gateway login --no-browser` in URL; mở URL đó trên máy bạn **sau khi** đã
  `ssh -N -L 51121:127.0.0.1:51121 user@may-chu` (Google chuyển hướng về `localhost:51121`).
- `claude login` in URL đăng nhập; làm theo hướng dẫn trên terminal.

## 6. Đã đo / chưa đo

Đo thật ngày 2026-10-11 trên Ubuntu 26.04 (WSL2, systemd 259), provider `fake`:

| Phép đo | Kết quả |
|---|---|
| `scripts/systemd.sh install` | 4 unit, `hub.env` quyền `600` |
| `systemctl --user start` gateway + orchestrator + console | cả ba `active`; `GET /` console → 200, `GET /health` gateway → 200 |
| Log trong `journalctl` | có (sau khi thêm `PYTHONUNBUFFERED=1` — trước đó **0 dòng**) |
| `systemctl --user stop xagents-orchestrator` | `company.sqlite.lock` được xoá — lease trả sạch |
| `systemctl --user kill -s SIGKILL xagents-orchestrator` | systemd khởi động lại (`NRestarts=1`), bản mới lấy được lease |
| `scripts/systemd.sh uninstall` | không còn unit `xagents-*`, cổng 8200/1123 trống |

**Chưa đo:** chạy với model thật và repo khách thật dưới systemd; `enable-linger` + reboot máy chủ thật; keeper
dưới systemd.
