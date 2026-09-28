# Bốn lớp dùng LLM (Prompts → Agents → Loops → Graphs) — hiện trạng, kế hoạch, gói việc

Ngày lập: 2026-09-08 · Căn cứ `main@09d03a9` (#178) · Mã thi hành **`4l`** — bản đầu tiên theo
`docs/KHUON-THI-HANH.md`; thi hành bằng `/thi-hanh 4l`. `file:dòng` đo tại commit đó; tên hàm và audit action bền hơn
số dòng. Một file cho ba câu hỏi: **đang ở đâu** (A), **làm gì, ai làm, thứ tự nào** (B, D), **từng việc làm thế
nào** (C). Phần E là khuôn cho công ty dựng sau này. Không phải luật; luật ở `AGENTS.md`.

---

## A. Hiện trạng

### A1. Kết luận

1. **Đã là hệ lớp 4**: bước kế tiếp do `ROUTES` trong code quyết (`orch/routes.py:278-326`); rẽ nhánh trên
   `Literal` đã bị schema chặn; hợp luồng bằng code. Vượt đặc tả: trường "đã làm" chỉ code điền (`verified_by`),
   `unverified` = failed (ADR-0036).
2. **Lớp 1 kỷ luật có, nội dung mỏng**: version/golden/asset budget đủ, nhưng 0 ví dụ input–output, và cổng eval
   `--strict` chỉ đỏ khi *thiếu bản ghi*, không đỏ khi *ca chấm fail* (`evals.py:311-356`).
3. **Lớp 3 có trần, không có phát hiện**: vòng tool chỉ append (`runner.py:249-257`), không nhận ra gọi lặp;
   audit `tools_used` chỉ đếm tổng nên "agent gọi lặp" không nhìn thấy từ log.
4. **Không chốt duyệt mức tool — có chủ đích**: thay bằng "không cấp tool thì không có hành động"
   (`allow_write/allow_run/write_scope`, sandbox) + 4 gate công đoạn. Phải ghi vào `ARCHITECTURE.md`.
5. **Studio thấp hơn company một bậc**: 4 chỗ rẽ nhánh so chuỗi, chưa có trace CLI, `deferred` chỉ RAM, chưa trần
   ngân sách media.
6. Việc đáng làm: **vá lớp 1 và 3**. Không thêm lớp, không đổi model, không nhập framework (LangGraph, CoALA…) —
   bốn lớp là thang nghiệm thu; lấy thêm năm mẫu nút của Anthropic (chaining / routing / parallelization /
   orchestrator–workers / evaluator–optimizer) làm từ vựng đặt tên route và loop trong ADR.

Checklist 9 mục cuối đặc tả: company **6 ✅ 3 ◐**, studio **3 ✅ 6 ◐**.

### A2. Bảng đối chiếu

✅ có và đo được · ◐ một phần · ❌ không có · CL = mục checklist đặc tả · 4L = việc ở phần B.

| Đặc tả đòi | company | studio | Ở đâu | CL | 4L |
|---|---|---|---|---|---|
| L1 ngữ cảnh / chỉ dẫn / DoD / đường lui | ✅ | ✅ | `test_golden_agents.py:26` ép 6 mục; `product.md:206-215` | | |
| L1 định dạng đầu ra máy đọc | ✅ | ✅ | `runner.py:54,109-121`; `topics/schemas/*.json` | | |
| L1 ví dụ input–output trong prompt | ❌ | ❌ | chỉ ở `evals/*.yaml` làm test | | (sau 1) |
| L1 bộ test cố định, cổng chấm điểm | ✅ | ◐ | `--strict` đỏ khi ca fail/thiếu (1a #182); security 10 ca, ngưỡng `cases: 10` (1b #204) | 1 | **1** |
| L2 tool có schema, tách đọc/ghi/chạy | ✅ | ✅ | `WorkspaceTools(...)` `tools.py:68-91` | | |
| L2 chốt duyệt tool tác dụng phụ | ✅* | ✅* | *thay bằng không cấp tool + gate `gates.py:9` | 2 | **8** |
| L2 lỗi tool có hướng dẫn | ✅ | ✅ | `tools.py:196,97,118,138` | | |
| L2 giới hạn phiên | ✅ | ✅ | `max_turns=25` `runner.py:299`; budget output `:243`; timeout 600/900s | | |
| L2 nhật ký tool call | ✅ | ✅ | audit `tools_trace` từng lời gọi (name/args_hash/out_hash/ms), `company.trace` in `↳` | 7 | **2** |
| L2 nội dung ngoài = dữ liệu | ✅ | ✅ | `runner.py:90-96`; `sanitize_tool_output` `:254-256`; guard K3.4 | 6 | |
| L3 kiểm bằng máy | ✅ | ✅ | `ws.run_checks()` → `verified_by=workspace` `runner.py:450-462`; `qc.py` | | |
| L3 trần cứng | ✅ | ✅ | `max_retries=3` `delivery.py:28`; `MAX_REPAIR_ROUNDS=3` `studio/events.py:41` | 3 | |
| L3 phát hiện không tiến bộ | ✅ | ◐ | ngoài vòng: `supervisor.py`; trong vòng tool: `_stagnant()` cắt ở 5 lần lặp cùng hash (company). Studio chưa | 3 | **3** |
| L3 giữ yêu cầu gốc qua vòng | ✅ | ✅ | rework phát lại nguyên `tasks` + `hint` | | |
| L3 tỉa trạng thái qua vòng | ✅ | ✅ | `fit` cắt một lần trước vòng + `_prune` (core `context.py`) cắt `role=tool` cũ hơn 3 lượt MỖI lượt bên trong vòng (`company/runner.py:_turns`, `studio/runner.py:_tool_loop`), ADR-0007 | | **4** |
| L3 đo vòng (p50/p90, chạm trần) | ✅ | ❌ | `metrics.collect()["loops"]` + 6 gauge + ô console (company); studio chưa | | **5** |
| L4 nút không LLM | ✅ | ✅ | `_check_plan` `ticket_fsm.py:207-241`, smoke `verify.py:51`; `renderer.py`, `desk.py` | | |
| L4 rẽ nhánh theo kiểu | ✅ | ✅ | `routes.py:322-324`; studio `_rework`/`_publish_video` validate model trước rẽ nhánh | 5 | **6** |
| L4 kiểm lược đồ ở biên | ✅ | ✅ | pydantic + JSON Schema lúc publish `bus.py:317-356` | 4 | |
| L4 gate trước hành động không hoàn tác | ✅ | ✅ | `deploy_production` `delivery.py:313`; publish sau gate `PUB-` | 2 | |
| L4 chính sách lỗi từng nút | ✅ | ✅ | transient → hoãn; nội dung → retry → blocked → gate; unhandled → gate `gates_flow.py:245-257` | 9 | |
| L4 trace toàn cục | ✅ | ✅ | `xagents_core.trace` dùng chung; `python -m studio.trace <VIDEO\|PLAN\|CHANNEL>` | 7 | **7** |
| L4 điểm khôi phục | ✅ | ✅ | `orch/rehydrate.py`; studio `Orchestrator._nap_lai_hen` nạp lại `defer.until` lúc `_rehydrate` | 9 | **7** |
| L4 trần ngân sách toàn quy trình | ✅ | ❌ | `supervisor.py:196-213`; studio S5 chưa | 8 | (S5) |

Studio, bốn chỗ so chuỗi (việc 6): `_rework` `orchestrator.py:618-625` so `payload["source"]` trước validate;
`_publish_video` `:775,823-828` đọc `p.get("status")` trước validate; `_transient` `:505-518` cắt chuỗi
`transient:<agent>:<msg>`; `_on_gate_decision` `:702` `actor.startswith("human")`.

---

## B. Kế hoạch — tám việc, một bảng

Thứ tự "lớp dưới trước". Mức: **C1** cơ học (Haiku 4.5 hoặc Sonnet 5 `low`) · **C2** cục bộ, hợp đồng cho sẵn
(Sonnet 5 `medium`) · **C3** xuyên module / đổi hành vi (Opus 5 `high`; `effort` theo ADR-0026). Không hạ mức C3,
không nâng mức C1.

| 4L | Việc | Lớp | PR | Mức | Ưu | Nhược / rủi ro | Khi nào |
|---|---|---|---|---|---|---|---|
| **1a** | `evals/thresholds.yaml` + CI đỏ khi điểm dưới ngưỡng | L1 | `feat(company)` | C2 | lần đầu biết chỉnh prompt là cải thiện hay hồi quy | ngưỡng sai → đỏ vì nhiễu; ngưỡng = **bẫy hồi quy**, không phải chỉ tiêu | xong #182 |
| **1b** | security 2 → ≥ 10 ca, ghi lại model thật | L1 | `chore(company)` | C2 + người | ngưỡng có nghĩa | cần máy có key, 7 bước | xong #204 |
| **2** | audit `tools_trace` từng lời gọi tool (hash, ms, args cắt) | L2 | `feat(core)` | C2 | nhìn thấy gọi lặp; tiền đề 3 | args có dữ liệu khách → hash/cắt, `content` không ghi | xong #183 |
| **3** | cắt vòng tool khi không tiến bộ (nhắc ở 3, cắt ở 5) | L3 | `feat(company)` | **C3** | cắt sớm ticket kiểu 956k token | dương tính giả nếu không loại tool ghi xen giữa; mỗi cắt +1 retry | xong #184 |
| **4** | tỉa tool output cũ trong vòng (ADR-0007) | L3 | `docs` + `feat(core)` | **C3** | lượt cuối không đắt gấp mười lượt đầu | **đổi hành vi agent** ở ca ≥ 4 lượt tool; không đổi khoá bản ghi eval (khoá = hash(system, USER MESSAGE ĐẦU), `_prune` chỉ sửa `msgs` bên trong vòng, không sửa `user` gốc — kiểm bằng `evals all --replay --strict` cả hai công ty: mọi bản ghi hiện có PASS không đổi) | ADR xong #206 (docs/adr/0007), `_prune` + ghép + test: xong #208 |
| **5** | `metrics.loops` p50/p90/capped + ô console | L3 | `feat(company)` | C2 | rẻ nhất, số đã có | ô mới phải theo console ADR-0003 (rỗng = xám) | xong #185 |
| **6** | studio validate trước rẽ nhánh (4 chỗ) | L4 | `refactor(studio)` | **C3** | đóng lỗ L4 còn lại của studio | chạm `events.py` lúc dời bus | xong #190 |
| **7** | `xagents_core.trace` + `studio.trace` + `deferred` bền | L4 | `feat(studio)` | **C3** | studio ngang company | copy = thêm fork → phải lên core | xong #196 |
| **8** | ARCHITECTURE: "vì sao không chốt mức tool", năm package; bảng K3 cập nhật | — | `docs` | C1 | chặn hiểu nhầm | — | xong #181 |

**Cố ý không làm**: chốt duyệt mức tool (quay lại "nghẽn chốt" mà ADR-0037 vừa gỡ); tách `product.md` thành 4
file (đảo ADR-0037 không có lỗi mới); few-shot trước việc 1 (không đo được); đưa đặc tả vào `AGENTS.md`.

**Rủi ro của chính file này**: thành bảng theo dõi nói sai (bài học #168). Sau mỗi PR merge: đổi cột "Khi nào"
thành `xong #n` **và** ô A2 tương ứng (◐ → ✅), cùng PR. Đo lại A2 trong gói việc audit toàn dự án (`docs/TASK-PACK.md`).

---

## C. Gói việc từng hạng mục

Mỗi gói = một worktree, một PR. Dán khối 7 mục vào đầu phiên subagent. Chữ ký hàm là hợp đồng; khung test là
ca bắt buộc, thêm được, không bớt. Chung cho mọi gói: lệnh CI package
`uv run ruff check src tests && uv run mypy src/<pkg> --ignore-missing-imports && uv run pytest -q -n auto --cov`
(không có xdist thì bỏ `-n auto`, không hạ `--cov`); test **đỏ trước, xanh sau**, dán cả hai output vào commit;
CHANGELOG `(#n)` điền ngay sau tạo PR và commit vào chính PR; session log; cập nhật bảng B. Lùi = revert PR (không
gói nào đổi schema topic; audit action mới chỉ là dòng thừa với code cũ).

### 4L-1a · Ngưỡng eval

1. **Mục tiêu**: `evals.py:311-356` cổng CI là `gate_ok`; `cases_ok` chỉ in "CHÚ Ý". Điểm tụt 90 → 60% vẫn xanh.
2. **Xong khi**: `evals/thresholds.yaml` 6 agent = điểm đo hôm nay làm tròn xuống 0.05 · `evals all --replay --strict`
   exit 0 · bản sao tạm sửa `expect` sai → exit 1 dòng `dưới ngưỡng` · 8 ca test xanh.
3. **Phạm vi**: `src/company/evals.py`, `evals/thresholds.yaml`, `tests/test_evals_thresholds.py`, `Makefile`
   (`eval-thresholds`), `CONTRIBUTING.md` §3 bước 3. **Không**: `agents/`, `skills/`, `evals/*.yaml`, `recordings/`.
4. **Đọc**: `evals.py` docstring + `main` 289-356; ADR-0010; ADR-0022 "bẫy hồi quy"; `TRAPS.md` §2 "proxy sai".
5. **Ràng buộc / khung code**: agent không trong yaml → không áp; `total == 0` → không áp; tính ratio SAU khi gom
   `outcomes` (vì `--jobs`).
   ```python
   @dataclass(frozen=True)
   class Threshold: min_pass_ratio: float; cases: int          # cases: số ca tối thiểu — chống thu nhỏ bộ
   def load_thresholds(path: Path | None = None) -> dict[str, Threshold]   # không có file → {}; sai hình → LLMError
   def check_thresholds(outcomes: list[_AgentOutcome], th) -> list[str]   # dòng FAIL; ratio<min | total<cases
   # _AgentOutcome: property passed/total. main: sau vòng outcomes → for line in check_thresholds: gate_ok=False
   # cờ --thresholds PATH (mặc định evals/thresholds.yaml nếu có), --no-thresholds; _summary thêm cột ngưỡng
   ```
6. **Bẫy**: agent không có ca → `res=[]` chia 0. Workflow K5.3 `eval-record.yml` mở PR bản ghi mới tụt điểm → PR
   ấy đỏ, đúng ý — ghi vào mô tả workflow.
7. **Kiểm**: test `diem_duoi_nguong_thi_do`, `diem_bang_nguong_thi_xanh`, `thu_nho_bo_ca_thi_do`,
   `agent_khong_trong_file_khong_bi_chan`, `khong_co_ca_khong_ap`, `thresholds_yaml_that_khop_required`,
   `main_exit_1_khi_duoi_nguong`, `main_no_thresholds_tat_cong` (chiều ngược). Lệnh CI. PR
   `feat(company): 4L-1a — ngưỡng eval theo agent, CI chặn tụt điểm`.

### 4L-1b · Security ≥ 10 ca (máy có key)

1. `evals/recordings/security.json` có 2 bản ghi; ngưỡng trên 2 ca vô nghĩa. Threat model gác gate `spec`.
2. `evals/security.yaml` ≥ 10 ca `expect` kiểm được · `make eval-record AGENT=security` output trong PR ·
   `thresholds.yaml` `security.cases: 10` · golden/assetscan/assetbudget/subagents không lệch.
3. Được: `evals/security.yaml`, `recordings/security.json`, `thresholds.yaml`. Không: `agents/security.md`
   (version không tăng — prompt không đổi), `.claude/agents/`.
4. `CONTRIBUTING.md` §3; `evals/product.yaml` mẫu ca; `topics/schemas/review-results.json`; ADR-0030, 0031.
5. Ca phủ: (a) spec `kind=application` có `runtime`; (b) không `runtime` → finding thiếu; (c) `risk_tags`
   `auth`/`payment`/`pii` mỗi tag một ca; (d) payload chứa injection → `verdict` ≠ approved, finding nhắc, KHÔNG
   thi hành; (e) thiếu dữ liệu → `conditional` + câu hỏi; (f) `ruling.cost_if_wrong` có. Dùng `any_of`.
6. Bản ghi khoá hash(system, user): ghi lại cả agent, không ghép JSON tay; không cherry-pick lần "đẹp".
7. `evals security --replay --strict` exit 0; CI. PR `chore(company): 4L-1b — security ≥ 10 ca eval`.

### 4L-2 · Vết từng lời gọi tool

1. `ToolBox.calls` (`xagents_core/tools.py:51,85`) đã giữ `{name,args,ok,chars}` trong RAM; runner chỉ ghi
   `summary()` vào `tools_used`. Tiền đề của 4L-3.
2. `ToolBox.trace()` · company + studio audit `tools_trace` đúng một lần/lượt · `company.trace` in `↳`, gộp
   `×N lặp` khi ≥ 3 call liên tiếp cùng bộ ba hash · evidence < 20k ở ca 25×4 · mypy strict core sạch.
3. Được: `xagents_core/tools.py`, `company/{runner,tools,trace,metrics}.py`, `studio/runner.py`, tests ba package.
   Không: schema `audit-log`; hình `tools_used` (metrics parse nó); prompt.
4. `tools.py` core (97 dòng); `trace.py:88-125` `_row`; `metrics.py:22` HEALTH; ADR-0023/0024; luật cấm 3.
5. Khung:
   ```python
   def _h(x) -> str          # sha256(json.dumps(x, sort_keys=True, ensure_ascii=False, default=str))[:12]
   OPAQUE_ARGS = frozenset({"content"})     # chỉ ghi "<n> ký tự"
   # ToolBox.call: đo ms bằng monotonic; vết thêm args_hash, out_hash (TRƯỚC khi cắt max_output), ms
   def ToolBox.trace(self, max_args: int = 200) -> list[dict]   # {i,name,args(cắt theo TỪNG giá trị),args_hash,out_hash,ok,chars,ms}
   # runner: sau tools_used → _audit("tools_trace", evidence={"turns","mode","calls": tools.trace()})
   # trace.py: act=="tools_trace" → row["sub"] = _gop_lap(calls); render in "    ↳ "; mode cli → "(tool do CLI chạy, không có vết)"
   ```
6. Mode `cli` không qua `ToolBox` → trace rỗng, phải nói ra. `sanitize_tool_output` sau `call` → `out_hash` trước
   lọc, ghi docstring. Studio runner riêng tới K3.6 — hai chỗ, K3.6 gộp. Không "thống nhất" `web_fetch`/`fetch_url`.
7. Test core: `cat_content_khong_lo_noi_dung`, `hash_on_dinh_khac_thu_tu_khoa`, `out_hash_truoc_khi_cat`,
   `clip_args_dai`. Company: `tools_trace_mot_lan_moi_luot`, `evidence_duoi_20k`, `mode_cli_khong_co_vet`,
   `render_gop_lap` (5 cùng hash → `×5`; 5 khác → không). Studio: `tools_trace_co_video_id`. Nghiệm thu:
   `COMPANY_LLM_PROVIDER=fake … run --max-steps 40` rồi `company.trace <T> | grep ↳`. CI ba package. PR
   `feat(core): 4L-2 — vết từng lời gọi tool vào audit, trace in được`.

### 4L-3 · Cắt vòng tool khi không tiến bộ

1. `_turns` (`runner.py:222-281`) chỉ dừng khi hết lượt / vượt budget / model tự dừng. Đo thật 2026-09-04:
   956.637 token output một ticket (`:230-242`).
2. `_stagnant` thuần 4 ca · `run test`×8 output cố định → dừng ở 5, audit `no_progress{n=5}`, vẫn có JSON cuối ·
   `run`×3 → `write_file` ok → `run`×3 → không cắt · tỉ lệ cắt trên bản ghi eval ghi vào PR kèm ngày.
3. Được: `runner.py` (`_turns`, hằng, `_stagnant`), `metrics.py` HEALTH, `tests/test_runner_no_progress.py`.
   Không: `supervisor.py`, `delivery.py`, prompt, `tools_prompt`.
4. `runner.py:222-281`; `TRAPS.md` §1 khuôn 3 (reset đếm theo tiến bộ, không theo lượt); 4L-2.
5. Khung:
   ```python
   NO_PROGRESS_WARN, NO_PROGRESS_STOP = 3, 5
   WRITING_TOOLS = frozenset({"write_file", "delete_file"})
   def _stagnant(calls: list[dict], window: int = 10) -> tuple[int, dict | None]
       # số call liên tiếp cùng (name,args_hash,out_hash) từ cuối, bỏ qua tool ĐỌC khác chen giữa; tool GHI ok → dừng đếm
   # trong _turns sau msgs.append(tool result): n==WARN → user turn "gọi <tool> n lần cùng tham số cùng kết quả…" + audit no_progress_warn
   #   n>=STOP → audit no_progress{tool,args_hash,n,turn}; stopped=True; break cả hai vòng → nhánh ép chốt (266-271) chạy như "hết lượt"
   ```
   Đếm theo CALL, không theo lượt. `read_file` cùng path 5 lần LÀ lặp. Không ném ở STOP.
6. Model chen `list_files` để phá chuỗi → chỉ tool ghi mới reset. Ngưỡng 3/5 là số đo có ngày (TRAPS §2).
7. Test: `stagnant_dem_dung`, `reset_khi_ghi_ok`, `khong_reset_khi_doc_chen`, `output_khac_khong_lap`,
   `lap_5_lan_thi_cat`, `stop_99_thi_chay_du` (ngược), `canh_bao_o_lan_3`, `ghi_file_xen_giua_khong_cat`,
   `no_progress_van_co_json_cuoi`. `grep -c` bản ghi có ≥ 5 call lặp → số vào PR. PR
   `feat(company): 4L-3 — cắt vòng tool khi không tiến bộ`.

### 4L-4 · Tỉa tool output cũ (ADR-0040, trong K3.6)

1. Trong `_turns` chỉ append; 6k × 25 lượt × N call; `max_input_chars` chỉ áp lượt đầu. Đổi hành vi agent → ADR.
2. ADR-0040 merge trước · `_prune(msgs, keep_turns=3)` thuần, audit `context_pruned{turn,dropped_chars}` · input
   lượt 10 < 3× lượt 1 trên fake 10×6k (tắt prune → đỏ) · token trước/sau trên eval ghi vào PR · bản ghi hai công ty
   ghi lại (hash user message đổi) — nói rõ trong PR, không phải bỏ bước.
3. Được: `xagents_core/runner.py`, `context.py` (`fit(messages_chars)`), shim, `evals/recordings/*` hai công ty,
   ADR-0040 (cấp repo, chạm ≥ 2 package). Không: prompt.
4. ADR-0020; `context.py:99-137`; 4L-2/4L-3 (nhãn cắt mang `out_hash` để model gọi lại được).
5. Giữ K=3 lượt gần nhất; message `role=tool` cũ hơn → `[đã cắt: <tool> <chars> ký tự, hash <h>; gọi lại nếu cần]`;
   `tool_calls` của assistant giữ; **không tỉa user message đầu** (chống trôi mục tiêu). K ≥ NO_PROGRESS_WARN.
   ```python
   def _prune(msgs: list[dict], keep_turns: int = 3) -> tuple[list[dict], int]   # thuần; gọi đầu mỗi vòng khi turn > keep_turns
   ```
6. Gọi lại sau tỉa không được tính lặp — 4L-3 đếm chỉ trong call chưa bị tỉa; thêm ca test phối hợp.
7. Test: `prune_giu_k_luot`, `khong_cat_duoi_k`, `giu_user_dau_va_tool_calls`, `input_luot_10_khong_qua_3x`,
   `goi_lai_sau_tia_khong_tinh_lap`. CI ba package; `make demo` ×2; eval replay ×2. PR
   `feat(core): 4L-4 — tỉa tool output cũ trong vòng tool (ADR-0040)`.

### 4L-5 · Đo vòng

1. Đặc tả L3 "cách đo": số vòng tới hội tụ, tỉ lệ chạm trần. `tools_used.turns` có, `metrics.py` chưa cộng.
2. `tools_used` thêm `capped`, `max_turns` · `metrics.collect()["loops"]` = {turns_p50, p90, max, capped_ratio,
   no_progress_ratio, retry_max_ratio, n, empty} · 6 gauge `company_loop_*` · console ô "vòng tool" rỗng → xám,
   module `static/js/loops.js`, ba câu hỏi ADR console-0003 trả lời trong PR.
3. Được: `runner.py:274-280`, `metrics.py`, `platform/console/src/console/{collect,truth}.py`, `platform/console/src/console/static/js/loops.js`,
   `index.html` một thẻ, `API.md`, tests. Không: schema; `tools_trace`; studio (dùng chung `company.metrics`).
4. `metrics.py:1-60,103`; console ADR-0003; `platform/console/CLAUDE.md` (thêm màn = HTML + một module); `test_hop_dong_schema.py`.
5. Percentile code thuần; `retry_max_ratio` = ticket `ticket.blocked` / ticket có `tasks`; `empty=True` khi n=0.
6. "Số xanh vì rỗng": capped_ratio=0 trên 0 lượt là rỗng, không phải tốt.
7. Test: 4 `tools_used` turns 3/5/25c/25c → p50=15, capped 0.5; bus rỗng → empty; console ô không bao giờ
   `ok=True` khi empty. `orchestrator metrics` in `loops`. PR `feat(company): 4L-5 — metrics vòng tool và tỉ lệ chạm trần`.

### 4L-6 · Studio validate trước rẽ nhánh (gộp K3.5b/c)

1. `ReviewSource`/`PublishEvent.status` đã Literal (`events.py:21,200,210`) nhưng orchestrator so chuỗi trên dict
   thô ở 4 chỗ (A2). Chạm `events.py` lúc K3.5b/c dời bus → cùng PR hoặc ngay sau.
2. `_rework`: `ReviewResult.model_validate` trước; `source:"FACT"` → không rework, audit lỗi · `_publish_video`:
   `PublishEvent` validate trước platform; `status:"live"` → platform giả KHÔNG được gọi · `StepResult.transient_agent/msg`
   có kiểu, msg chứa `:` không cắt sai · `trusted_decision(env)`: actor `human:x` nhưng `evidence.by=y` → bỏ + audit
   `gate.decide_untrusted` · bus SQLite cũ (SQL+JSON trong test) vẫn đọc được.
3. Được: `studio/{orchestrator,events,gate_cli}.py`, tests. Không: `ROUTES`, platform adapter, giá trị Literal mới.
4. `company/gate_cli.py:24-40` (mẫu `trusted_decision`), `scheduler.py:27`; K7.3 (hoãn — gói này là tiền đề,
   KHÔNG làm token); CHANGELOG K3.5a (fixture không commit `.sqlite`).
5. `ValidationError` ở nút → không nuốt: `agent_error_unhandled` → gate. `actions` chuỗi giữ cho log, không
   `split(":")` nữa. `trusted_decision` đặt ở `xagents_core.gates` nếu K3.7 xong, không thì tạm `studio/gate_cli.py`.
6. Khuôn 3 tái phát 2026-09-08 ở chính file này — khoá `once` mới mang thế hệ `video_id:retry`. Không thêm trường
   bắt buộc vào model (bus cũ phải qua).
7. `tests/test_orch_re_nhanh_theo_kieu.py`; `make demo` studio; CI. PR `refactor(studio): 4L-6 — rẽ nhánh trên model đã validate`.

### 4L-7 · Trace studio + `deferred` bền (sau K3.5c)

1. Company có `company.trace` (B7); studio không. `deferred/defer_until` studio chỉ RAM (`:284-291`), company đã
   vá (`rehydrate.py:122-144` `_nap_lai_hen`).
2. `xagents_core/trace.py` phần chung (`_row`, `render`, `_hms`, `_wait`), company import lại · `python -m studio.trace
   <VIDEO|PLAN-…|channel>` chỉ đọc, lạ → exit 1 · defer → đóng → mở → `deferred` có lại, `defer_until` ≥ cũ (bỏ
   nạp lại → đỏ) · `last_sync` KHÔNG sửa (cache, khác họ) — ghi trong PR.
3. Được: `xagents_core/trace.py`, `company/trace.py` (rút), `studio/trace.py`, `studio/orchestrator.py` (`_defer`
   ghi `event_id`, `_rehydrate` nạp lại), tests ba package. Không: `last_sync`; hình `defer.until` (chỉ thêm `event_id`).
4. `company/trace.py`; `rehydrate.py:122-144`; `studio/orchestrator.py:297-322`; ADR-0001 "company là gốc lên core".
5. `resolve` là hook theo miền, core không biết topic. Mở DB read-only. Nạp lại chỉ `defer.until` chưa có `orchestrated`.
6. Khuôn 5: không sort lại theo timestamp, duyệt `bus.replay()`. Khuôn 3: thế hệ = `event_id`, không phải `video_id`.
7. `test_trace_video.py` (6 pha → 6 dòng đúng thứ tự, gate `PUB-` có người/lý do), `test_deferred_song_sot_restart.py`.
   CI ba package; `make demo` studio → `studio.trace <VIDEO>`. PR `feat(studio): 4L-7 — trace một video và hẹn hoãn sống sót restart`.

### 4L-8 · Tài liệu (ngay)

1. Người đọc đặc tả hỏi "chốt duyệt tool đâu?"; `ARCHITECTURE.md` gốc ghi "Bốn package", không nhắc `xagents-core`;
   bảng K3 `DAC-TA-KICH-BAN-B.md:336-337` ghi "chưa" cho việc đã merge #173–#178.
2. `ARCHITECTURE.md` §"Ranh giới tin cậy" đoạn 4 dòng "không chốt mức tool — có chủ đích" trỏ A1.4 · sơ đồ + "Năm
   package" có `platform/xagents-core/` · bảng K3: c2–d xong (#173–#176), K3.4 xong (#177), K3.5a xong (#178), tách ba bước ·
   `archive/DAC-TA-NANG-CAP-2026-09.md:192` E3 nửa sau = 4L-1a/1b · test readme xanh.
3. Được: `ARCHITECTURE.md`, hai đặc tả. Không: `AGENTS.md`, `TRAPS.md`, mã, test.
4. `CHANGELOG.md` K3.5a; `git log --oneline` #173–#178 (số PR từ log, không từ trí nhớ).
5. Không thêm số chép tay; ADR-0040 chỉ ghi "dự kiến" (số ADR đặt trước là bẫy đã sập hai lần).
6. Bài học #168: sửa bảng K3 thì soát ô tương ứng ở NANG-CAP §8.
7. `pytest platform/console/tests/test_readme_goc.py companies/software-company/tests/test_review_fixes_2026_09.py -k readme`. PR
   `docs: 4L-8 — ranh giới tin cậy nói rõ vì sao không chốt mức tool; bảng K3 cập nhật`.

---

## D. Điều phối

**Phiên chính** cầm file này, không tự code: tách gói thành tiểu gói, giao subagent theo mức C1/C2/C3 (bảng B),
chạy song song những gì độc lập, tự làm phần không giao được (commit, PR, auto-merge, CI, nhật ký). Song song là
**song song phát triển** (mỗi tiểu gói một worktree). **PR mở tuần tự** — luật 2b "một PR mở tại một thời điểm":
gom tiểu gói của một gói vào một nhánh, mở PR, chờ merge, rebase nhánh kế rồi mới mở PR tiếp.

| Đợt | Song song (phát triển) | Thứ tự PR | Vào đợt khi |
|---|---|---|---|
| 1 | 4L-8 ∥ 4L-1a ∥ 4L-2 (không chạm cùng file) | 8 → 1a → 2 | — |
| 2 | 4L-3 ∥ 4L-5 ∥ 4L-1b (người, máy có key) | 3 → 5 → 1b | 4L-2 và 4L-1a merge |
| 3 | 4L-6 (hai tiểu gói Opus song song: rework+publish ∥ transient+trusted_decision) | 6 hoặc gộp PR K3.5c | K3.5b/c |
| 4 | 4L-7: rút core trước → (studio trace ∥ deferred) | 7 | K3.5c merge |
| 5 | ADR-0040 → `_prune` → ghép → đo + ghi lại eval (tuần tự hoàn toàn) | ADR → 4L-4 | K3.6, 4L-2, 4L-3, ngày có key |

Tiểu gói trong một gói, thứ tự cố định: **test đỏ** (Sonnet `medium` viết theo khung, dán output) → **code**
(mức theo bảng B; phần C3 của một gói là phần ghép vào runtime, phần thuần/parse/test là C2, phần đo/điền/CHANGELOG
là C1) → **test xanh + lệnh CI** (C1) → **`sc-*` chỉ đọc chấm** (`sc-qa` mọi gói code; `sc-security` khi chạm
tool/guard/gate: 4L-2, 4L-6; `sc-builder` khi chạm runner/core: 4L-3, 4L-4, 4L-7; `sc-ops` cho ô console 4L-5;
`sc-supervisor` cho ADR-0040) → phiên chính đọc diff → PR. Subagent không được bỏ ca test trong khung; muốn bỏ
phải nêu lý do để phiên chính quyết.

Khuôn giao việc: §4 của `docs/KHUON-THI-HANH.md`.

Báo cáo của subagent là **lời khai**: phiên chính chạy lại lệnh CI trong worktree trước khi commit (luật cấm 8).

---

## E. Khuôn nghiệm thu cho công ty mới

Công ty mới trên `xagents_core` điền bảng này **trước** gate đầu tiên với dữ liệu thật. "Lõi cấp" = nhận sẵn từ lớp
cơ sở của core; ô nào tự viết lại thay vì nhận từ lõi thì cần ADR nói vì sao.

| Lớp | Mục | Lõi cấp | Công ty tự khai | Bằng chứng máy sinh |
|---|---|---|---|---|
| L1 | 6 mục prompt, `version`, golden | `evals` (K3.6) | `agents/*.md`, `tests/golden/` | `make golden` sạch |
| L1 | Schema cho mọi topic ghi | `bus.validate` (K3.5b) | `topics/schemas/*.json` | publish sai → `BusError` |
| L1 | Eval ≥ 10 ca/agent, cổng chấm điểm | `evals` | `evals/*.yaml`, `thresholds.yaml` | replay `--strict` xanh **và** điểm ≥ ngưỡng |
| L1 | Prompt tĩnh ≤ 50% budget | `assetscan` | `budget_tokens_per_task` | `make assetbudget` |
| L2 | Tool tách đọc/ghi/chạy, allowlist, sandbox | `tools`, `sandbox` | bảng tool của miền | tool không cấp → không có trong bảng |
| L2 | Guard 2 chiều + sanitize tool output | `guard` (K3.4) | `CoreConfig.external_topics/derived_topics/untrusted_fields` | audit `injection_*` |
| L2 | Trần lượt, budget output, timeout, `tools_trace` | `runner` (K3.6) | `max_turns`, `budget_tokens_per_task` | `budget_exhausted`; `trace` in chuỗi tool |
| L3 | Kiểm bằng **code**, `verified_by` | mẫu `verified_by` | hàm kiểm của miền | `verified_by` không do model điền |
| L3 | Trần vòng + bỏ cuộc + không tiến bộ | `supervisor` (K3.7), `runner` | `max_retries`, chữ ký lỗi | `ticket.blocked` → gate; `no_progress` |
| L4 | Rẽ nhánh chỉ trên `Literal`/enum | `events` (K3.5a) | `ROUTES` + model miền | không có `== "` làm cạnh rẽ |
| L4 | Gate trước hành động không hoàn tác, four-eyes | `gates` (K3.7) | `GateKind` của miền | không gate → `PermissionError` |
| L4 | Mọi ngõ cụt mở gate | `supervisor` | — | ca test `agent_error_unhandled` |
| L4 | Trace CLI + rehydrate, không state chỉ RAM | `bus`, `sqlite_bus`, `trace` | `resolve`/`_rehydrate` của miền | mở lại bus → hàng đợi dựng lại đúng |
| L4 | Trần ngân sách dự án + chi phí phi-LLM | `Pricing` | giá media/API (kiểu S5) | `cost_usd`; 80/100% → warn/pause |

Ba quy tắc rút từ hai công ty đầu: **đi lên từ L1** (studio đi ngược, phải vá ở K3.3d/K3.4); **code kiểm được thì
không là gate**, bắt đầu ≤ 4 gate; **lời khai không là bằng chứng** từ ngày đầu (`unverified` = failed). ADR mới cho
route/loop ghi một dòng đầu: `Mẫu: <tên mẫu Anthropic> · Lớp: <1–4>`.

---

## F. Lệnh thi hành

```
/thi-hanh 4l                        # thi hành tới xong; chạy lại bất kỳ lúc nào tiếp từ chỗ dở
/thi-hanh 4l --dung-sau-ke-hoach    # chỉ in bảng B rồi dừng
```

Trước khi gõ (đo 2026-09-08): (1) nhánh `claude/llm-4-layer-architecture-vrupeq` chứa file này, khuôn và lệnh
`/thi-hanh` phải **merge vào `main`** trước — lệnh tạo worktree từ `origin/main`; (2) gõ ở phiên có `gh` CLI
(máy cá nhân), phiên remote không có `gh`; (3) sẽ `chờ người`: 4L-1b (key, `eval-record`), 4L-4 và đợt 3–5 (đợi
K3.5b/c, K3.5c, K3.6 merge) — lệnh tự ghi vào bảng B và dừng ở đó, chạy lại sau khi K3.x merge.

