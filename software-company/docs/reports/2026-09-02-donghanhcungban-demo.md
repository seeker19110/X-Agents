# Báo cáo mô phỏng: giao dự án donghanhcungban.com (bản demo) cho công ty AI

Ngày chạy: 2026-09-02. Kịch bản: `examples/donghanhcungban_demo.py` (không gọi model thật — `FakeClient` đóng vai
20 agent với nội dung theo dự án; khối kỹ thuật sửa code THẬT trong worktree của repo khách tạo tạm, lint/test thật chạy,
reviewer/QA đọc diff thật). Mục đích: xem kết quả bàn giao và phát hiện lỗi ở cả **sản phẩm demo** lẫn **quy trình của công ty**.

Chạy lại:

```bash
cd software-company && PYTHONPATH=src uv run python examples/donghanhcungban_demo.py --out sim-out
```

## 1. Kết quả vòng đời

| Bước | Diễn biến | Kết quả |
|---|---|---|
| Nghiên cứu | sales publish `research-requests` → intake → researcher → synthesizer → risk → clarifier (2 câu hỏi) | dừng chờ khách |
| Làm rõ | khách trả lời Q1 "lưu SQLite", Q2 "không tin tức" → spec-writer viết PRD v1 (3 Must, 1 Should, NFR a11y) | gate `SPEC-DHCB` |
| Gate 1 | PO duyệt spec → security-engineer viết threat model STRIDE v1 → delivery-lead lập C4 + OpenAPI + 4 ticket | gate `PLAN-DHCB-1` |
| Gate 2 | PM duyệt plan → dispatch DHCB-1 (router), sau đó DHCB-2 (layout), DHCB-3 (đăng ký, `pii`), DHCB-4 (schema, `pii`) | 4 PR `verified_by=workspace` |
| Review | DHCB-3 lần 1 **test đỏ** → reviewer block, QA fail với root_cause → retry=1 kèm hint → PR lần 2 xanh → security pass | rework_rate 0.25 |
| Release | mỗi ticket approved → 1 RC → merge `--no-ff` vào `company/integration` → staging → QA hồi quy (+ security với `pii`) | 4 gate `REL-00x` |
| Gate 3 | release-manager duyệt → production → support-docs viết release notes/runbook (namespace `docs` v1..v4) | 4 gate `UAT-*` |
| Nghiệm thu | 3 release accepted → ticket closed; REL-004 conditional → account-manager mở CR-DHCB-1 → delivery-lead ước lượng impact | PO `deferred` |

Số liệu: 238 event, 45 lời gọi model, 27 lời gọi tool, 71.5k token, 0 lỗi orchestrator, 0 PR unverified.
Artifact: `company.artifacts/DHCB/{prd,architecture,api-contract,threat-model,docs}/latest.*`. `main` của khách không bị chạm.

Điểm quy trình làm **đúng**: ticket phụ thuộc chờ ở `waiting` rồi tự dispatch; ticket `pii` bắt buộc thêm security review;
PR có test đỏ bị máy ghi `tests=false` bất chấp model khai `true`; vòng retry mang hint đúng root_cause; xung đột/merge
có kỷ luật `--no-ff`; ước lượng vs thực tế vào `knowledge`.

## 2. Lỗi phát hiện ở SẢN PHẨM demo (trên `company/integration`)

Test 9/9 xanh, ruff sạch, nhưng kiểm tra tay bằng `dhcb.web.handle()`:

| # | Lỗi | Nguyên nhân | Ai đáng lẽ bắt |
|---|---|---|---|
| S1 | Nav có link `/dang-ky` nhưng router trả **404** | OpenAPI khai `POST /dang-ky`, plan không có ticket nối form vào router; backend DHCB-3 chỉ viết `signup.py` | reviewer (đối chiếu contract ↔ code), QA hồi quy staging |
| S2 | Trang chủ/giới thiệu **không dùng layout chung** (không có `lang`, nav, viewport) | DHCB-2 tạo `layout.py` nhưng không sửa `web.py`; test của DHCB-2 chỉ test `page()` cô lập | QA (test tích hợp), account-manager (UAT theo Gherkin REQ-2) |
| S3 | `/static/site.css` → 404 | không có ticket phục vụ static | delivery-lead khi lập plan |
| S4 | Consent bị bỏ qua ở lần 1 của DHCB-3 (đăng ký thành công dù `consent=no`) | lỗi cố ý để thử quy trình | **đã bắt được**: QA fail → retry → sửa |

