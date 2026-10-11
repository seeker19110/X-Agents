# ADR-0031: Repo chỉ chạy trên Linux — bỏ mọi nhánh mã, chân CI và tài liệu dành riêng cho Windows

Ngày: 2026-10-11 · Trạng thái: **đề xuất** (chờ duyệt qua PR) · Thay một phần ADR-0013 (hub "chạy trên WSL") và
ADR-0040 của `companies/software-company` (cầu `wsl.exe` làm runner mặc định của `COMPANY_DEPLOY=process`).

## Bối cảnh

Chủ repo chuyển toàn bộ vận hành sang Ubuntu (máy đo: Ubuntu 26.04 LTS, systemd 259, Docker 29.1.3) và sẽ triển
khai trên Linux. Trước PR này, hỗ trợ Windows nằm ở bốn lớp. Đo bằng `grep` trên `main` @ `129ca84`:

| Lớp | Đo được |
|---|---|
| Nhánh mã theo nền tảng trong `src/` | 19 chỗ rẽ (`sys.platform`/`os.name`/`getattr(os, …)`/`LOCALAPPDATA`) ở 6 module: `gateway/manage.py` (6: `tasklist`, `taskkill`, `CREATE_NEW_PROCESS_GROUP`), `gateway/auth.py` (1 + vòng thử lại `os.replace` vì Defender), `xagents_core/sqlite_bus.py` (4: `msvcrt`, `ctypes.windll`, `O_BINARY`), `xagents_core/sandbox.py` (5: `taskkill /T`, `start_new_session` ×2, env qua argv, `:no-uid`), `xagents_core/llm.py` (2: `ARGV_LIMIT` 30 000, dò `%LOCALAPPDATA%/…/codex.exe`), `company/mcp_bridge.py` (1: `SystemRoot`) |
| Mặc định chỉ đúng trên Windows | `company/deploy.py:57` `DEFAULT_RUNTIME_PROCESS = "wsl.exe --cd . bash"` — trên Ubuntu `COMPANY_DEPLOY=process` hỏng ngay ("không có trên PATH") nếu người vận hành quên đặt `COMPANY_DEPLOY_RUNTIME=bash` |
| CI | 7 chân `windows-latest` trong `ci.yml` (`unit`, `gateway-unit`, `console-unit`, `core-unit`, `keeper-unit`, `core-static`, `keeper-static`) cùng 5 chỗ `shell: bash`/`if: runner.os` chỉ để né lớp bọc `pwsh` |
| Công cụ, tài liệu | `build-and-test.ps1` (đã hỏng: `cd` vào `software-company/`, `gateway/`, `console/` ở gốc — không còn từ ADR-0011); mục "Thao tác trên Windows" của `CLAUDE.md`; hướng dẫn PowerShell ở `docs/HUONG-DAN-VAN-HANH.md`, `docs/TRUC-VA-DUNG-KHAN.md`, `README.md`, `CONTRIBUTING.md` |

Test chỉ để phủ các nhánh trên (giả `sys.platform`, giả `msvcrt`/`ctypes`/`os.name`) chiếm 24 ca — đo bằng số test
trước/sau PR này: gateway 312→303, core 684→676, company 2137→2133, console 830→827 — thêm 6 skip theo nền tảng. Mỗi nhánh Windows là một chỗ mã phải giữ đúng mà chủ repo không còn chạy — chi phí không có người
hưởng.

## Quyết định

1. **Linux là nền tảng duy nhất được hỗ trợ.** Mọi job CI chạy `ubuntu-latest`; ma trận chỉ còn phiên bản Python
   (3.11, 3.13).
