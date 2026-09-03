# ADR-0023: Chế độ tool CLI cho provider `claude-code`

## Bối cảnh
ADR-0019 đưa `claude-code` vào như backend không cần key, nhưng ghi rõ: không hỗ trợ tool-use, nên `RoutingClient`
bỏ qua nó khi request có `tools`. Hệ quả trên thực tế nặng hơn mô tả:

- `generate_in_workspace` (khối kỹ thuật) luôn cấp `WorkspaceTools(allow_write=True)`, và worktree không đổi sau vòng
  tool thì PR bị chấm `invalid_output`. Không có tool = không ra được PR.
- `_read_only_tools` cấp toolbox cho reviewer/QA khi có repo.

Nên cấu hình "toàn bộ công ty chạy bằng gói Claude" (`COMPANY_LLM_BACKENDS=claude-sub`) không chạy được: 6 agent
engineering + reviewer/qa/security không còn backend nào, `RoutingClient` ném "không backend nào hỗ trợ tool-use".
Lý do kỹ thuật thì hẹp: `claude -p` không trả `tool_calls` ra cho lớp ngoài — nhưng CLI **tự chạy tool được**.

## Quyết định
1. **Cờ `cli_tools` cho backend `claude-code`.** Bật thì `complete(tools=..., workdir=...)` không báo lỗi nữa mà chạy
   `claude -p` với `cwd` = worktree của ticket và cho CLI tự cầm tool của nó. Trả về câu trả lời cuối, `tool_calls`
   rỗng — với `runner._tool_loop` đó là một lượt rồi thoát, nhưng file trong worktree đã bị sửa thật.
2. **`workdir` là tham số mới của `ModelClient.complete`.** `ToolBox` mang thêm `root` (do `WorkspaceTools.add_to` điền);
   `runner._complete` truyền `tools.root` xuống. Provider khác nhận và bỏ qua.
3. **Ánh xạ tool công ty → tool CLI**, không mở rộng hơn bảng đang có: `read_file`→Read, `list_files`→Glob,
   `search`→Grep, `write_file`→Edit+Write, `run`→Bash **chỉ khi** cấu hình có `cli_bash`. Toolbox chỉ đọc
   (reviewer/QA) do đó không bao giờ nhận Edit/Write/Bash.
4. **Hàng rào thay cho `tools.py`.** Ranh giới tin cậy của ADR-0010 (argv do code ghép, allowlist lệnh, chặn file bí
   mật, khoá đường dẫn trong worktree) không còn áp được khi CLI tự gọi tool. Bù bằng bốn thứ, tất cả ở argv:
   - `--restricted`: khoá file tool trong cwd, bỏ tool chạy lệnh trừ khi `--tools` gọi tên, và **bỏ qua settings
     user/project của máy** (agent không thừa hưởng quyền rộng của người dùng).
   - `--tools` hẹp theo mục 3.
   - `--allowed-tools "Bash(<mẫu>)"` theo `cli_bash`; lệnh ngoài mẫu bị hệ permission từ chối.
   - `--settings` mang deny-list file bí mật (`.env`, `*.pem`, `llm.yaml`, `.aws/**`...) — `--restricted` khoá được
     phạm vi thư mục nhưng file bí mật NẰM TRONG worktree thì vẫn đọc được nếu không deny.
   - `--strict-mcp-config`: không kéo MCP server nào của người dùng vào phiên.
5. **Thiếu `workdir` là lỗi cứng**, không âm thầm chạy ở thư mục hiện hành.
6. `supports_tools` của backend `claude-code` mặc định theo `cli_tools` (vẫn ghi đè được bằng khoá cùng tên).

## Hệ quả
- Chạy được cả 20 agent, kể cả khối kỹ thuật, bằng gói Claude Pro/Max trên máy — không API key, không gateway.
- Bằng chứng vẫn thật: `ws.dirty()`, lint/test và diff trong `generate_in_workspace` do CODE chấm, không phải model
  khai. Blackboard, gate, ngân sách, worktree của orchestrator không đổi.
- **Đánh đổi phải biết**: hàng rào tool yếu hơn một bậc so với `tools.py` — nó là hệ permission của CLI chứ không phải
  argv do ta ghép. Với repo khách không tin cậy, giữ `cli_tools: false` và đi backend API.
- Ngân sách token mỗi lượt tool không còn đếm được từng lượt: cả phiên CLI về như một `Completion`, `budget_tokens_per_task`
  chỉ chặn được SAU khi phiên kết thúc chứ không cắt giữa chừng. `cli_max_turns` là cái hãm thay thế.
- Mặc định vẫn `cli_tools: false`: hành vi cũ không đổi cho mọi cấu hình đang chạy.
