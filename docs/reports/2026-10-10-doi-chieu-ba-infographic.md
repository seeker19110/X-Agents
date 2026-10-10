# Đối chiếu ba infographic về AI agent với repo — 2026-10-10

Yêu cầu của chủ dự án: *"nghiên cứu những thứ này, cải tiến, cải tổ, thay đổi dự án trở nên tốt hơn bằng hết khả năng"*,
kèm ba ảnh: (1) "24 AI Terms Everyone Should Know in 2026" (Chief AI Leader), (2) "How real engineers use AI agents —
the 25 skills in Matt Pocock's .agents directory", (3) "AI Agents: 6 Must Know Definitions" (Chief AI Leader).

Làm theo `docs/PROMPT-SHEET.md` §H: đọc **nguồn thật** chứ không tin ảnh, đối chiếu với thứ repo ĐÃ CÓ (code, ADR,
TRAPS), kết luận theo ba cột; "chưa có" chỉ lấy khi nó giải một sự cố đã xảy ra ở đây. Kế hoạch thi hành phần đáng
làm: `docs/thi-hanh/ib1.md`. Bảng cầu thuật ngữ đầy đủ (24 + 6 dòng, `file:dòng`): `ARCHITECTURE.md` §"Thuật ngữ
ngành ↔ cơ chế ở repo". Báo cáo này **chỉ kết luận**; mỗi mục "lấy" là một PR riêng, test đỏ trước.

## 1. Nguồn đã đọc

