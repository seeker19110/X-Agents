# ADR-0032: Triển khai hub trên Ubuntu bằng systemd user unit; Docker chỉ cho sản phẩm và sandbox của khách

Ngày: 2026-10-11 · Trạng thái: **đề xuất** (chờ duyệt qua PR) · Liên quan ADR-0013/0014 (container hoá hub),
ADR-0039 của `companies/software-company` (deploy khách bằng compose; "systemd — chưa làm, cố ý"), ADR-0031 (chỉ Linux).

## Bối cảnh

Hub gồm bốn tiến trình dài hạn: gateway, orchestrator, console, keeper. Hiện chưa có cách nào giữ chúng sống:
gateway "chết là chết" (ADR-0002 của gateway), orchestrator do console bật (`--allow-engine`) **chết cùng console**,
và không có file service nào trong repo.

Đường container hoá (ADR-0013/0014) chưa từng chạy được trên Linux thật — ADR-0014 tự ghi chưa ai chạy
`up -d`. Rà mã ngày 2026-10-11 thấy 8 chỗ hỏng trên Docker Engine Linux, mỗi chỗ đủ làm hub vô dụng:

| # | Chỗ hỏng | Ở đâu |
|---|---|---|
| 1 | hub không tới được gateway: `host.docker.internal` trỏ IP bridge, gateway chỉ nghe `127.0.0.1` | `docker-compose.yml` `extra_hosts` |
| 2 | smoke sau deploy luôn đỏ: dò `127.0.0.1:<port>` là loopback **của container hub** | `company/deploy.py` |
| 3 | đường dẫn mount lệch host↔container khi gọi `docker` qua socket (docker-out-of-docker) | `ContainerSandbox` `-v {cwd}:/w` |
| 4 | `GH_TOKEN` trong env bị `clean_env` lọc; không mount `~/.config/gh` → `--deliver-pr` hỏng | `sandbox.py`, `github_pr.py` |
| 5 | không có `claude` CLI / Node trong image, không mount `~/.claude` | `Dockerfile` |
| 6 | container chạy root; repo khách và `var/` thành của root, git báo "dubious ownership" | `Dockerfile`, `entrypoint.sh` |
| 7 | keeper trong container không có git repo (`.dockerignore` loại `.git/`) | `console/engine.py` |
| 8 | `${HOME}/.gitconfig` thiếu thì Docker tạo thư mục root cùng tên | `docker-compose.yml` |

Gốc chung: hub cần **danh tính của người vận hành trên máy chủ** — đăng nhập `claude`/`gh`/Google, git credential,
repo khách, và `docker.sock`. Socket ấy tương đương root trên host, nên container hub không thêm lớp cách ly nào
(ADR-0039 quyết định 7 đã nói cùng ý cho daemon-client).

## Quyết định

1. **Hub chạy trực tiếp trên máy chủ dưới systemd user unit** của người vận hành — không root, không container.
   Bốn unit mẫu ở `deploy/systemd/`, cài bằng `scripts/systemd.sh install` (điền đường dẫn repo và `uv`, chép
   `hub.env` quyền 0600 một lần, không đè khi cài lại). `loginctl enable-linger` để chạy không cần phiên đăng nhập.
2. **Mỗi tiến trình một unit**, orchestrator tách khỏi console: `Restart=on-failure`, `KillSignal=SIGINT` (orchestrator
   trả lease, console xoá file token), `PYTHONUNBUFFERED=1` (log vào journald ngay). Console không `--allow-engine`
   (tránh hai orchestrator tranh lease) và chỉ nghe loopback; truy cập từ xa bằng SSH tunnel.
3. **Cấu hình theo máy** nằm ở `~/.config/x-agents/hub.env` (`ORCHESTRATOR_ARGS`, `CONSOLE_ARGS`, bí mật), ngoài repo.
4. **Docker giữ nguyên vai cho khách**: sandbox (`ContainerSandbox`) và deploy compose (ADR-0039) gọi Docker Engine của
   chính máy chủ — đúng đường đã chạy.
5. **Có cổng canh** (`platform/console/tests/test_trien_khai_systemd.py`): render bằng chính script, `systemd-analyze
   verify`, mọi cờ trong `ExecStart` phải có trong `--help` thật, cùng các bất biến của mục 2.

`Dockerfile`/`docker-compose.yml` của hub **không xoá** trong ADR này: tám chỗ hỏng ở trên là lý do không chọn chúng,
còn gỡ hay sửa là quyết định riêng.

## Phương án đã loại

- **Sửa container hub cho chạy được trên Linux.** Ưu: môi trường đóng băng, `docker compose up` một lệnh. Loại vì
  phải sửa đủ tám chỗ trên, trong đó (3) và (6) cần đồng bộ đường dẫn và uid host↔container cho mọi repo khách, (5)
  phải mang Node + `claude` + thư mục đăng nhập vào image — mỗi bước trả lại thứ systemd có sẵn, mà không thêm cách
  ly vì `docker.sock` đã cho container quyền root host.
- **System unit (root) thay vì user unit.** Ưu: không cần linger. Loại vì hub phải chạy bằng danh tính người vận
  hành (đăng nhập `claude`/`gh`, quyền file repo khách); chạy root lặp lại đúng lỗi (6).
- **supervisord / pm2.** Thêm một phụ thuộc làm đúng việc systemd đã có trên mọi Ubuntu, và không có journald.
- **Một unit chạy console `--allow-engine` bật orchestrator.** Ít unit hơn, nhưng orchestrator chết cùng console và
  không ai khởi động lại nó — đúng thứ ADR này sửa.

## Hệ quả

- Vận hành: `docs/TRIEN-KHAI-SYSTEMD.md`. Dừng khẩn thêm mức systemd ở `docs/TRUC-VA-DUNG-KHAN.md`.
- Cập nhật mã: orchestrator `--watch` tự `execv` khi mã đổi; gateway và console cần `restart`.
- Máy chủ không trình duyệt: đăng nhập gateway qua `--no-browser` + SSH tunnel cổng 51121.
- **Nhận biết nếu sai:** cần chạy nhiều hub trên một máy hoặc cô lập hub khỏi người vận hành → mở lại phương án
  container với tám chỗ hỏng ở trên làm danh sách việc.