2. **Gỡ mọi nhánh mã chỉ tồn tại cho Windows**, giữ nhánh POSIX làm đường duy nhất:
   - `gateway`: `/proc` (Linux) hoặc `ps` (macOS/BSD) để nhận daemon; `os.kill(SIGTERM)` để dừng;
     `start_new_session=True`; `chmod 0600` vô điều kiện; bỏ vòng thử lại `os.replace`.
   - `xagents_core`: `fcntl.flock` cho `Lease`, gỡ tên file lock khi còn giữ khoá (bỏ đường "đóng rồi xoá");
     `os.killpg` cho cây tiến trình; `ContainerSandbox` luôn `-u uid:gid`, tên không còn hậu tố `:no-uid`, env mặc
     định qua `/dev/stdin`; `ARGV_LIMIT = 120_000`; `find_codex_binary` chỉ tìm trên PATH.
   - `company`: `DEFAULT_RUNTIME_PROCESS = "bash"`; bỏ `mcp_bridge.platform_env()`.
3. **Giữ lại có chủ ý** (không phải hỗ trợ Windows, dù có chữ Windows):
   - `keeper/evidence.py` đọc lệnh của repo khách bằng `PureWindowsPath` (vd `.venv\Scripts\pytest.exe`) — đó là
     **dữ liệu** khách, không phải nền tảng hub chạy.
   - `console/server.py::_drain_body` — bảo vệ **trình duyệt** của người trực, có thể là máy Windows mở console qua
     SSH tunnel.
   - Phép kiểm `\` và `:` trong tên thư mục của `blackboard.py`, `BINARY_EXT` có `.exe`/`.dll` trong `tools.py` — rào
     dữ liệu, đúng trên mọi hệ.
   - Chú thích lịch sử giải thích vì sao một thiết kế còn hiệu lực ra đời trên Windows (bước đồng hồ ~15,6 ms ở
     `gates.py`/`observe.py`) — thiết kế vẫn đúng, chỉ nguồn gốc là Windows.
4. **Không viết lại lịch sử**: `CHANGELOG.md`, `docs/sessions/`, `docs/reports/`, `docs/archive/`, `docs/thi-hanh/`,
   bản ghi eval và ADR cũ giữ nguyên văn; ADR-0013 và ADR-0040 (công ty) chỉ thêm dòng trạng thái trỏ về đây.

## Phương án đã loại

- **Giữ mã Windows, chỉ bỏ chân CI.** Rẻ nhất trong PR này. Loại vì mã không có CI là mã mục: nhánh `msvcrt` hay
  `taskkill` sẽ sai dần mà không ai thấy, và `fail_under = 100` phải trông vào test giả nền tảng — đúng khuôn "xanh
  vì không đo cái thật" mà `TRAPS.md` §2 cấm.
- **Giữ Windows qua WSL** (hub trong WSL, như ADR-0013). Đó chính là Linux; giữ cầu `wsl.exe` và hướng dẫn PowerShell
  chỉ để phục vụ máy chủ Windows bọc ngoài là nợ cho một máy không còn dùng.
- **Gỡ luôn nhánh macOS (`ps`) để "chỉ Linux" tuyệt đối.** Loại: nhánh `ps` là POSIX, không có chi phí riêng, và máy
  phát triển macOS vẫn chạy được test mà không cần mã thêm.

## Hệ quả

- Chạy trên Windows native **không còn được hỗ trợ**: `fcntl` không có trên Windows nên `xagents_core.sqlite_bus`
  không import được — hỏng to và ngay, không âm thầm. Người dùng Windows chạy trong WSL2/Ubuntu.
- `ContainerSandbox` mất hậu tố tên `:no-uid` (POSIX luôn có `os.getuid`); audit cũ mang `:no-uid` vẫn đọc được,
  bản mới không sinh nữa.
- `COMPANY_DEPLOY=process` chạy được trên Ubuntu không cần đặt thêm biến; ai muốn chạy script từ gốc repo khách đặt
  `COMPANY_DEPLOY_RUNTIME="env -C . bash"`.
- CI ít hơn 7 job con mỗi PR.
- **Nhận biết nếu sai:** có người cần chạy hub trên Windows native → mở ADR mới, đừng thêm lại nhánh lẻ; cổng
  `test_cong_repo.py::test_skip_xfail_khong_vuot_tran` đếm skip, nên một skip theo nền tảng thêm lại sẽ lộ.
- Triển khai (Docker hay systemd trên Ubuntu) là quyết định riêng, không thuộc ADR này.
