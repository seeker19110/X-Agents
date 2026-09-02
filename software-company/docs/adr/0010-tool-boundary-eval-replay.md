# ADR-0010: Tool có ranh giới tin cậy cho khối kỹ thuật, bằng chứng do code điền, eval ghi/phát lại, vòng học ước lượng

Trạng thái: Accepted · Ngày: 2026-09-02

## Bối cảnh
Đến ADR-0009 công ty có đủ 20 agent, orchestrator và bus bền vững, nhưng runner chỉ gọi model một lượt và ép JSON.
Prompt của khối kỹ thuật bắt agent "làm trên worktree, TDD, chạy lint + test trước khi publish PR" trong khi runtime
không cho agent chạm file nào; `workspace.py` (worktree + lint/test thật) không được nối vào đâu. Hệ quả: agent kỹ
thuật chỉ có thể *khai* `local_checks`, reviewer/QA review một PR không tồn tại dựa trên lời khai đó — hệ thống sinh
ra bằng chứng chất lượng giả, tệ hơn là không có tính năng.

Ba lỗ hổng đi kèm: (1) mở tool cho model đồng nghĩa mở cửa cho đầu ra không tin cậy điều khiển shell nếu không có
ranh giới; (2) eval cần model thật nên CI không bao giờ chạy, quy tắc "đổi prompt phải có eval" (ADR-0004) không
được máy cưỡng chế; (3) bài học estimate-vs-actual được ghi vào `knowledge` nhưng không ai đọc lại — vòng học hở.

## Quyết định
1. **Tool là bảng tên cố định, không có shell** (`tools.py`). Model chỉ chọn trong `read_file`, `write_file`,
   `list_files`, `search`, `run`; `run` chỉ nhận tên trong allowlist (`lint`, `test`, `git_status`, `git_diff`) với
   argv do code ghép. Mọi đường dẫn bị khoá trong worktree của ticket (không `..`, không tuyệt đối, không `.git/`,
   không file bí mật theo mẫu `.env`, `*.pem`, `*secret*`…); env cho lệnh con bị lọc mọi biến `*_API_KEY|TOKEN|SECRET|
   PASSWORD`; đầu ra cắt ở 6 000 ký tự. Lỗi tool trả về cho model dưới dạng chuỗi để nó tự sửa; không ném ra ngoài.
2. **Tool-use trung lập provider** (`llm.py`): `ModelClient.complete` nhận thêm `tools` (ToolSpec) và `messages`
   (hội thoại trung lập user/assistant/tool). Adapter Anthropic (tool_use/tool_result block), OpenAI-compatible
   (function calling) và Fake (`tool_handler`) tự chuyển đổi. Runner chạy vòng lặp model ↔ tool (`generate(tools=…)`)
   tới khi model trả lời cuối, hết `max_turns` (mặc định 25) hoặc vượt `budget` token — vượt thì audit
   `budget_exhausted` và dừng ngay trong vòng, không đợi supervisor cắt sau.
3. **Bằng chứng của PR do code điền, không phải model** (`runner.generate_in_workspace`). Sau vòng tool: worktree không
   đổi → `invalid_output` (không có PR rỗng); có đổi → chạy `ruff` + `pytest` thật, commit, và ghi đè `branch`, `pr_ref`
   (commit), `local_checks` (kèm `verified_by: workspace`), `impact.files`. Model có khai gì ở các trường này cũng bị
   thay; `coverage` không đo được thì không có. Reviewer/security nhận `diff` và `changed_files` thật trong đầu vào;
   QA nhận thêm tool chỉ đọc (`read_file`, `search`, `run test`) để tự chạy test.
4. **Không có repo thì không có bằng chứng**: orchestrator chạy không `--repo` vẫn đi hết luồng (mô phỏng), nhưng
   `local_checks` của PR bị thay bằng `{"unverified": true}` và audit `local_checks.unverified`; `sprint_report`
   đếm `prs_unverified`. Lời tự khai của model không bao giờ đóng vai bằng chứng.
5. **Eval ghi / phát lại** (`evals.py`): `--record` chạy model thật và lưu `evals/recordings/<agent>.json` khoá bằng
   hash(system prompt + user message); `--replay` chạy từ bản ghi, CI dùng (`eval-replay` trong `quality`). Đổi prompt,
   skill hay ca eval → hash đổi → bản ghi lệch → test `test_committed_recordings_match_current_prompts` và job CI đỏ
   cho tới khi ghi lại bằng model thật và commit. Đó là cơ chế cưỡng chế của ADR-0004. Agent chưa có bản ghi được SKIP
   (không chặn), `--strict` để bắt buộc.
6. **Vòng học đóng lại**: `Supervisor.calibration()` đọc mọi bài học từ `shared-context` namespace `knowledge` (bền vững
   qua bus, không chỉ bộ nhớ) → median(actual/estimate) theo assignee; orchestrator đưa bảng này vào đầu vào của
   delivery-lead mỗi lần lập kế hoạch (`estimate_calibration`). `sprint_report` thêm `rework_rate`,
   `review_catch_rate`, `prs_unverified`, `calibration`. Kế hoạch có `depends_on` vòng bị từ chối ở bước lập kế hoạch
   (trước gate), không đợi tới dispatch.

## Hệ quả
- `python -m company.orchestrator run --repo <path> [--base main]` là chế độ "làm thật"; không có `--repo` là mô phỏng
  và PR được dán nhãn chưa xác minh. Worktree nằm ở `<repo>/.worktrees/<ticket>`, branch `ticket/<id>`.
- Prompt của khối kỹ thuật không đổi (golden giữ nguyên): mô tả tool được runner ghép vào user message.
- Chưa có: merge branch ticket vào nhánh tích hợp (release-engineer vẫn mô phỏng deploy), nên ticket phụ thuộc rẽ từ
  `base` chứ chưa thấy code của ticket trước; tool cho khối nghiên cứu đọc codebase khách (cùng `WorkspaceTools`
  chỉ đọc, chưa nối route); sandbox tiến trình (container) cho `run` — hiện chỉ có allowlist + lọc env.
- Bản ghi eval phải do người có model thật tạo; repo chưa có bản ghi nào cho tới khi chạy `make eval-record`.
