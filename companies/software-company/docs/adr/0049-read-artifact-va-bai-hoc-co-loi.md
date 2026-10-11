# ADR-0049: Tool `read_artifact` đọc đủ artifact bị cắt; bài học `knowledge` mang lời người

Ngày: 2026-10-10 · Trạng thái: chấp nhận · Sửa câu sai của ADR-0020 §1; nối ADR-0012 (cắt ngữ cảnh có nhãn),
ADR-0048 (bài học tại mốc merge); giữ ADR gốc 0003/0004 (không RAG, không vector).

## Bối cảnh

1. **Agent không đọc được phần artifact bị cắt.** ADR-0020 §1 viết "agent có tool đọc repo vẫn mở được tệp artifact
   qua `path`". Code nói ngược lại: nhãn cắt của `fit` trỏ đường dẫn tuyệt đối `<db>.artifacts/<project>/<ns>/latest.<ext>`
   (`runner._context`), còn `WorkspaceTools._path` từ chối mọi đường tuyệt đối và mọi đường thoát worktree — đúng
   ranh giới ADR-0010, không được nới. Đo trên bus thật: `context_trimmed` 692 lần (`docs/reports/2026-09-27-audit.md`
   ở gốc repo); pha spec đọc PRD cắt 48→35 KB, mất mục tiêu chí nghiệm thu (`docs/sessions/2026-09-22.md`).
2. **Bài học chỉ mang số.** `_record_lesson` ghi `estimate/actual/ratio/retry/risk_tags` lên `knowledge`; chẩn đoán
   của người (`Task.human_hint`, từ gate escalation) chỉ vào `Supervisor.knowledge` trong RAM — không ai đọc, mất khi
   restart. `related_lessons` (ADR-0048) nói ticket trước tốn bao nhiêu, không nói người đã dặn gì.

## Quyết định

1. **Tool `read_artifact(namespace, section=None)`** (`tools.ArtifactTools`). Agent chỉ đưa **tên** namespace; dự án
   do code chọn (`project_of` của lượt), nội dung lấy từ `Blackboard.content` — bản mới nhất, cùng nguồn với file
   mirror, không có đường dẫn nào để agent dựng. Phạm vi = `AgentSpec.reads_full` (ADR-0020), trừ namespace toàn công
   ty (`knowledge` — runner đã bỏ bản thô, ADR-0048). Ngoài phạm vi → `ToolError`, model đọc được lý do.
2. `section` khớp tiêu đề `## …` không phân biệt hoa thường, trả đúng mục tới tiêu đề `##` kế; không có mục → lỗi
   liệt kê tiêu đề có sẵn. Không `section` mà artifact dài hơn `MAX_OUTPUT` → dòng đầu nói danh sách mục để đọc tiếp
   (`ToolBox` vẫn cắt ở `MAX_OUTPUT` như mọi tool). Không thêm `start/end`: chưa có ca nào cần.
3. **Gắn một chỗ:** `AgentRunner.generate` gắn tool vào mọi bảng tool của lượt (route `rw`, `tests`, `ro`, `research`
   đều đi qua đây) khi có blackboard. Lượt đó nhãn cắt đổi thành `tool read_artifact("<ns>")`; lượt không tool giữ
   nhãn cũ (eval không truyền tool nên prompt đã ghi không đổi — `evals --replay --strict` giữ xanh).
4. **Bài học có lời:** `lesson["hint"] = t.human_hint or ""` — lời người, không phải `Task.hint` mà delivery-lead ghi
   đè mỗi retry. Bản ghi đi qua bus nên `lessons()` → `lessons_for` → `related_lessons` có lời ngay cả sau restart;
   không dựng lại `Supervisor.knowledge` vì không đường đọc nào dùng nó.
5. **Không RAG/vector** (ADR gốc 0003, 0004): tra theo tên và tiêu đề mục là đủ cho blackboard N nhỏ.

## Hệ quả

- Agent có tool đọc được tiêu chí nghiệm thu bị cắt mà không nới ranh giới đường dẫn của `WorkspaceTools`.
- Bảng tool mọi route có tool dài thêm một mục; prompt lượt có tool đổi (tên tool trong `tools_prompt`, nhãn cắt).
- `related_lessons` dài thêm tối đa 5 × độ dài hint người viết.
- Còn biết: mode `cli` (ADR-0023) chạy tool riêng của CLI, không qua `ToolBox` — lượt đó không có `read_artifact`.

## Liên quan

ADR-0010 (ranh giới tool), ADR-0012 (cắt có nhãn), ADR-0020 (phạm vi đọc theo vai), ADR-0048 (bài học tại merge);
test `tests/test_read_artifact_adr0049.py`, `tests/test_tools_and_agentic.py::test_bai_hoc_mang_hint_cua_nguoi`.
