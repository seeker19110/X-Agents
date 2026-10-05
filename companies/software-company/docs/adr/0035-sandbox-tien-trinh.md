# ADR-0035: Sandbox tiến trình cho lệnh con

Trạng thái: chấp nhận · Ngày: 2026-09-06 · Mục K2 của `docs/DAC-TA-TRIEN-KHAI-KICH-BAN-B.md` · Liên quan:
ADR-0013 (stack), ADR-0023/0024 (CLI/MCP tool), ADR-0029 (smoke do orchestrator chạy), ADR-0033 (DoD sản phẩm
chạy được), `SECURITY.md`

## Bối cảnh

Công ty chạy lệnh con ở nhiều chỗ: `tools.py` (`WorkspaceTools.run`, allowlist argv của model), `workspace.py`
(`TicketWorkspace._run` — lint/test theo stack của khách, và `_git`), `smoke.py` (`Popen` lệnh khởi động ứng
dụng), `Studio-creators` (`CommandTTS`, `ffmpeg`, `qc`). Tất cả đều là **mã của khách hoặc lệnh do model viết ra**
chạy bằng quyền người vận hành.

Ba điểm đau cụ thể:

1. `run_smoke` chạy `rt.command` lấy từ spec ứng dụng — chuỗi do model sinh, không có allowlist argv như `tools.py`.
   ADR-0033 làm smoke thành điều kiện DoD nên lệnh này chạy ở **mọi** ticket, không phải trường hợp hiếm.
2. `pytest` / `npm test` / `./gradlew` của repo khách thấy `HOME` (`~/.ssh`, `~/.claude`), thấy mạng, không có
   hạn mức pid/cpu/ram.
3. `SECURITY.md` đã tự nhận đúng giới hạn này bằng chữ: "sandbox là *đường dẫn + env*, không phải *tiến trình*".
   Nhận là tốt, nhưng nhận rồi để nguyên nhiều tháng thì chỉ là chú thích cho một lỗ hổng đã biết.

`clean_env()` (lọc `SECRET_ENV`) và `core.hooksPath=/dev/null` giải quyết được rò bí mật và hook, không giải
quyết được việc mã khách đọc file ngoài worktree.

## Quyết định

1. **Một giao diện `Sandbox`** trong `company/sandbox.py`: `RunSpec` (argv, cwd, env, timeout, `network=False`,
   `port`, `max_output`) → `Result` (exit_code, stdout, stderr, timed_out, **sandbox**), cộng `spawn` trả `Handle`
   (`poll`/`kill`/`stderr_tail`) cho `smoke.py` vốn cần tiến trình sống trong lúc probe HTTP.
2. **Hai backend.** `SubprocessSandbox` gói **đúng hành vi hiện có** (cùng cắt output, cùng timeout, cùng
   `clean_env`) — mục tiêu là không đổi hành vi ở bước gói. `ContainerSandbox` chạy
   `docker|podman run --rm --pids-limit 256 --cpus … --memory … -u uid:gid -v <cwd>:/w:rw -w /w --env-file /dev/stdin`,
   `--network none` mặc định và `--network bridge -p 127.0.0.1:<port>:<port>` khi `spec.network` (smoke vẫn probe
   được `127.0.0.1`). Env đi qua `--env-file /dev/stdin` (stdin) chứ không phải `-e`: giá trị không lộ trong `ps`.
3. **Chế độ `auto`, nhưng fail-closed.** Thứ tự: `COMPANY_SANDBOX` env → `cfg.sandbox` → `"auto"`. `auto` dùng
   container nếu tìm thấy runtime trên PATH. **ADR gốc 0023 (Accepted 2026-10-05) sửa quy tắc thiếu runtime:**
   cả `auto` lẫn `container` đều ném `SandboxError`; chỉ `subprocess` khai tường minh mới chạy ngoài container.
   Cách này ngăn một hệ bảo vệ tự hạ cấp trong im lặng.
4. **Git ở lại subprocess.** Ba lý do: argv của git là hard-code (model không viết được), hook của khách đã bị vô
   hiệu bằng `core.hooksPath`, và `deliver --push` cần credential helper của chính người vận hành — thứ không nên
   và không thể mang vào container. Ranh giới này ghi rõ để lần sau không ai "gói nốt cho đều".
5. **Env lọc lại tại sandbox.** `sanitize_env` chạy `SECRET_ENV` một lần nữa ngay trong `sandbox.py` dù nơi gọi đã
   `clean_env()`: sandbox là chỗ cuối cùng biến môi trường đi qua, không dựa vào kỷ luật của nơi gọi.
6. **Windows không có `os.getuid`.** Bỏ cờ `-u`, và tên sandbox báo cáo là `container:<image>:no-uid` — audit phải
   thấy được rằng lần chạy đó **không** hạ quyền, thay vì trông y hệt lần chạy có hạ quyền.

## Hệ quả

- `Result.sandbox` thành một trường bằng chứng: `local_checks.sandbox`, `smoke.sandbox`, `calls[].sandbox` trong
  audit sẽ nói lần chạy đó được cô lập tới mức nào (PR K2.2).
- Console đọc audit `sandbox.mode` và bằng chứng chạy mã khách để cảnh báo khi có `subprocess` (ADR gốc 0023).
  Máy dev không có Docker vẫn chạy được khi khai `COMPANY_SANDBOX=subprocess` tường minh và chấp nhận giới hạn gate.
- Image mặc định `python:3.12-slim` chỉ đúng cho repo Python; repo stack khác phải khai `sandbox_image`. Đây là
  giới hạn đã biết, không phải bug: chọn image là quyết định của người vận hành, công ty không đoán hộ.
- Ba trường cấu hình mới (`sandbox`, `sandbox_image`, `sandbox_runtime`) + ba biến môi trường tương ứng.
- Studio dùng lại module này (K2.3, bản copy tạm cho tới khi `xagents-core` ra đời ở K3).
- `SECURITY.md` sẽ sửa đoạn tự nhận nói trên khi K2.2 nối xong — **không sửa trước**, vì trước K2.2 câu đó vẫn
  đúng: module tồn tại nhưng chưa có nơi gọi.

## Liên quan

ADR-0029 (smoke do orchestrator chạy — nguồn của lệnh không allowlist), ADR-0033 (smoke thành DoD nên rủi ro
thành thường trực), `SECURITY.md` §"Lệnh con của repo khách", `docs/DAC-TA-TRIEN-KHAI-KICH-BAN-B.md` mục K2.