Kết luận cho khách: bản demo "xanh" theo bằng chứng máy nhưng chưa dùng được end-to-end; cần thêm 1 ticket tích hợp
(route `/dang-ky` GET/POST + bọc mọi trang qua `page()` + static) trước khi UAT.

## 3. Lỗi / lỗ hổng phát hiện ở QUY TRÌNH (framework `software-company`)

| # | Mức | Vấn đề | Bằng chứng | Đề xuất |
|---|---|---|---|---|
| F1 | cao — **đã sửa** | **Dự án chết im lặng**: synthesizer trả sai schema (lần chạy đầu) → chuỗi nghiên cứu dừng, `status` không có queue/deferred/gate nào chờ; không ai biết dự án kẹt | audit `synthesizer:invalid_output`, `status.tickets={}`, không supervisor action | supervisor phát hiện project có `invalid_output` mà không có event kế tiếp → `escalate` + gate `escalation` cấp dự án; `status` liệt kê "dự án không có bước tiếp theo" |
| F2 | cao — **đã sửa** | **Spec không cần bản nháp**: khách publish `clarification-answers` khi chưa có `clarification-questions` (vì chuỗi trên đã chết) → `_answers_complete` trả True → spec-writer viết PRD với `requirements_draft` trống | lần chạy đầu: `approved-specs` xuất hiện dù không có `requirements-draft` | route spec-writer yêu cầu có `requirements-draft` của cùng project, thiếu thì từ chối + audit |
| F3 | trung bình — **đã sửa** | **QA hồi quy staging không có tool**: route `release-events → qa-debugger` không cấp tool, QA chỉ "tin" mô tả deploy; S1/S2 lọt vì thế | `Route("release-events", "qa-debugger", ...)` không có `tools=`; QA staging trả "3/3 trang 200" mà không chạy gì | cấp tool chỉ đọc trên worktree `_integration` (`tools="ro"`) như QA trên PR; yêu cầu `metrics.smoke` do tool sinh |
| F4 | trung bình — **đã sửa** | **Ticket `released` mãi mãi sau nghiệm thu conditional**: DHCB-4 giữ `released` kể cả khi CR sinh ra đã `deferred`/`rejected` | `status.tickets["DHCB-4"]="released"` sau `decide-change deferred` | khi CR con của acceptance conditional được quyết định → đóng ticket của release đó (hoặc mở lại nếu accepted-cần-sửa) |
| F5 | trung bình — **đã sửa** | **CLI chỉ đọc vẫn cần model**: `orchestrator show/status/report` gọi `make_client()` → crash `cài SDK: uv sync --extra anthropic` khi máy người xem không có SDK/config | traceback ở `orchestrator.main` với `show prd` | lệnh chỉ đọc dùng `FakeClient()`/`None` thay vì `make_client()` |
| F6 | thấp — **đã sửa** | **PR test đỏ vẫn đi qua 3 reviewer**: backend publish PR dù `tests=false` (vi phạm "KHÔNG publish PR khi test fail"); tốn reviewer + QA + security một vòng chỉ để nói "test fail" | DHCB-3 lần 1: 3 review-results cho PR đã biết đỏ | runner: `local_checks.tests=false` → trả thẳng về ticket (retry+1, hint = test_output) không qua review |
| F7 | thấp — **đã sửa** | **Không gom release**: mỗi ticket approved → 1 RC → 1 staging → 1 gate 3 → 1 UAT; demo 4 ticket = 4 lần duyệt release, 4 release notes | REL-001..004, `docs` v1..v4 | delivery-lead gom RC theo cửa sổ/plan hoặc `--batch-release`; tối thiểu gom ticket cùng requirement |
| F8 | thấp — **đã sửa** | **Rác trong repo khách**: `.worktrees/` không được ignore → `git status` của khách thấy untracked | `?? .worktrees/` | thêm vào `.git/info/exclude` của repo khách khi tạo worktree |
| F9 | thấp — **đã sửa** | Phiên bản release do model khai: RC mang `version` (0.1.x) nhưng release-engineer có thể trả version khác mà không bị kiểm | lần chạy đầu: RC 0.1.1, release-events "1.0.0" | orchestrator ghi đè `version` từ RC như đã làm với `env`/`release_id` |

