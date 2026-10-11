# Đối chiếu DeerFlow 2.0 (ByteDance) với X-Agents — 2026-10-11

Yêu cầu: *"nghiên cứu repo này giúp ích được gì"* (ảnh README `bytedance/deer-flow` 2.0, "#1 GitHub Trending
28-02-2026"), rồi *"ok triển khai, những cái tốt ghi nhận lại sau này lấy sau"*. Làm theo `docs/PROMPT-SHEET.md` §H: ba cột
**đã có và sâu hơn / đã có nhưng nông hơn / chưa có**; "chưa có" chỉ lấy khi chỉ ra sự cố đã xảy ra ở đây, không có thì
"chưa cần" kèm điều kiện quay lại. Không cài gì, không vendor gì.

Nguồn đã đọc (WebFetch, không clone, không chạy code nào của họ): README chính (273k ký tự, đọc ba đoạn), cây
`backend/packages/harness/deerflow/`, `backend/docs/summarization.md`, `GUARDRAILS.md`, `LOOP_DETECTION.md`,
`task_tool_improvements.md`, danh sách `skills/public`, một bài review độc lập (andrew.ooo, 2026-10-10). Số sao
83,6k (2026-10-10), MIT, bản 2.1.0 (2026-09-24). Mọi câu về X-Agents đối chiếu lại với mã ở đây bằng `file:dòng`.

## 1. DeerFlow là gì — và vì sao phần lớn không phải cơ chế thiếu

Harness cho **một siêu agent trò chuyện**: `lead_agent` (LLM) nhận yêu cầu, giao việc cho sub-agent qua tool `task`
(`context_mode isolated|snapshot`), chạy trong sandbox local/Docker/K8s, bộ nhớ dài hạn DeerMem, 23 skill công khai
(deep-research, ppt/podcast/video-generation, skill-creator…), kênh Telegram/Slack/Feishu/WeChat, TUI, lịch chạy,
RAGFlow. Bản 2.0 viết lại từ đầu trên LangGraph/LangChain; "Code-as-Prompt" là tên họ đặt cho điều repo này làm từ
ADR-0004 (prompt là code có version). Bài review ghi điểm yếu: gánh bảo mật đặt lên người vận hành ("Gateway admin =
code execution"), nhiều dịch vụ (8 vCPU/16 GB tối thiểu), chạy dài "vẫn hay đi lạc".

Khác biệt gốc: ở DeerFlow **manager là LLM**; ở đây manager là code (`co/orchestrator.py` + `co/orch/routes.py`,
`co/delivery.py`), human gate `spec → release → acceptance` (`core/gates.py`), bus có schema + ACL (`co/core.py:34-57`),
prompt có golden + eval (`CONTRIBUTING.md` §3). Đó là lựa chọn đã ghi ở `ARCHITECTURE.md` §"Thuật ngữ ngành ↔ cơ chế ở
repo", không phải thiếu sót. Nên kênh IM, chat archive, Projects, RAGFlow, TUI, skill nội dung là **sản phẩm khác**.

## 2. Cột 1 — đã có ở đây và sâu hơn (không lấy)

| DeerFlow | X-Agents | Ở đâu |
|---|---|---|
| Lead agent LLM điều phối, sub-agent cách ly context | Orchestrator code; route cấp tool/context theo pha; `/thi-hanh` điều phối subagent | `co/orch/routes.py:157-204`, `docs/KHUON-THI-HANH.md` |
| Human-in-the-loop = `auto_approve_permissions`, card duyệt mạng | 3 gate + escalation, checklist, reviewer ký Ed25519, sàn tự duyệt có điều kiện | `co/gates/checklists.md`, `co/gate_reviewer.py`, ADR công ty 0043 |
| Checkpoint/replay LangGraph, `batch_task` bền trong SQL | Bus SQLite append-only, `rehydrate`, test bất biến restart, `trace` | `co/orch/rehydrate.py`, `tests/test_orch_state_rehydrate.py` |
| SkillScan khi cài skill (CRITICAL chặn, LLM quét vòng hai), RBAC tool theo vai | `assetscan` + waiver, `assetbudget`, vendor lock sha256, ACL topic/namespace, sandbox fail-closed | `co/assetscan.py`, `docs/integrations/*.lock.json`, `core/sandbox.py` |
| Token budget cộng cả sub-agent | Ngân sách token/tiền theo ticket + dự án, 80 %/100 %, `budget.extended` do người | `co/supervisor.py:143-186` |
| Memory tự trích (DeerMem), SOUL.md tự sửa, prompt overlay prepend/append | **Cố ý không**: bài học `knowledge` ghi lời người; prompt chỉ đổi qua 7 bước có eval | ADR gốc 0004; `AGENTS.md` luật cấm 8 |

## 3. Cột 2 — đã có nhưng nông hơn: ĐÃ LẤY trong thay đổi này

**Blocker có kiểu.** Session goal của DeerFlow chấm mỗi run bằng một evaluator và trả **kiểu** blocker
(`missing_evidence | needs_user_input | run_failed | external_wait | goal_not_met_yet`), trần 8 lần tiếp tục, dừng sau
2 lần "không tiến" giống hệt. Phần evaluator-model **không lấy** (model chấm model là lời khai, luật cấm 8). Phần
**kiểu** thì lấy, vì nó trả lời đúng câu hỏi `TRAPS.md` đã để ngỏ sau CAMPUS-UNI 2026-09-24: *"bộ đếm retry này đang đếm
lỗi của agent, hay đếm trục trặc của hạ tầng/trần?"*. Mỗi lần trả lời câu đó repo thêm một bộ đếm riêng: năm bộ đếm,
bảy audit, hai hằng ở `routes.py` (bảng ở ADR công ty 0052 §Bối cảnh). `ticket.blocked` chỉ nói `retry=3`.

Đã làm (ADR-0052): `co/stop_kind.py` — `STOP_KINDS`, `STOP_POLICY` (kiểu nào đốt retry, miễn mấy lần, rồi làm gì),
`classify_error` từ `TransientError`/`LLMError.head`; hai hằng cũ đọc từ bảng; `stop_kind` vào sáu audit dừng;
`DeliveryLead.stops` đếm retry theo kiểu, `ticket.blocked` và CR `REPLAN-*` mang `stops`; hồ sơ gate escalation hiện
`stops`. Không đổi một số trần nào. Chi tiết và phương án đã loại: `companies/software-company/docs/adr/0052-*.md`.

## 4. Cột 3 — chưa có, hoặc nông hơn nhưng chưa có sự cố → "lấy sau", kèm điều kiện quay lại

Ghi theo lệnh *"những cái tốt ghi nhận lại sau này lấy sau"*. Mỗi mục có **lệnh đo** để biết khi nào tới lúc.

| # | DeerFlow | X-Agents hiện có | Điều kiện quay lại | Đo bằng |
|---|---|---|---|---|
| 1 | Compaction LLM: trigger `tokens`/`messages`/`fraction` (OR), `keep` 20 message, **không tách cặp AI/Tool**, summary ở `<durable_context_data>` quyền thấp, cache theo prompt | `_prune` giữ 3 lượt tool gần nhất rồi băm (`core/context.py:201`), `context.fit`, `max_turns=25`; sự cố PRD cắt 692 lần đã đóng bằng `read_artifact` (ib1) | Một lượt tool của ticket chạm `max_input_chars` **sau** khi đã `_prune` | đếm audit `token_estimate` có `trimmed_payload > 0` trong lượt có `tools_used.turns ≥ 10` |
| 2 | Loop detection theo băm tool call trong một lượt: cảnh báo rồi chặn cứng, đếm theo `(thread, run)` | Supervisor "cùng lỗi lặp ≥ 2" cấp **event** (`co/supervisor.py:138`); trong `_tool_loop` chỉ có `max_turns` | `tools_trace` cho thấy cùng `(tool, args)` ≥ 3 lần trong một lượt ở ≥ 2 ticket | truy vấn bus: nhóm `tools_trace` theo lượt, đếm hash `(name, args)` trùng |
| 3 | `tool_search`/`describe_skill`: nạp skill muộn, top-5 theo từ khoá | Nạp skill theo pha, tất định (ADR-0037); trần `assetbudget` 50 % | Một vai chạm trần `assetbudget` mà không cắt được skill nào theo pha | `make assetbudget` |
| 4 | Sandbox egress `allowlist` với card duyệt một lần; private/loopback/metadata **không duyệt được** | Sandbox mạng tắt hẳn (fail-closed) | Ticket thật cần tải phụ thuộc trong sandbox (`uv sync` offline hỏng) | audit `pr.rejected_local_checks` có `No matching distribution`/`ConnectionError` |
| 5 | Durable `batch_task`: trần `total/live/running` riêng, retry budget, phục hồi restart | `run(workers)` song song theo key (ADR-0012) + rehydrate | Một dự án > 20 ticket độc lập cùng lúc làm `status` không đọc nổi | `metrics` `queue` và số worker |
| 6 | Session goal evaluator (model) + "dừng sau 2 lần không tiến giống hệt" | `/product-goal` tiêu chí Ready/Done/Complete do người + code chấm | **Không lấy** chừng nào luật cấm 8 còn: tiêu chí xong phải là code hoặc người | — |
| 7 | Gộp bộ đếm `turn_continuations` + `conflict_retries` thành một `stop_counts[tid][kind]` (bước tiếp của ADR-0052) | Hai bộ đếm riêng, cùng khuôn, 22 tham chiếu test | Xuất hiện kiểu dừng thứ ba có `free_stops` | đọc bảng `STOP_POLICY` |

## 5. Thay đổi trong PR này

ADR công ty 0052; `co/stop_kind.py`; `co/orch/{routes,error_flow,scheduler,worktree_flow}.py`, `co/delivery.py`,
`co/gate_brief.py` đọc bảng/ghi `stop_kind`; `tests/test_stop_kind_adr0052.py` (15 ca, đỏ trước: `ModuleNotFoundError`);
golden `gate_brief/escalation.json` đổi một trường; `CODEMAP.md`, `TRAPS.md` (dòng "Tính hết lượt là làm sai" trỏ ADR);
hồ sơ `docs/thi-hanh/df1.md`.
