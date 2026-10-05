# TRAPS.md — bẫy riêng của xagents-core

Bốn khuôn chung ở `../../TRAPS.md` §1 áp nguyên vẹn (mọi công ty dùng chung lõi này). Dưới đây là bẫy đã cắn
người ngay trong chính core — mỗi dòng có test hoặc đoạn code làm chốt chặn.

## Bẫy đã vá

| Bẫy | Đã xảy ra | Chốt chặn / lần sau |
|---|---|---|
| Đồng hồ Windows bước ~15,6ms làm 2 gate trùng khoá `once` | Hai gate cùng `subject_id` mở cách nhau <16ms có cùng `created_at` → khoá chống-trùng nuốt mất lần quá hạn thứ hai (đo 2026-09-09) | `GateRequest.seq` là bộ đếm tăng dần thay `created_at` để phân biệt thế hệ (`gates.py`) |
| `PersistentGate` tin `evidence.by` thay vì `env.actor` | Lỗ hổng "actor giả mạo qua evidence" bị vá 2 LẦN Ở 2 CHỖ KHÁC NHAU trước khi hai công ty hợp nhất về một `gate_cli.py` — cùng lỗ hổng, hai lần phát hiện độc lập | `trusted_decision` chỉ đọc `env.actor` (ACL producer lúc publish), không đọc trường tự khai trong payload |
| `RecordingClient` không chốt `prompt_version` đúng lúc | Sự cố 2026-09-05: ghi bản eval xong đổi prompt, bản ghi cũ vẫn coi là hợp lệ vì version chốt muộn | Chốt `prompt_version` lúc `__init__`; `save()` GỘP thay vì ghi đè (`evals.py`) |
| `QUOTA_PATTERNS` khớp không ranh giới từ | Studio production: chuỗi "insufficient"/"429" khớp nhầm "unlimited", "billingham", "4290" thành hết quota | Mẫu có ranh giới từ, đo chéo 23 câu thử giữa hai công ty trước khi gộp (`routing.py`) |
| Đọc "tạm thời" bằng chuỗi con trần trong thông điệp CLI | 2026-10-02: `claude -p`/`codex` soi `"rate"`, `"limit"`, `"usage"` — khớp "generate", "context limit" (prompt quá dài) và "Usage: codex exec" (sai cờ) → `TransientError`, backend nghỉ, event hoãn mãi; bốn chỗ còn bốn danh sách khác nhau | Một regex cụm có ranh giới từ `TRANSIENT_TEXT` cho cả bốn đường (`llm.py`; `tests/test_llm_clients.py` `VINH_VIEN`/`TAM_THOI`). Thêm mẫu: thêm cả ca vĩnh viễn chứa chữ ấy. `\b` coi `_` là chữ: `\bquota\b` bỏ sót `insufficient_quota`, `request_timeout` (bản chuỗi con trước đó vẫn khớp — hồi quy ngay trong bản vá, trợ lý review bắt) → ranh giới chữ cái `(?<![a-z])…(?![a-z])` cho từ hay nằm trong mã snake_case |
| Tool ném `OSError` giết cả lượt agent | 2026-10-02: `write_file` vào đường là thư mục → `IsADirectoryError` xuyên `ToolBox` (chỉ bắt ToolError/TypeError/ValueError) và runner company (chỉ bắt ToolError) — lời hứa 2 của khung bị phá | `ToolBox._call` bắt `OSError` → `lỗi: <Kiểu>: <strerror>` (không lộ đường tuyệt đối) (`tests/test_tools.py`) |
| Sandbox subprocess ném `FileNotFoundError` khi máy thiếu binary | 2026-10-02: stack node mà không có `npm` → `TicketWorkspace.lint/test` ném xuyên; backend container cùng ca thì trả 127 | `SubprocessSandbox.run` trả `Result(127, …)` nói lệnh nào thiếu (`tests/test_sandbox.py` `…thieu_binary…`) |
| `AnthropicClient` trả JSON cụt khi `stop_reason=max_tokens` | Cùng họ với `finish_reason=length` đã vá ở `OpenAICompatClient` nhưng nhánh Anthropic sót: runner báo "không phải JSON", người đọc sửa prompt | `LLMError` nói rõ hạn mức khi không có tool_use (`tests/test_llm_clients.py` `test_anthropic_het_han_muc…`). Sửa một client → rà cả bốn client |
| Bộ lọc injection lệch giữa hai công ty | K3.4: company bắt 8 mẫu mà studio (cũ) trượt, studio bắt 4 mẫu mà company trượt — mỗi bên tự viết mẫu riêng không đối chiếu | Gộp về một bảng mẫu chung ở `guard.py`, viết lại `vi-ignore` sau khi phát hiện CẢ HAI bản cũ đều trượt cùng 2 câu tấn công tiếng Việt |
| `Lease` chiếm lock cũ bằng đọc-rồi-ghi pid | Nợ từ K3.5c: hai orchestrator khởi động cùng lúc sau crash cùng đọc "pid chết", cùng ghi, cùng giữ một bus; tái hiện chắc chắn 10/10 vòng bằng hai tiến trình thật chờ nhau trong `_alive` (2026-10-04) | Khoá OS (`flock`/`msvcrt`) là chủ, pid chỉ để chẩn đoán; khoá xong kiểm `st_nlink` (bẫy gỡ tên: POSIX gỡ tên KHI CÒN khoá, Windows đóng rồi xoá); không dùng `lockf` (khoá theo tiến trình); khoá msvcrt là bắt buộc nên khoá một byte xa phần pid; Windows nhả khoá của tiến trình chết không tức thì. Nhánh nền tảng nào cũng phải có ca giả module (`msvcrt`/`fcntl`) vì chân Windows đo `--cov` 100% (`test_lease_hai_tien_trinh_dua_…`) |
| Chống lặp bằng cờ RAM sai sau mở lại bus | `Supervisor` (khuôn 2 `../../TRAPS.md`): cờ "đã cảnh báo" sống trong RAM, mở lại tiến trình là mất, cảnh báo lặp lại vô hạn | Trạng thái chống lặp phải đọc lại từ audit-log lúc `_rehydrate`, không chỉ khởi tạo rỗng |

## Bẫy biết trước (chưa cắn)

| Bẫy | Vì sao | Chốt chặn / lần sau |
|---|---|---|
| Hạ code về trước ADR-0022 sau khi journal đã có `task.reopened` | Code cũ không biết loại event thứ 7, nên `ExecutionEventKind("task.reopened")` ném `ValueError` ở mọi lần replay | Hệ đóng an toàn: company biến lỗi thành `quality.sync_error`, R6 thành `quality_error`. Đã chạy N5 thì chỉ tiến, không lùi; muốn lùi phải bỏ run đó |

## Cách rà khi có lỗi mới

Cùng khuôn 4 lỗi ở `../../TRAPS.md` §1, thêm câu riêng cho lõi: *"nếu sửa ở đây, cả hai công ty (software-company
VÀ keeper) có cùng cần hành vi mới không?"* — core không biết tên công ty nào (ADR-0001 §2); một nhu cầu chỉ một
bên cần thuộc về lớp con của công ty đó, không thuộc đây. Sửa `routing.py`/`guard.py` xong: chạy lại test của cả
hai công ty (không chỉ `xagents-core/tests/`), vì cả hai import cùng một bản.