## 4. Việc tiếp theo

1. ~~Sửa F1, F2, F5~~ — đã sửa cùng ngày: gate `escalation` cấp dự án + `status.stalled` (F1), route spec-writer đòi
   `requirements-draft` + audit `spec_writer.no_draft` (F2), chỉ `run` mới gọi `make_client()` (F5); test trong `tests/test_orchestrator.py`.
2. ~~F3 + F6~~ — đã sửa: QA hồi quy staging có tool chỉ đọc trên worktree `_integration`, QA có tool mà không chạy gì
   thì audit `review.no_tool_evidence` (F3); PR có lint/test thật đỏ không publish, audit `pr.rejected_local_checks`,
   ticket retry+1 với hint là đầu ra test, không qua reviewer/QA/security (F6); test trong `tests/test_tools_and_agentic.py`.
3. ~~F4, F7, F8, F9~~ — đã sửa: CR từ nghiệm thu conditional mang `release_id`, khách quyết CR thì ticket đóng (F4);
   `--batch-release` gom ticket approved vào một RC khi dự án không còn ticket đang chạy (F7); `.worktrees/` vào
   `.git/info/exclude` của repo khách (F8); `version` release-events lấy từ RC, model khai khác bị ghi đè + audit (F9).
   Phát hiện thêm khi viết test: ticket bị `budget_cut` không có gate (treo im lặng) và gate escalation chỉ mở khi còn
   event kế tiếp — cả hai đã sửa cùng lượt.
4. ~~Với khách: mở ticket tích hợp DHCB-5~~ — đã mở và chạy lại (mục 5).

## 5. Lần chạy 2: thêm ticket tích hợp DHCB-5

DHCB-5 (backend, `depends_on` DHCB-2/3/4, `pii`): route `/dang-ky` GET+POST, bọc mọi trang qua `page()`, phục vụ `/static/`,
test tích hợp theo nav. Kịch bản bật `--batch-release` và thêm bước "khách bấm thử" trên `company/integration` ở cuối.

Kết quả: 5 ticket → 1 RC (v0.1.1) → staging → production → nghiệm thu → CR deferred → **5/5 ticket closed**;
46 lời gọi model, 0 lỗi. Kiểm tra sản phẩm **7/7 OK**: `/`, `/gioi-thieu`, `/dang-ky`, `/static/site.css` = 200,
trang chủ có `lang="vi"`, POST hợp lệ = 201 (ghi SQLite), POST thiếu consent = 422. S1–S3 đã hết.

Ba lỗi quy trình mới lộ ra khi chạy DHCB-5 (đều đã sửa, có test):

| # | Mức | Vấn đề | Sửa |
|---|---|---|---|
| F10 | cao | **Ticket phụ thuộc không thấy code của ticket đã approved**: merge vào nhánh tích hợp chỉ xảy ra lúc RC; khi gom release (hoặc ticket sau dispatch trước khi RC kịp merge) DHCB-5 rẽ từ nền chưa có `dhcb.layout` → `ModuleNotFoundError` | ticket approved merge ngay (`_integrate_approved`, gọi trước khi xử lý `tasks`); RC chỉ merge phần chưa có; xung đột lúc approved → ticket về changes_requested với hint; RC gặp ticket đã bị trả về → void |
| F11 | trung bình | **Agent kỹ thuật lỗi → ticket treo `dispatched` mãi** (không PR, không retry, không gate) | lỗi runner trên route `tasks` → `DeliveryLead.rework` retry+1 với hint là lỗi; hết retry → blocked → gate escalation |
| F12 | thấp | **Làm lại mà ghi y hệt lần trước → "commit thất bại"** khó hiểu (commit cũ đã nằm trên branch nên `has_changes` vẫn True) | `TicketWorkspace.dirty()` so với HEAD branch; runner báo "không sửa file (so với lần trước)" |

Ngoài ra, reviewer giả trong kịch bản chặn nhầm DHCB-5 vì heuristic khớp chữ "signup" ở dòng import — đã sửa kịch bản;
điều này minh hoạ đúng cảnh reviewer thật báo sai: ticket retry, agent không đổi gì → `không sửa file` → blocked → gate,
không có lỗi nào rơi vào im lặng.