| Nguồn | Bản | Phần đọc |
|---|---|---|
| Ảnh 1, 3 | ảnh tải lên, không có nguồn gốc kiểm được | toàn bộ chữ trên ảnh |
| `mattpocock/skills` | clone nông `49dd158` (2026-10-09), MIT, `package.json` 1.3.1 | `AGENTS.md`, `SCOPE.md`, `.out-of-scope/*`, `CHANGELOG.md`, 38 `SKILL.md` (27 ở `engineering/`+`productivity/`), tệp phụ của ứng viên |
| Repo này | `main@8b2b597` (#416) | ba khảo sát `Explore` chỉ đọc theo mảng (retrieval/memory · action/agent/production · skill/vendor), mỗi khẳng định kèm `file:dòng`; hai điểm quyết định tự kiểm lại tay |

Ảnh 2 lệch nguồn thật ở bốn chỗ: ghi `resolving-merge-conflicts` (upstream **đã gỡ**, #1120: "the agent works through
an in-progress merge or rebase conflict without a dedicated skill"); không ghi `retro`, `pr`, `implement-spec` (có thật,
promoted); "218k+ stars / 900k+ installs" không kiểm được và không ảnh hưởng kết luận. Mọi skill Pocock mang
`agents/openai.yaml` (metadata Codex) — không phải `.md`, cơ chế vendor ECC hiện từ chối.

## 2. Ảnh 1 + 3: 24 thuật ngữ và 6 định nghĩa

### 2a. Cột 1 — đã có, thường chặt hơn ảnh mô tả (không lấy gì)

| Thuật ngữ | Ở repo | Vì sao không cần thêm |
|---|---|---|
| LLM, Prompt, Tokens | client theo provider + routing; "prompt là code" (golden, eval-record); ngân sách token đầu ra theo ticket | `core/llm.py`, `core/registry.py:106-122`, `co/supervisor.py:143-186` |
| Context window, Chunking | `context.fit` water-filling, `max_input_chars` theo vai (ADR-0020), `cut_prd_sections` theo mục có ưu tiên (ADR gốc 0029), `_prune` (ADR gốc 0007) | `core/context.py:140-240`, `co/prd_context.py:9-49` |
| Tool calling, Function calling | `ToolBox`/`ToolSpec` trung lập provider, vòng tool, adapter Anthropic/OpenAI/Gemini, quyền theo route, sandbox fail-closed | `core/tools.py:47-52`, `co/runner.py:309-434`, `core/sandbox.py:81` |
| AI Agent, Agentic workflow, Multi-agent | `AgentSpec`/`AgentRunner`; máy trạng thái `Orchestrator`+`ROUTES` (ADR công ty 0034); **manager là code**, không phải agent LLM; bus có JSON Schema + ACL | `co/orchestrator.py:366-431`, `core/bus.py:49,74-75` |
| Agentic AI | tự chủ **có trần**: human gate, ngân sách, sandbox — ảnh mô tả "acts more autonomously", repo chọn ngược có chủ đích (`ARCHITECTURE.md` §"Ranh giới tin cậy") | `core/gates.py:64-108` |
| Planner, Evaluator | `product[plan]` + `_check_plan` bác theo luật; gate + checklist, `evals --strict`, reviewer ký Ed25519, `quality_floor` | `co/orch/guards.py:312-360`, `co/quality_floor.py:102-147` |
| Guardrails | injection guard, ACL, sandbox, ngân sách, `assetscan`/`assetbudget`, gitleaks, hook `.claude/hooks/` | `core/guard.py`, `co/assetscan.py` |
| MCP | repo **tự có** cầu MCP nội bộ (stdio JSON-RPC 2.0, `2025-06-18`) đưa tool công ty vào `claude -p`; `--restricted` không tắt nó (ADR gốc 0027 §4) | `co/mcp_bridge.py:38,161-210`, `co/llm.py:472-505` |
| Skills, Single-agent, Memory (ảnh 3) | 45 skill công ty theo `skills`/`skills_core`/`phases`; một ticket một agent mỗi pha; ba tầng nhớ (vòng tool / blackboard / bus + journal) | `core/registry.py:136-160`, `core/blackboard.py` |

### 2b. Cột 2 — đã có nhưng hở, có sự cố ghi lại: NÊN LẤY (→ `ib1`)

| Thuật ngữ | Lỗ hổng đo được | Sự cố | Mã `ib1` |
|---|---|---|---|
| Agentic RAG / Memory | ADR-0020 §1 nói "agent có tool đọc repo vẫn mở được tệp artifact qua `path`", nhưng `tools.py:95-99` từ chối mọi đường dẫn tuyệt đối/thoát worktree, còn nhãn cắt ở `co/runner.py:447-448` đưa đúng đường dẫn tuyệt đối `<db>.artifacts/…`. Agent **không có cách** đọc phần bị cắt | `context_trimmed` 692 lần (`docs/reports/2026-09-27-audit.md:101`); pha spec đọc PRD cắt 48→35 KB, mất tiêu chí nghiệm thu (`docs/sessions/2026-09-22.md:67`) | A1, A2: tool `read_artifact(namespace, section)` |
| Memory (dài hạn) | bài học `knowledge` chỉ mang số; `hint` của người chỉ vào RAM, mất sau restart; `related_lessons` không có lời | 179/193 lỗi một dự án là cùng một sự cố mà không agent nào biết (`co/orch/enrich.py:46-50`) | A3 |
| Observability | `observe.span` + `otel_sink()` có sẵn nhưng `runner.sink = None` và không chỗ nào gán; `correlation_id` đứt ở `tasks` (`co/delivery.py:127`) và PR takeover (`co/orch/worktree_flow.py:281`) | ADR gốc 0009:9 "latency chưa đo được, đó chính là vấn đề"; `co/trace.py:3-4` người vận hành "phải tự truy SQLite"; `TRAPS.md` "Tin dashboard xanh" | Q1, Q2 |
| SLM | tier `light` cấu hình xong, chỉ `supervisor` khai light mà nó không trong `ROUTES`; comment `TIERS` (`core/llm.py:90`) vẫn ghi intake/clarifier là light (đã lên strong, ADR công ty 0037) | QLKH-004 tốn 10,7M token (`TRAPS.md:49`); 956k token đầu ra một ticket (`co/runner.py:56-59`) | L1 (chờ người chọn pha + eval-record), Q3 |

### 2c. Cột 3 — chưa có, và chưa cần (không có sự cố)

| Thứ | Vì sao chưa cần |
|---|---|
| RAG, Embeddings, Vector DB, Hybrid search, Reranking | Đã cân và loại ở ADR gốc 0003:64-66 ("blackboard N nhỏ theo thiết kế"), 0004:58-59 ("không embedding, không vector"); điều kiện mở lại ghi ở `2026-10-10-doi-chieu-12-repo-co-che.md:126` (tệp bài học vượt ngân sách ngữ cảnh — hiện ≤ 5 bài/prompt). Xếp hạng theo luật (`prd_context.py`, `lessons_for`) đủ cho N nhỏ |
| A2A | không có agent ngoài repo để nói chuyện; bus nội bộ có schema + ACL (`agent-frameworks.md:40`) |
| MCP server cho bên ngoài | chưa có người dùng ngoài `claude -p`; cầu nội bộ đủ |
| Lọc PII đầu ra | chỉ tag `pii` buộc review security (`co/events.py:41`); chưa sự cố |
| Bộ đếm token thật | `chars/3.2` được đối chiếu `token_estimate` mỗi lượt (`co/runner.py:515-517`); chưa sự cố do lệch |

## 3. Ảnh 2: 38 skill của `mattpocock/skills` (nguồn thật)

Tiêu chí: như ADR gốc 0028 (hợp stack, không trái luật, không trùng cơ chế, chỉ `.md` hoặc bỏ qua được metadata,
không dấu hiệu plugin) cộng §H (phải có sự cố). Đã quét 14 ứng viên qua `company.assetscan` và bộ lọc coupling của
`scripts/ecc_vendor.py`: **0 phát hiện `high`, 0 dấu hiệu plugin-only**; tệp không phải `.md` chỉ là `agents/openai.yaml`
(mọi skill) và hai `.sh` (`diagnosing-bugs`, `wizard`).

### 3a. Đủ dưới tên khác (7)

`tdd` (luật bắt buộc 4 + `TRAPS.md` §6 + `/gate`, cứng hơn: `fail_under = 100`, đo hai chiều ghi vào commit; Pocock
"test only at pre-agreed seams" và "refactoring is not part of the loop" **khác** luật 4), `diagnosing-bugs` (`/debug`
có thêm Pha 0 tra TRAPS và Pha 6 rà cả họ), `code-review` (`/gate`, `/ecc-review-pr`, `sc-*`), `implement`/`to-spec`/
`wayfinder` (`/thi-hanh` + `docs/thi-hanh/<mã>.md` idempotent), `handoff` (Compact Instructions + nhật ký phiên; Pocock
ghi `/tmp`, mất khi container cloud thu hồi).

### 3b. Một phần — hai mục có sự cố, LẤY (V4 của `ib1`)

| Skill | Repo có | Hở | Sự cố |
|---|---|---|---|
| `writing-for-agents` (+ `SKILL-MECHANICS.md`) | cổng canh tài liệu agent (`test_cong_khung.py:1137-1154`, 7 bước, assetbudget) và từ vựng (`docs/NGON-NGU.md`) | không có hướng dẫn **viết**: context pointer, hai loại tải (context/cognitive), thang thông tin, tiêu chí hoàn thành, leading word, phủ định làm ngược, tỉa no-op/sediment | luật nạp mỗi phiên 26,5 KB (`2026-10-10-audit-toi-gian-quy-trinh.md:106-117`); `pe2` P0 phải cắt "15 dòng thuật ngữ dày" khỏi `AGENTS.md` |
| `retro` | `TRAPS.md` + nhật ký phiên ghi tay; triết lý "hàng rào thi hành, không phải lời nhắc" | không có quy trình hồi cứu cuối phiên xếp theo bảy hạng (navigation, automated checks, coding standards, AGENTS.md phình, tool economy, no-op, information access) với luật "xây cổng thay vì viết luật" | bốn audit tay trong một ngày (`docs/reports/2026-10-10-audit-*.md`); audit tối giản chính là một retro không khuôn |

Hai mục này là **tham chiếu cho phiên người lái** (`.claude/skills/mp-*`); agent công ty chạy `--restricted` không thấy
(ADR gốc 0028 §"Đo"). `retro` nhắc `CODING_STANDARDS.md` (repo không có) — ghi chú nguồn đầu tệp nói mục không có thì
dùng `TRAPS.md`/`AGENTS.md`, cùng cách ADR 0028 xử lý câu "80 %" của `python-testing`.

### 3c. Một phần — không lấy, lý do

`to-tickets` (bảng B + gói việc 7 mục chia theo hạng mục/C1-C3, không theo lát dọc — hai cách chia, không thiếu),
`domain-modeling` (`GLOSSARY.md` + ADR một đoạn ≠ `docs/NGON-NGU.md` "chỉ thêm chữ đã gây nhầm" + ADR có số đo —
trái khuôn), `research` (ghép được từ PROMPT-SHEET §H + subagent `Explore`), `triage` (keeper `triager` cho tín hiệu
máy; không có issue tracker), `codebase-design`/`improve-codebase-architecture` (ADR gốc 0015 cố ý không radar kiến
trúc), `prototype` (luật 4 đã có ngoại lệ, cần hỏi người trước), `to-questionnaire` (ô `chờ người` của `/thi-hanh`),
`grill-with-docs` (kéo theo `domain-modeling`).

### 3d. Không có, chưa có sự cố (7) và không hợp (2)

Chưa cần: `wizard` (kèm `template.sh`), `teach`, `wait-what` (trỏ `GLOSSARY.md`), `pr` (mẫu PR đã có `BÁO CÁO XÁC
THỰC`), `implement-spec`/`ask-matt` (router: điều kiện "> 5 lệnh" đã đạt — 11 lệnh — nhưng chưa sự cố; `CLAUDE.md`
đã liệt kê), `in-progress/*` và `misc/*` (upstream không ship). Không hợp: `setup-matt-pocock-skills` (ghi `~/.claude`,
trái ADR gốc 0027:107-109), `resolving-merge-conflicts` (không còn ở nguồn).

### 3e. Có sự cố nhưng repo đã loại — quyết định của người (G1)

`grilling`/`grill-me`: sự cố #286 (`TRAPS.md:92`, hiểu sai yêu cầu "nhiều cổng dễ tắc" thành gộp agent, lùi cả PR).
Repo đã loại `/grill` **ba lần** (`2026-09-14-doi-chieu-projects-template.md:69`, `CHANGELOG.md:418`,
`2026-10-10-doi-chieu-projects-template-v4.md:74`) vì ngược `AGENTS.md` §"Khi bối rối". Điều khác lần này: skill của
Pocock là **user-invoked** (`disable-model-invocation: true`, 0 ký tự mô tả nạp vào ngữ cảnh) — người gõ `/mp-grill-me`
khi muốn bị hỏi dồn, luật "nêu giả định rồi đi tiếp" khi agent tự làm không đổi. `TRAPS.md` "Quyết lại điều một ADR đã
quyết" cấm phiên tự lật; nên để người quyết "có/không" (bảng B của `ib1`, mã G1).

### 3f. `resolving-merge-conflicts`: skill đã mất, sự cố vẫn còn

Hai sự cố ở đây (`TRAPS.md:130` nhân đôi dòng CHANGELOG; marker #307 nằm trên `main` một tuần,
`docs/sessions/2026-09-22.md:9-21`) → viết **quy trình của repo** ở `docs/QUY-TRINH-GIT.md` §2e (T3), không vendor.

## 4. Cơ chế vendor: từ một nguồn sang nhiều nguồn (V1–V5)

`scripts/ecc_vendor.py` + `docs/integrations/ecc.lock.json` + `test_cong_ecc.py` tái dùng được về khuôn (ghim commit,
sha256 từng tệp, tiền tố, ghi chú "luật repo thắng", hai lớp quét) nhưng cứng một nguồn: `LOCK_REL`/`PREFIX`/`_note`
(`ecc_vendor.py:35-37,186-194`), chỉ `.md` (`:106-111`), CLI không `--lock` (`:315-323`), cổng cứng `ecc-*`
(`test_cong_ecc.py:32-34,75,144,153`). ADR gốc 0028 đã dự liệu "tên repo thêm sau có thể đụng" → tiền tố riêng mỗi nguồn
(`mp-`). Quyết định ghi ở ADR gốc 0030; lock mới `docs/integrations/mattpocock.lock.json` giữ cả 36 mục `rejected` kèm lý
do để lần nâng bản sau không cân lại từ đầu.

## 5. Việc cho người (không máy nào thay được)

1. **G1** — vendor `grilling`/`grill-me` hay giữ quyết định loại (§3e).
2. **L1** — chọn pha chạy tier `light` và máy có khoá model để `make eval-record`.
3. **Q2** — có bật OTel ở máy vận hành không (OTel do người cài, ADR gốc 0009 quyết định 4).
4. Ảnh 1/3 không có nguồn gốc; nếu chủ dự án có link gốc, thêm vào §1 để lần sau đối chiếu đúng bản.
