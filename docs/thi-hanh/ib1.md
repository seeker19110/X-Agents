# Ba infographic về AI agent — đối chiếu với repo và thi hành phần đáng làm

Ngày lập 2026-10-10 · căn cứ `main@8b2b597` (#416) · báo cáo đầu vào `docs/reports/2026-10-10-doi-chieu-ba-infographic.md`.
File này dùng cho phiên `/thi-hanh ib1` và cho người đọc muốn biết repo đứng ở đâu so với từ vựng ngành
(RAG, memory, MCP, A2A, planner/evaluator/guardrails/observability) và so với 38 skill của `mattpocock/skills`.

Đề bài của chủ dự án: *"nghiên cứu những thứ này, cải tiến, cải tổ, thay đổi dự án trở nên tốt hơn bằng hết khả
năng"*, kèm ba ảnh: (1) "24 AI Terms Everyone Should Know in 2026", (2) "How real engineers use AI agents — 25 skills
của Matt Pocock", (3) "AI Agents: 6 Must Know Definitions". Ảnh là tài liệu tiếp thị; mọi kết luận dưới đây đối chiếu
với **nguồn thật** (`mattpocock/skills@49dd158`, 2026-10-09, MIT) và **code thật** của repo, theo `docs/PROMPT-SHEET.md`
§H: "chưa có" chỉ được lấy khi nó giải một sự cố đã xảy ra ở đây.

## A. Hiện trạng

### A1. Kết luận

- 22/24 thuật ngữ của ảnh 1 và 6/6 định nghĩa của ảnh 3 **đã có cơ chế tương ứng** trong repo, dưới tên riêng
  (bảng cầu thuật ngữ: `ARCHITECTURE.md` §"Thuật ngữ ngành ↔ cơ chế ở repo"). Hai thứ không có là **cố ý**:
  RAG/embedding/vector DB (ADR gốc 0003, 0004, điều kiện mở lại ở báo cáo 12-repo) và A2A (báo cáo agent-frameworks).
- Bốn chỗ "có nhưng hở", mỗi chỗ có sự cố ghi lại: (1) agent **không đọc được** artifact blackboard bị cắt dù
  ADR-0020 nói được — PRD cắt 692 lần, mất tiêu chí nghiệm thu; (2) bài học `knowledge` chỉ mang **số**, lời người
  (`hint`) mất sau restart; (3) span quan sát có cơ chế nhưng **chưa nối sink**, `correlation_id` đứt ở hai event
  code tạo; (4) tier `light` có cấu hình nhưng **không agent runtime nào dùng** (956k token đầu ra một ticket).
- Ảnh 2 ghi 25 skill; nguồn thật có 38 (27 "promoted"). `resolving-merge-conflicts` trong ảnh **đã bị gỡ** ở
  upstream (#1120). So với repo: 7 đủ dưới tên khác, 11 một phần, 7 không có mà chưa có sự cố, 2 không hợp.
  **Hai skill đáng vendor** (`writing-for-agents`, `retro`); `grilling`/`grill-me` có sự cố (#286) nhưng repo đã loại
  ba lần — là quyết định của người, không phải của phiên này.
- Cơ chế vendor ECC (ADR gốc 0028) tái dùng được về khuôn nhưng script, lock và cổng đang cứng một nguồn; muốn
  thêm nguồn thứ hai phải tổng quát hoá (ADR gốc 0030).
- Mọi số trong file này đo lại được bằng `file:dòng`; không ô nào là ấn tượng đọc mã.

### A2. Bảng đối chiếu

Đường dẫn viết tắt: `core/` = `platform/xagents-core/src/xagents_core/`, `co/` = `companies/software-company/src/company/`,
`kp/` = `companies/keeper/src/keeper/`, `scadr/` = `companies/software-company/docs/adr/`.

| Đề bài đòi gì | Repo có gì | Ở đâu | Mã việc |
|---|---|---|---|
| Tên ngành ↔ tên repo tra được một chỗ | `docs/NGON-NGU.md` chỉ ghi chữ đã gây nhầm (`:8`), không có cầu sang từ vựng ngành | `docs/NGON-NGU.md:1-8`; `ARCHITECTURE.md` không có mục nào | T2 |
| Agent đọc được artifact bị cắt khỏi ngữ cảnh | nhãn cắt trỏ đường dẫn tuyệt đối `<db>.artifacts/…`; tool từ chối mọi đường tuyệt đối/thoát worktree; ADR-0020 §1 nói ngược lại | `co/runner.py:447-448`; `co/tools.py:95-99`; `scadr/0020-context-by-role.md:13`; sự cố `docs/sessions/2026-09-22.md:67`, `docs/reports/2026-09-27-audit.md:101` | A1, A2 |
| Bài học liên dự án có lời người | `knowledge` chỉ giữ số (`estimate/actual/ratio/retry/risk_tags`); `hint` vào RAM `self.knowledge`, không dựng lại sau restart | `co/orch/gates_flow.py:299-305`; `co/supervisor.py:204-205, 269-271`; `co/runner.py:478-481` | A3 |
| Truy vết một ticket xuyên suốt | `trace` gom theo id nghiệp vụ; `correlation_id` đứt khi code tạo `Envelope(...)` mới | `co/trace.py:49-94`; `co/delivery.py:127`; `co/orch/worktree_flow.py:281`; chỉ `co/runner.py:246` dùng `child()` | Q1 |
| Span/latency đo được | `observe.span` + `otel_sink()` có sẵn, nhưng `runner.sink = None` và không chỗ nào gán | `core/observe.py:99-165`; `core/runner.py:150`; ADR-0009:9 "latency chưa đo được, đó chính là vấn đề" | Q2 |
| Model nhỏ cho việc cơ học | tier `light` cấu hình (`claude-haiku-4-5`, `gemini-3.8-flash-low`) nhưng chỉ `supervisor` khai light và nó không trong `ROUTES`; comment `TIERS` cũ | `co/llm.claude-gateway.yaml:23,44,48`; `companies/software-company/agents/supervisor/supervisor.md:4`; `co/orch/routes.py:157-204`; `core/llm.py:90`; sự cố `TRAPS.md:49` (10,7M token), `co/runner.py:56-59` | L1, Q3 |
| Skill ngoài vendor được từ nhiều nguồn, ghim commit | script/lock/cổng cứng một nguồn: `LOCK_REL`, `PREFIX`, `_note`, chỉ `.md`; Pocock có `agents/openai.yaml` trong mọi skill | `scripts/ecc_vendor.py:35-37, 106-111, 186-194, 315-323`; `platform/console/tests/test_cong_ecc.py:32-34, 75, 144, 153` | V1–V5 |
| Hướng dẫn **viết** tài liệu cho agent (không chỉ cổng) | có cổng (`test_cong_khung.py:1137-1154`, 7 bước, assetbudget) và từ vựng, không có hướng dẫn viết; luật nạp mỗi phiên 26,5 KB | `docs/reports/2026-10-10-audit-toi-gian-quy-trinh.md:106-117`; `docs/thi-hanh/pe2.md` P0 ("15 dòng thuật ngữ dày") | V4 (`writing-for-agents`) |
| Hồi cứu cuối phiên thành hàng rào thay vì lời nhắc | `TRAPS.md` + nhật ký phiên ghi tay; bốn audit 2026-10-10 là hồi cứu thủ công; triết lý "hàng rào thi hành" đã có | `AGENTS.md` §"Hàng rào thi hành"; `TRAPS.md` §1; `docs/reports/2026-10-10-audit-*.md` | V4 (`retro`) |
| Giải xung đột merge theo ý định từng hunk | chỉ phòng ngừa (một PR mở, rebase) + cổng bắt marker | `docs/QUY-TRINH-GIT.md:57-82`; `platform/console/tests/test_readme_goc.py:141`; sự cố `TRAPS.md:130` (nhân đôi dòng CHANGELOG), marker #307 nằm trên `main` một tuần (`docs/sessions/2026-09-22.md:9-21`) | T3 |
| Phỏng vấn làm rõ đặc tả (`grilling`) | không có cho phiên người lái, **cố ý**: loại 3 lần vì ngược `AGENTS.md` §"Khi bối rối" | `docs/reports/2026-09-14-doi-chieu-projects-template.md:69`; `CHANGELOG.md:418`; `…-projects-template-v4.md:74`; sự cố `TRAPS.md:92` (#286) | G1 (chờ người) |
| Câu trong code khớp thực tế | `kp/blackboard.py:3` "cả 10 đều null" (keeper-supervisor sở hữu `knowledge`); `co/subagents.py:9` "(20 file)" (đĩa có 6); `core/llm.py:90` liệt kê intake/clarifier là light (đã lên strong, ADR-0037) | `kp/events.py:156-158`; `.claude/agents/sc-*.md`; `docs/DIEU-PHOI-MODEL.md:43` | T4, A4, Q3 |
| RAG / embedding / vector DB / rerank | không có, **cố ý**; thay bằng bơm toàn văn + cắt theo mục + tool đọc | `docs/adr/0003-doi-chieu-ruflo.md:64-66`; `docs/adr/0004-doi-chieu-agent-memory.md:58-59`; `docs/reports/2026-10-10-doi-chieu-12-repo-co-che.md:126` | cố ý không làm |
| A2A | không có, **cố ý hoãn**; bus nội bộ có schema + ACL thay thế | `docs/reports/2026-09-27-agent-frameworks.md:40` | cố ý không làm |
| Lọc PII trên đầu ra model | không có; chỉ tag `pii` buộc review security | `co/events.py:41`; `co/gate_brief.py:11` | chưa cần (không sự cố) |

## B. Kế hoạch

| Mã | Việc | Mảng | Hạng mục | Mức | Ưu | Nhược | Khi nào |
|---|---|---|---|---|---|---|---|
| T1 | Báo cáo đối chiếu ba infographic theo §H (ba cột, nguồn thật, `file:dòng`) | docs | ib1-tailieu | C2 | Kết luận có bằng chứng, dùng lại được | Dài | ◐ phiên này |
| T2 | `ARCHITECTURE.md` §"Thuật ngữ ngành ↔ cơ chế ở repo": 24 + 6 dòng, mỗi dòng `file:dòng` | docs | ib1-tailieu | C1 | Phiên sau không phải khảo sát lại 900k token | Phải bảo trì khi đổi cơ chế | ◐ phiên này |
| T3 | `docs/QUY-TRINH-GIT.md` §2e: giải xung đột theo ý định từng hunk, kiểm marker, chạy lại cổng | docs | ib1-tailieu | C1 | Đóng đúng hai sự cố đã ghi | — | ◐ phiên này |
| T4 | Sửa docstring `kp/blackboard.py:3` khớp `kp/events.py:156-158` | keeper | ib1-tailieu | C1 | Hết câu sai | Chạm `.py` → cổng keeper | ◐ phiên này |
| T5 | File này + dòng CHANGELOG + mục nhật ký phiên | docs | ib1-tailieu | C1 | — | — | ◐ phiên này |
| V1 | ADR gốc 0030: vendor skill **đa nguồn** — một script, một lock mỗi nguồn (`prefix`, `label`, `ignore`), cổng theo lock, trần mô tả chung cho cả `.claude/` | docs | ib1-vendor | C3 | Quyết định trước code; nêu phương án loại | Một vòng viết | ◐ phiên này |
| V2 | `scripts/vendor_skills.py` thay `ecc_vendor.py`: `--lock`, `prefix`/`label`/`license_path`/`ignore` từ lock, `_note` theo nguồn, bỏ qua tệp khớp `ignore` thay vì dừng, đổi cả tham chiếu `"x"` trong nháy kép, kiểm đụng tên giữa các lock | scripts | ib1-vendor | C2 | Nguồn thứ hai, thứ ba không cần script mới | Sinh lại 25 tệp `ecc-*` (ghi chú nguồn đổi) | ◐ phiên này |
| V3 | Test: `test_vendor_skills.py` (từ `test_ecc_vendor.py`, thêm ca ignore/nháy kép/đụng tên/`--lock`), `test_cong_vendor.py` (từ `test_cong_ecc.py`, parametrize theo mọi lock; trần mô tả chung) | console | ib1-vendor | C2 | Cổng offline cho mọi nguồn | — | ◐ phiên này |
| V4 | `docs/integrations/mattpocock.lock.json`: `select` = `writing-for-agents`, `retro`; `rejected` = 36 mục còn lại, mỗi mục một lý do; sinh `.claude/skills/mp-*` + `mattpocock.LICENSE` | docs | ib1-vendor | C1 | Hai skill có bằng chứng cần | Thêm ~150 ký tự mô tả vào ngữ cảnh mỗi phiên | ◐ phiên này |
| V5 | Makefile (`vendor LOCK=`, `vendor-check`), job CI `vendor-check` thay `ecc-check` (giữ trong `needs` của `quality`), `CLAUDE.md`, `AGENTS.md` luật cấm 5, `CODEMAP.md`, `ARCHITECTURE.md:102`, CHANGELOG | ci/docs | ib1-vendor | C1 | Một chỗ cho mọi nguồn | — | ◐ phiên này |
| A1 | Tool `read_artifact(namespace, section=None)`: đọc `latest.<ext>` của namespace trong phạm vi `context_namespace_read` của agent, cắt theo mục `##` nếu có `section`, trần `MAX_OUTPUT`; cấp cho mọi route có tool; nhãn cắt đổi từ đường dẫn sang `read_artifact("<ns>")` | company | ib1-artifact | C3 | Đóng lỗ PRD cắt 692 lần mà không cần vector | Đổi nhãn → `evals --replay --strict` có thể đỏ → eval-record (chờ người) | chưa |
| A2 | ADR công ty mới (số kế tiếp trong `scadr/`) + sửa câu `scadr/0020:13` | docs | ib1-artifact | C1 | Tài liệu khớp code | — | chưa |
| A3 | Bài học có lời: `_record_lesson` ghi `hint` vào `lesson["hint"]`; `lessons_for` trả kèm; `record_lesson` dựng lại từ bus khi khởi động | company | ib1-artifact | C2 | `related_lessons` có nghĩa, bền qua restart | Prompt dài hơn ≤ 5 × hint | chưa |
| A4 | Sửa docstring `co/subagents.py:9` "(20 file)" → số thật đo từ đĩa | company | ib1-artifact | C1 | — | — | chưa |
| Q1 | `correlation_id` xuyên suốt: `_publish_task` và PR takeover dùng `child()` của event gốc | company | ib1-quansat | C2 | `trace` theo một id | Cần event cha ở chỗ gọi | chưa |
| Q2 | Nối `runner.sink = otel_sink()` khi `XAGENTS_OTEL=1` (hoặc khoá `observe.otel` trong `llm.yaml`), `NullSink` khi thiếu OTel; test hai chiều | core + company | ib1-quansat | C3 | Latency đo được (ADR-0009) | Thêm một khoá cấu hình | chưa |
| Q3 | Sửa comment `core/llm.py:90` khớp ADR-0037 | core | ib1-quansat | C1 | — | — | chưa |
| L1 | Tier `light` cho việc cơ học thật: chọn pha (ứng viên: `ops[docs]`, `product[plan]` bước điền số), ADR công ty, 7 bước `CONTRIBUTING` §3 | company | ib1-light | C3 | Giảm token đo được | Cần `make eval-record` model thật | chờ người: chọn pha + máy có khoá model |
| G1 | Vendor `grilling`/`grill-me` (user-invoked, không đổi luật "Khi bối rối") hay giữ quyết định loại | docs | — | — | Có sự cố #286 | Repo đã loại 3 lần | chờ người: quyết "có/không"; "có" → thêm vào `select` của V4 |

Bốn hạng mục, thứ tự PR: **ib1-tailieu → ib1-vendor → ib1-artifact → ib1-quansat**; `ib1-light` và G1 chờ người. Mỗi hạng
mục ≤ 5 mã, ≤ 2 package.

**Cố ý không làm** (có bằng chứng trong repo, không phải ý thích):
- Không thêm RAG, embedding, vector DB, reranker: ADR gốc 0003/0004 đã loại; điều kiện mở lại là tệp bài học vượt
  ngân sách ngữ cảnh (`2026-10-10-doi-chieu-12-repo-co-che.md:126`) — `knowledge` hiện ≤ 5 bài/prompt.
- Không thêm A2A: không có agent ngoài repo để nói chuyện; bus có schema + ACL là đủ (`agent-frameworks.md:40`).
- Không làm MCP server cho bên ngoài: chưa có người dùng ngoài `claude -p`; cầu nội bộ `mcp_bridge.py` đã đủ.
- Không vendor `tdd` (khác luật 4 ở "seam thoả thuận trước" và "refactor ngoài vòng"; đã có `ecc-python-testing`),
  `domain-modeling` (`GLOSSARY.md`/ADR một đoạn ≠ `docs/NGON-NGU.md`/ADR có số đo), `diagnosing-bugs` (trùng `/debug`,
  kèm `.sh`), `code-review`/`implement`/`implement-spec`/`to-spec`/`to-tickets`/`triage`/`wayfinder`/`ask-matt`/
  `setup-matt-pocock-skills`/`pr` (cần issue tracker + nhãn triage do setup tạo; trùng `/thi-hanh`, `TASK-PACK`,
  `QUY-TRINH-GIT`, mẫu PR), `handoff` (ghi `/tmp`, trùng Compact Instructions + nhật ký phiên), `wait-what` (trỏ
  `GLOSSARY.md`), `research` (ghép được từ PROMPT-SHEET §H + `Explore`), `to-questionnaire`/`prototype`/`wizard`/
  `teach`/`codebase-design`/`improve-codebase-architecture` (chưa có sự cố), `in-progress/*` và `misc/*` (upstream
  không ship). Lý do từng mục nằm trong `rejected` của lock (V4).
- Không viết bộ đếm token thật thay `len`: ước lượng `chars/3.2` đã được đối chiếu `token_estimate` mỗi lượt
  (`co/runner.py:515-517`); chưa có sự cố do lệch.
- Không lọc PII đầu ra: chưa có sự cố.

**Rủi ro của chính file này:** (1) bảng A2 dựa trên ba khảo sát `Explore` đã tự kiểm hai điểm chính (ADR-0020:13 vs
`tools.py:95-99`; `runner.sink = None`), các dòng khác là `file:dòng` do trợ lý trả — sai số có thể là lệch vài dòng,
không phải sai cơ chế; (2) A1 có thể làm `evals --replay --strict` đỏ vì nhãn cắt nằm trong payload đã ghi — khi đó mã
sang `chờ người` (eval-record); (3) ảnh 2 không khớp nguồn thật (thiếu `retro`, `pr`, `implement-spec`; thừa
`resolving-merge-conflicts`) — file này theo nguồn thật.

## C. Gói việc

### T1 — Báo cáo đối chiếu

1. **Mục tiêu**: `docs/reports/2026-10-10-doi-chieu-ba-infographic.md` theo §H: nguồn đã đọc, ba cột (đã có và sâu hơn /
   đã có nhưng nông hơn / chưa có → chưa cần hoặc lấy), quyết định, việc cho người.
2. **Phạm vi**: chỉ tài liệu. 3. **Đầu vào**: ba khảo sát `Explore` (A2). 4. **Ràng buộc**: mọi khẳng định có `file:dòng`
   hoặc commit nguồn. 5. **Khung**: như `docs/reports/2026-10-10-doi-chieu-tu-van-da-dang.md`. 6. **Bằng chứng**: `git diff
   --check`; `scripts/dev-task.sh repo-gate`. 7. **Ca test**: không có (tài liệu). Tiêu đề PR của hạng mục:
   `docs(repo): ib1-tailieu — đối chiếu ba infographic, cầu thuật ngữ, giải xung đột, sửa câu lệch`.

### T2 — Cầu thuật ngữ trong `ARCHITECTURE.md`

1. Mục mới trước "Lịch sử repo": bảng *thuật ngữ ngành · cơ chế ở repo · ở đâu · ghi chú (có/một phần/cố ý không)*,
   24 dòng + 6 dòng. 2. Chỉ `ARCHITECTURE.md`; `docs/NGON-NGU.md` thêm **một dòng** trỏ sang (luật của NGON-NGU `:8`:
   không thêm mục cho đủ). 3–4. Dòng nào "không có" phải trỏ ADR/báo cáo đã loại. 5. Bảng Markdown. 6. `repo-gate`
   (cổng `test_cong_tai_lieu.py` kiểm link). 7. n-a.

### T3 — §2e giải xung đột

1. Sau §2d của `docs/QUY-TRINH-GIT.md`: quy trình 6 bước — đọc **ý định** hai phía (`git log -1 --format=%B` mỗi phía),
   giải từng hunk theo ý định chứ không chọn "ours/theirs" cả tệp, tệp append-only (`CHANGELOG.md`,
   `docs/sessions/*.md`) giữ **cả hai** dòng đúng thứ tự merge, `grep -rn '^<<<<<<<\|^>>>>>>>'` trước khi `add`, chạy lại
   `scripts/dev-task.sh gate <gói>` sau khi giải, không `--abort` (hook chặn; dừng hỏi người nếu hai phía đổi cùng logic).
   Trỏ `TRAPS.md:130` và #307. 2. Chỉ tài liệu. 6. `repo-gate`. 7. n-a.

### T4 — Docstring keeper

1. `kp/blackboard.py:3-4`: thay "cả 10 đều `null`" bằng câu đúng: 9 agent `null`, `keeper-supervisor` sở hữu `knowledge`
   (`kp/events.py:156-158`); đường ghi vẫn không chạy trong sản xuất vì orchestrator keeper không gọi LLM ngoài eval
   (`kp/evals.py:97`). 2. Một docstring. 6. `scripts/dev-task.sh gate keeper`. 7. n-a (docstring).

### V1 — ADR gốc 0030

1. `docs/adr/0030-vendor-skill-da-nguon.md`, khuôn 4 mục + "Phương án đã loại" + "Đo": số đo hiện tại (25 tệp ECC,
   5 035 ký tự mô tả; `.claude/` tổng 6 006; Pocock 38 skill, 27 promoted, mọi skill có `agents/openai.yaml`).
2. Quyết định: (a) một script `scripts/vendor_skills.py`, CLI `build|check --lock <path>`; (b) mỗi nguồn một lock
   `docs/integrations/<tên>.lock.json` mang `prefix`, `label`, `license_path`, `ignore` (glob tương đối trong mục,
   mặc định `[]`), các trường cũ giữ nguyên; (c) trần mô tả **chung** `.claude/` ghi ở cổng (`BUDGET_TOTAL = 8000`)
   cộng trần riêng từng lock; (d) tiền tố không được là tiền tố của nhau, tên mục sau tiền tố không đụng giữa các
   lock; (e) ghi chú nguồn nêu `label`, giấy phép, "luật `AGENTS.md` thắng"; (f) tham chiếu `"x"` trong nháy kép
   cũng đổi (Pocock gọi skill bằng `Call the Skill tool with "x"`); (g) `COUPLING` chung + `coupling` riêng trong lock.
3. Phương án đã loại: script thứ hai chép từ `ecc_vendor.py` (hai bản, sửa một lệch một); plugin
   `mattpocock-skills@claude-plugins-official` (ADR 0028 đã đo plugin không nạp ở phiên web); `npx skills add` (chép
   không ghim, cần node); giữ nguyên tên không tiền tố (ADR 0028 §"Phương án đã loại").
6. Link trong PR. 7. n-a.

### V2 — `scripts/vendor_skills.py`

1. Đổi tên `scripts/ecc_vendor.py` → `scripts/vendor_skills.py` (`git mv`), giữ docstring đầu nhưng viết cho đa nguồn.
2. Chữ ký giữ/đổi:
   ```python
   def load_lock(path: Path) -> dict
   def render(src: Path, lock: dict, others: list[dict] = ()) -> dict[str, tuple[str, str]]   # others: lock khác để kiểm đụng tên
   def build(root: Path, src: Path, lock_path: Path) -> dict
   def check(root: Path, src: Path, lock_path: Path) -> list[str]
   def fetch(remote: str, revision: str, dest: Path) -> Path            # giữ
   def rewrite_refs(text: str, items: dict[str, str], prefix: str) -> str   # thêm dạng "x"
   def _sources(src, kind, name, ignore: list[str]) -> list[Path]      # bỏ qua tệp khớp ignore (fnmatch trên đường dẫn trong mục)
   def _note(lock: dict, source: str) -> str                             # dùng lock["label"], lock["license"], LOCK đường dẫn
   def _on_disk(root: Path, prefix: str, license_rel: str) -> list[str]
   def main(argv) -> int   # argparse: cmd, --lock (bắt buộc), --src, --root, --remote
   ```
   `PREFIX`, `LOCK_REL`, `LICENSE_REL` hằng → đọc từ lock (`prefix`, đường dẫn lock, `license_path`). `COUPLING` giữ
   6 mẫu chung; `ecc:` chuyển thành mẫu riêng trong `ecc.lock.json["coupling"]`.
3. `ecc.lock.json` thêm `prefix: "ecc-"`, `label: "ECC"`, `license_path: "docs/integrations/ecc.LICENSE"`,
   `ignore: []`, `coupling: {"\\becc:[a-z]": "gọi mục ECC theo namespace plugin"}`; chạy `build` sinh lại 25 tệp (ghi chú
   nguồn đổi câu, nội dung không đổi) — đọc diff `.claude/` như mã người lạ.
4. Ràng buộc: không đổi hành vi với ECC ngoài dòng ghi chú; `ruff`/`mypy` theo console (`scripts/` được test nạp
   bằng `importlib`); Windows: `newline="\n"`.
5. Khung trong 2. 6. `scripts/dev-task.sh gate console`.
7. Ca test (V3) đỏ trước: `test_sources_bo_qua_tep_khop_ignore`, `test_rewrite_doi_ten_trong_nhay_kep`,
   `test_hai_lock_dung_ten_bi_tu_choi`, `test_tien_to_long_nhau_bi_tu_choi`, `test_main_can_lock`,
   `test_note_dung_label_cua_lock`; chiều ngược: `ignore` rỗng → tệp `.yaml` vẫn bị từ chối như cũ.

### V3 — Test

1. `git mv platform/console/tests/test_ecc_vendor.py test_vendor_skills.py`; sửa `SCRIPT`; fixture `lock` nhận
   `prefix`/`label`/`ignore`; thêm 6 ca ở V2.7. `git mv test_cong_ecc.py test_cong_vendor.py`: `LOCKS =
   sorted((ROOT/"docs/integrations").glob("*.lock.json"))` trừ `projects-template.lock.json` (khác khuôn, không có
   `select`) — hoặc lọc theo có khoá `select`; parametrize mọi test theo lock; `test_tong_mo_ta_toan_claude_duoi_tran_chung`
   (đọc mọi `SKILL.md`/lệnh/agent trong `.claude/` kể cả `sc-*`, ≤ `BUDGET_TOTAL`); giấy phép: kiểm "MIT License" +
   tên trong `lock["license_holder"]`; `enabledPlugins` giữ kiểm ECC; thêm kiểm `mattpocock-skills` không có trong
   `enabledPlugins`/`extraKnownMarketplaces`. 2. Chỉ console tests. 6. `gate console`. 7. như V2.7.

### V4 — Lock mattpocock

1. `docs/integrations/mattpocock.lock.json`: `repository: "mattpocock/skills"`, `revision:
   "49dd158d1076134a641b33efb035946536778336"`, `tag: null`, `version: "1.3.1"` (package.json), `license: "MIT"`,
   `license_holder: "Matt Pocock"`, `license_path: "docs/integrations/mattpocock.LICENSE"`, `prefix: "mp-"`, `label:
   "mattpocock/skills"`, `adr: "docs/adr/0030-vendor-skill-da-nguon.md"`, `budget_description_chars: 1500`,
   `ignore: ["agents/openai.yaml"]`, `select.skills`: `writing-for-agents` (lý do: audit tối giản 26,5 KB luật/phiên,
   pe2 P0; đây là tham chiếu để viết, cổng đã có), `retro` (lý do: hồi cứu thủ công 4 lần/ngày 2026-10-10; "xây cổng
   thay vì viết luật" = `AGENTS.md` §Hàng rào); `rejected`: 36 mục còn lại, lý do như "Cố ý không làm" ở B.
   Lưu ý skill Pocock nằm ở `skills/<bucket>/<x>/` → lock mang `skills_dir_globs: ["skills/*/{name}"]` hoặc script tìm
   `skills/**/<name>/SKILL.md` (quyết ở V1; đề nghị: khoá `layout: "bucket"` → tìm `skills/*/<name>`).
2. Chạy `make vendor LOCK=docs/integrations/mattpocock.lock.json` → `.claude/skills/mp-writing-for-agents/{SKILL.md,
   SKILL-MECHANICS.md}`, `.claude/skills/mp-retro/SKILL.md`, `docs/integrations/mattpocock.LICENSE`. Đọc diff. 6. `gate
   console` (cổng vendor + assetscan). 7. cổng `test_cong_vendor.py` xanh cho cả hai lock.

### V5 — Makefile, CI, tài liệu

1. Makefile: `vendor: uv run python scripts/vendor_skills.py build --lock $(LOCK)`; `vendor-check:` lặp mọi lock có
   `select`; giữ `ecc-vendor`/`ecc-check` làm alias một dòng gọi `vendor LOCK=…` (CLAUDE.md và CODEMAP còn trỏ). CI: job
   `vendor-check` chạy `make vendor-check`, thay `ecc-check` trong `needs` của `quality` (`ci.yml:565`) và comment
   `ci.yml:399-402`. `CLAUDE.md` §ECC → §"Skill vendor" nêu hai nguồn, tiền tố `ecc-`/`mp-`, lệnh `/mp-retro`;
   `AGENTS.md` luật cấm 5 thêm `mp-*` và `mattpocock.LICENSE`; `CODEMAP.md:26` dòng ECC → dòng chung; `ARCHITECTURE.md:102`
   `ecc-check` → `vendor-check`; `README.md` nếu đếm số skill `.claude`; CHANGELOG một dòng. 6. `repo-gate` +
   `test_cong_khung.py` (kiểm `ci.yml` ↔ `dev-task.sh`). 7. cổng `test_cong_vendor.py::test_adr_va_claude_md_tro_dung_cach_dung`.
   Tiêu đề PR: `feat(claude): ib1-vendor — vendor skill đa nguồn, lấy writing-for-agents và retro của mattpocock/skills`.

### A1 — Tool `read_artifact`

1. `co/tools.py`: lớp `ArtifactTools(blackboard, project_id, spec)` với `read_artifact(namespace: str, section: str |
   None = None, start: int = 1, end: int | None = None) -> str`; từ chối namespace ngoài `spec.reads_full(ns)` và namespace
   không thuộc dự án; đọc `blackboard.path(ns, project_id=...)`; `section` khớp tiêu đề `##` (không phân biệt hoa thường);
   trần `MAX_OUTPUT` của core cắt như tool khác. `add_to(tb)` đăng ký. `co/orchestrator.py:381-410` (`_toolbox`): thêm
   cho mọi route có tool. `co/runner.py:447-448`: nhãn cắt → `"gọi read_artifact(\"<ns>\") để đọc đủ"`; `tools_prompt`
   không đổi (tên tool tự vào danh sách).
2. Chỉ company. 3. ADR-0020 §1 câu 3; `core/blackboard.py:85-96` (`path`), `core/registry.py:96-99` (`reads_full`).
4. Ranh giới: không đọc `knowledge` thô (runner đã bỏ), không đọc namespace dự án khác; đường dẫn do code dựng, agent
   chỉ đưa tên. 5. Chữ ký ở 1. 6. `gate company`; `evals all --replay --strict`.
7. Ca đỏ trước: `test_read_artifact_tra_dung_latest`, `test_read_artifact_cat_theo_muc`,
   `test_read_artifact_tu_choi_namespace_ngoai_pham_vi_doc`, `test_read_artifact_tu_choi_du_an_khac`,
   `test_nhan_cat_tro_read_artifact_khong_phai_duong_dan`; chiều ngược: tắt `add_to` → agent không có tool, nhãn cũ.
   Tiêu đề PR: `feat(company): ib1-artifact — tool read_artifact và bài học có lời người`.

### A3 — Bài học có lời

1. `co/orch/gates_flow.py:299-305`: `lesson["hint"] = t.hint or ""`; `co/supervisor.py`: `lessons()` giữ `hint`;
   `lessons_for` trả `{"ticket_id","assignee","ratio","retry","risk_tags","hint"}`; `record_lesson` không đổi chữ ký.
   `knowledge` RAM dựng lại từ `lessons()` ở `co/supervisor.py:269-271`. 6. `gate company`. 7. đỏ trước:
   `test_bai_hoc_mang_hint_cua_nguoi`, `test_related_lessons_co_hint`, `test_knowledge_dung_lai_sau_restart`.

### Q1 — `correlation_id` xuyên suốt

1. `co/delivery.py:127` `_publish_task(task, parent: Envelope | None)` → `parent.child(...)` khi có; `dispatch` nhận `parent`
   từ `ticket_fsm` (event `plans`); `co/orch/worktree_flow.py:281` lấy event PR gần nhất của ticket làm cha. 6. `gate
   company`. 7. đỏ trước: `test_tasks_mang_correlation_cua_plan`, `test_pr_takeover_noi_chuoi_nhan_qua`.

### Q2 — Nối span sink

1. `core/observe.py` giữ; `co/llm.py` (`make_client`/cấu hình): khoá `observe: {otel: true}` trong `llm.yaml` hoặc env
   `COMPANY_OTEL=1` → `runner.sink = otel_sink("company")`; thiếu OTel → `NullSink` (đã có). ADR gốc 0009 ghi quyết định 4
   (OTel do người vận hành cài) — giữ. 6. `gate core` + `gate company`. 7. đỏ trước: `test_sink_bat_khi_cau_hinh`,
   `test_sink_none_khi_khong_cau_hinh` (no-op tuyệt đối giữ nguyên).

### L1, G1 — chờ người

L1: chọn pha chạy `light` (đề nghị thử `ops[docs]` trước — đầu ra là tài liệu, có eval sẵn), viết ADR công ty, chạy 7
bước với model thật, so điểm eval trước/sau. G1: quyết định có vendor `grilling`/`grill-me` hay không; "có" thì ghi vào
`select` của `mattpocock.lock.json` kèm lý do "#286, user-invoked nên không đổi luật Khi bối rối", chạy `make vendor`.

## D. Điều phối

| Đợt | Song song (phát triển) | Thứ tự PR | Điều kiện vào đợt |
|---|---|---|---|
| 1 | T1–T5 (một gói) | PR 1 `docs(repo)` | #417 merge, nhánh dựng lại từ `main` |
| 2 | V1 → V2+V3 (cùng subagent, test đỏ trước) → V4 → V5 | PR 2 `feat(claude)` | PR 1 merge |
| 3 | A1+A2 ‖ A3 ‖ A4 | PR 3 `feat(company)` | PR 2 merge; `evals --replay --strict` xanh sau A1, đỏ → `chờ người` |
| 4 | Q1 ‖ Q2+Q3 | PR 4 `feat(core)` (scope core vì Q2 chạm core) | PR 3 merge |
| — | L1, G1 | — | người quyết |

Mức → model: C1 Haiku, C2 Sonnet, C3 Opus (`docs/KHUON-THI-HANH.md` §2). `sc-*` chấm: PR 2 `sc-security` (nội dung
vendor đi vào phiên người lái — assetscan đã quét, vẫn đọc diff `.claude/`); PR 3 `sc-builder` + `sc-qa` (ranh giới
tool); PR 4 `sc-supervisor` (quan sát/ngân sách). Khuôn giao việc: `docs/KHUON-THI-HANH.md` §4.

Trạng thái sống ở bảng B cột "khi nào" — `◐ phiên này` nghĩa là đang làm trong phiên lập file; `xong #n` khi PR merge.

## F. Lệnh thi hành

```
/thi-hanh ib1                        # thi hành tới xong (idempotent, chạy lại tiếp từ chỗ dở)
/thi-hanh ib1 --dung-sau-ke-hoach    # chỉ in bảng B rồi dừng
```

Trước khi gõ: nhánh chứa file này đã merge `main` chưa (PR 1); đợt 2 cần github.com để `vendor-check` fetch nông
hai commit ghim; đợt 3 có thể dừng ở `chờ người` nếu `evals --replay --strict` đỏ (cần máy có khoá model để
`make eval-record`); L1 và G1 cần người quyết trước khi làm.