## 6. Chế độ model thật (`--real`)

Kịch bản có cờ `--real`: bỏ client giả, 20 agent do model sinh, model theo tier trong front matter (16 `strong`: researcher,
synthesizer, risk, spec-writer, delivery-lead, 6 kỹ thuật, reviewer, qa-debugger, security-engineer, release-engineer,
account-manager; 4 `standard`: intake, clarifier, supervisor, support-docs). Kịch bản chỉ đóng vai người: trả lời câu hỏi
làm rõ theo phương án mặc định (tối đa 2 vòng), duyệt gate spec/plan/release, ký nghiệm thu, quyết change request; dự án
kẹt (agent lỗi, hết ngân sách) thì in trạng thái + lệnh `gate_cli` rồi dừng, không tự duyệt escalation.

```bash
COMPANY_LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-... \
COMPANY_MODEL_STRONG=claude-opus-5 COMPANY_MODEL_STANDARD=claude-sonnet-5 COMPANY_BUDGET_USD=20 \
PYTHONPATH=src uv run python examples/donghanhcungban_demo.py --real --out sim-real
```

Chạy thử trong môi trường không có khoá API (2026-09-02): intake nhận 401 → `project.stalled` → gate `escalation` DHCB,
dự án paused, kịch bản dừng có hướng dẫn — đúng hành vi F1. **Chưa có kết quả với model thật** vì môi trường chạy không
có `ANTHROPIC_API_KEY`; cần điền khoá (và bảng `prices` trong `llm.yaml` để có chi phí USD, đặt `budget_usd` để supervisor
pause khi chạm trần) rồi chạy lệnh trên.

Lỗi quy trình phát hiện thêm khi chuẩn bị chế độ này (đã sửa, có test):

| # | Mức | Vấn đề | Sửa |
|---|---|---|---|
| F13 | trung bình | **Spec publish lặp → nhiều plan cho cùng dự án**: `approved-specs` xuất hiện lần hai (spec-writer chạy lại, người publish hai lần) sau khi gate spec đã duyệt → delivery-lead lập PLAN-2, PLAN-3 trùng ticket, ba gate plan cho một việc | `_plan`: đã có plan từ approved-specs của dự án đang chờ/đã duyệt → audit `plan.duplicate_spec`, bỏ qua; muốn lập lại phải reject plan cũ |

## 7. Lần chạy 3: model thật qua subagent Claude Code (relay), 2026-09-02

Không có API key nên dùng `examples/relay_client.py`: orchestrator ghi mỗi lời gọi ra `<n>.req.json`, Claude Code giao cho
subagent theo tier (strong → Opus, standard → Sonnet), subagent ghi `<n>.res.json`. Khối kỹ thuật sửa thẳng trong worktree;
framework vẫn tự chạy ruff/pytest, commit, lấy diff cho reviewer/QA/security. Người (kịch bản + tôi làm lead) chỉ: trả lời
5 câu hỏi làm rõ theo mặc định, duyệt 3 gate, duyệt 1 escalation, ký nghiệm thu, hoãn 1 change request.
Artifact và transcript: `docs/reports/2026-09-02-donghanhcungban-relay/`.

### Kết quả sản phẩm

Nhánh `company/integration` (13 commit, `main` khách không đổi): `dhcb/{storage,validation,layout,site_pages,pages,service,app,server}.py`,
`python -m dhcb` bind 127.0.0.1 có CSP; **86 test xanh, ruff sạch**. Bấm thử tay như khách: `/`, `/gioi-thieu`, `/dang-ky`,
`/xac-nhan` = 200 có `lang="vi"` + băng-rôn demo; đường lạ 404 có bố cục chung; POST hợp lệ = 200 + 1 bản ghi SQLite;
thiếu consent = 400, hiện lại form kèm lỗi theo ô, 0 bản ghi; XSS bị escape. QA hồi quy trên server thật: p95 0,9 ms,
a11y cơ bản đạt, 12/12 Must của PRD. Cả 6 ticket closed, REL-001 v0.1.1 production (= gói bàn giao chạy cục bộ),
khách ký conditional, CR-DHCB-1 (trang tin tức) hoãn sang bản đầy đủ.

So với hai lần chạy client giả: chất lượng artifact cao hơn hẳn (PRD 12 Must Gherkin, threat model 16 threat STRIDE+LINDDUN,
OpenAPI, C4, sổ rủi ro FMEA; reviewer/QA/security bắt được `.pyc` commit nhầm, thiếu maxLength, 501 thay 404, keep-alive 413...).

### Chi phí

| Chỉ số | Giá trị |
|---|---|
| Lời gọi model qua relay | 43 (38 Opus, 3 Sonnet, 2 dùng lại cache intake/1 lặp) |
| Token do framework ước lượng (ký tự/4, prompt = system + đầu vào + blackboard toàn văn) | 938k → **17,70 USD** theo bảng giá mẫu trong `relay_client.py` |
| Token thật subagent Claude Code (gồm tool-use, đọc repo, chạy test) | **2,94M** cho 43 subagent; ước ~55–65 USD nếu tính giá Opus, thực tế nằm trong subscription Claude Code |
| Thời gian | ~3 giờ đồng hồ (14:32 → 15:45), phần lớn là chờ subagent tuần tự (workers=1) |
| Ước lượng vs thực tế | delivery-lead ước 30–55k token/ticket, thực tế 95–170k (ratio 1,9–5,7); rework_rate 0,17 (1/6 ticket làm lại) |

Bài học chi phí: mỗi lời gọi mang toàn văn blackboard (~25k token) nên 1 ticket = 4 lời gọi ≈ 95k token; supervisor cắt
ngân sách mọi ticket → cần `budget_tokens` thực tế hơn (calibration đã ghi vào `knowledge` cho lần sau) và cân nhắc
`max_input_chars` thấp hơn cho reviewer/QA.

### Lỗi quy trình phát hiện thêm (F14–F19)

| # | Mức | Vấn đề | Trạng thái |
|---|---|---|---|
| F14 | cao | `commit_all` dùng `git add -A` → `__pycache__/*.pyc` do subagent chạy pytest bị commit; hai ticket cùng commit `.pyc` → **xung đột merge nhị phân**, DHCB-3 phải làm lại | **đã sửa**: `JUNK_PATTERNS` vào `.git/info/exclude`, `commit_all` gỡ rác đã bị theo dõi khỏi index |
| F15 | cao | Ticket phụ thuộc được dispatch ngay lúc dependency `approved`, trước khi merge thành công → DHCB-4 làm trên nền không có layout, tự dựng khung riêng; sau này phải hợp nhất ở DHCB-6 | **đã sửa**: có nhánh tích hợp thì dependency phải `integrated` (`DeliveryLead.mark_integrated`), orchestrator merge ticket approved mỗi vòng `run()` (`_integrate_pending`) kể cả khi review cuối bị hoãn |
| F16 | trung bình | Budget token của ticket tính cả reviewer/QA/security (mỗi lời gọi ~25k token blackboard); delivery-lead ước 30–55k → supervisor `budget_cut` 6/6 ticket | **đã sửa** (`Supervisor.REVIEW_ACTORS`: token reviewer/QA/security ghi vào `Budget.review_used`, không trừ vào ngân sách ticket; `sprint_report`/lesson có `review_tokens`). Cắt blackboard theo vai trò + trần prompt theo agent: ADR-0020 |
| F17 | cao | Mở lại bus không replay `tasks` phát lại → ticket bị trả về lại thành `approved`, dependents dispatch, PR làm lại bị từ chối "approved → in_review" | **đã sửa** (`DeliveryLead._replay_task`) |
| F18 | trung bình | Merge nhánh trống (vừa `fresh()`) được tính "đã tích hợp" → code làm lại không bao giờ vào nhánh tích hợp | **đã sửa** (`integration.noop`) |
| F19 | trung bình | Mở lại bus ở chế độ gom release: replay tạo lại RC (REL-001..007 trong `status` sau khi đọc lại) và trạng thái ticket lệch (`approved` thay vì `closed`) dù lần chạy thật đã đúng | **đã sửa** (`DeliveryLead._on_release_candidate` dựng `releases`/`release_tickets`/`versions` từ log; `_on_review`/`flush_releases` không tạo RC khi `replaying`) |

Ngoài ra kịch bản dùng client giả có bước "khách bấm thử" gắn với API của code giả; đã đổi sang dò API (`dhcb.app.handle`
hoặc `dhcb.web.handle`) để dùng được cho cả code do model sinh.
