# Hợp đồng nội bộ của `console` (không phải tài liệu người dùng)

File này là hợp đồng giữa ba lớp của gói `console`. Đọc trước khi sửa bất kỳ lớp nào.
Xoá file này khi console đã ổn định và hợp đồng chuyển hết vào docstring + test.

## Lớp

```
collect.py   đọc SQLite bus của software-company + keeper + trạng thái gateway  → dict thuần
truth.py     sự thật giao hàng của software-company: phễu release, quyết định chưa áp, bế tắc im lặng
decide.py    ghi quyết định gate thật qua HumanGate của từng công ty
server.py    ThreadingHTTPServer stdlib, phục vụ static/index.html + /api/*
static/      trang console (đã có thiết kế, chỉ cần nối dữ liệu)
```

Không dùng framework web. Chỉ `http.server`, `json`, `sqlite3` và hai gói `company`,
`keeper` qua path dependency.

## `collect.py`

```python
def collect(company_db: Path | None, keeper_db: Path | None = None,
            gateway_token_file: Path | None = None,
            gateway_url: str = "http://127.0.0.1:1123") -> dict
```

Trả về đúng cấu trúc dưới đây. Mọi khoá luôn có mặt; thiếu dữ liệu thì trả list rỗng
hoặc `None`, **không ném lỗi** — DB không tồn tại là trạng thái bình thường (chưa chạy
công ty đó bao giờ).

```jsonc
{
  "generated_at": "2026-09-03T08:41:12+07:00",
  // K7.5: phần mô tả HÌNH DẠNG dữ liệu dưới đây là bản rút gọn cho người đọc, KHÔNG phải nguồn sự thật.
  // Nguồn sự thật là `topics/schemas/*.json` của các công ty + hai test canh mối nối:
  //   `tests/test_hop_dong_schema.py`  — trường console đọc phải có trong schema (K7.4)
  //   `tests/test_es_module.py`        — mọi module được nạp, mọi tên nhập đều được export (K7.1)
  // Chỗ nào ở đây lệch với test thì TEST đúng. Xoá dần phần mô tả này khi test phủ hết.
  // Mọi trường payload console đọc từ các công ty đều bị `tests/test_hop_dong_schema.py` (K7.4) canh: nó quét
  // `collect.py`/`truth.py` và khẳng định từng tên có trong `topics/schemas/` của công ty. Đổi schema bên công
  // ty mà quên sửa console → test console ĐỎ, thay vì ô hiện rỗng mà không ai biết.
  "sources": {                       // để trang báo phần nào đang trống và vì sao
    "software-company": {"ok": true,  "db": "software-company/company.sqlite", "events": 238, "error": null,
                         "sandbox_available": true},   // K2.7: MÁY chạy console có docker/podman không
    "keeper":           {"ok": false, "db": null, "events": 0, "error": "chưa có file DB",
                         "sandbox_available": true},
    "gateway":          {"ok": true,  "url": "http://127.0.0.1:1123", "error": null}
  },
  "tiles": {
    "events": 238, "queue": 12, "model_calls": 45, "tool_calls": 27,
    "tokens": 71500, "project_budget_tokens": 1200000,
    "rework_rate": 0.25, "review_catch_rate": 0.6,
    "prs_unverified": 0, "cost_today_usd": 3.41, "tokens_today": 412000,
    "stuck_tickets": 2,
    "project_cost_usd": 18.74, "project_budget_usd": 40.0,
    "unpriced_calls": 12, "calibration": 1.18
  },
  "gates": [{
    "id": "REL-001", "xuong": "software-company", "kind": "release",
    "by": "delivery-lead", "trigger": "human:owner", "hours": 26, "sev": "over",   // over|warn|calm|signed
    "effect": "Duyệt = … (hậu quả của việc duyệt, theo kind; rỗng khi xưởng không nói)",
    "reject": "Từ chối = … (ticket/RC về đâu; rỗng khi xưởng không nói)",   // C2
    "agent":  "ops",                                                       // agent chạy lại sau khi duyệt; "" khi không biết
    "title": "…", "facts": [["ticket_id","TCK-112"], …],
    "cl": [["review:fact:pass","mô tả ngắn lấy từ checklist/evidence"], …],
    "decidable": true,     // false = câu hỏi làm rõ hoặc gate reviewer đã ký nhưng cờ tiến trình đọc tắt
    "reviewer_signed": {"decision":"approve","by":"reviewer:doc-lap"} // chỉ có khi chữ ký hợp lệ, cờ tắt; gate chưa áp
  }],
  "tickets": [{"id":"TCK-112","st":"in_review","who":"builder","t":"…",
               "used":82400,"out":9800,"bud":120000,"est":78000,"retry":0,   // used = tổng token; out = đầu ra (ngân sách so với out)
               "integrated":true,"sha":"b1b3e4b","human_hint":"","hint":"","gate":null,
               "ahead": 3,            // C7: commit của ticket/<id> CHƯA có trên nhánh tích hợp; null = không đo được ≠ 0 = đã gộp hết
               "pending_decision": {"id":"TCK-112","decision":"approve","by":"human:owner","kind":"escalation","minutes":14,"reason":"…"}
               }],                    // C3: chữ ký người đã ghi mà orchestrator chưa áp; null khi đã áp
  "prs":     [{"id":"TCK-112","br":"…","s":"…","lint":"pass","tests":"pass","v":"workspace"}],
  "reviews": [{"id":"TCK-112","src":"security","v":"block","f":"block · …","trim":"cắt api-contract 13.170 ký tự",
               "trim_src":[{"src":"api-contract","chars":13170},{"src":"payload","chars":804}],   // C5: từng nguồn bị cắt, hiện cạnh verdict
               "at":"04:07"}],
  "cost_days": {"days":["21/8", …], "series":[[0.42,0.31,0.06], …]},  // [strong, standard, light]
  "agents":  [["backend", 4.82], …],                                   // giảm dần, tối đa 10
  "backends":[{"n":"claude-code","tiers":"strong · standard","tools":"có",
               "ok":true,"st":"Sẵn sàng","calls":128,"fail":2,"note":"…"}],
  "product_funnel": [{"project_id":"QLKH",           // C1: một phễu cho MỖI sản phẩm; [] khi không đọc được xưởng
    "delivered": false,                                // lên production VÀ đã nghiệm thu
    "stages": [{"stage":"request","label":"Yêu cầu khách","n":1,"empty":false,"smoke":""},
               {"stage":"staging","label":"Staging (smoke)","n":1,"empty":false,"smoke":"ok"},   // ok|fail|unverified|""
               …]}],                                   // `empty` (n===0) → trang tô XÁM, không bao giờ xanh
  "silent_deadlocks": [{"kind":"ticket","id":"QLKH-010","state":"blocked","why":"…","integrated":true}],  // C4
  // S1 (ADR gốc 0023): lượt CHẠY MÃ CỦA KHÁCH trong 24h từ bằng chứng do code điền; `mode` là audit
  // `sandbox.mode` của lần khởi động gần nhất, không đọc cấu hình hiện tại. `subprocess` hiện cảnh báo gate
  // kể cả khi chưa có lượt chạy hoặc máy thiếu runtime. `null` khi xưởng không đọc được.
  "sandbox": {"window_h":24,"runs":12,"unsandboxed":9,"mode":"subprocess","by_name":{"subprocess":9,"container:python:3.12-slim":3},
              "last_at":"2026-09-07T03:11:28+00:00"},
  "supervisor":[{"t":"TCK-118","a":"budget_cut","r":"…","w":"08:12"}],
  "log":     [{"t":"08:41","a":"backend","ac":"produced:pull-requests","k":"TCK-112","tok":8420,"c":0.21}],
  // ---- sự thật giao hàng của software-company (console/truth.py) — null/[] khi xưởng không đọc được ----
  "delivery": {
    "releases_total": 19, "releases_live": 14, "void": 5, "production": 0, "delivered": 0,
    "latest_tag": null, "latest_release": null, "integration_sha": "d16289b", "integrated_tickets": 18,
    "funnel": [{"stage":"void","label":"Bị huỷ","n":5,"ids":["REL-009", …]}, …],   // đủ 15 bậc, thứ tự đi tới (ADR-0039 thêm hai bậc `*_deploy_failed`)
    "releases": [{"id":"REL-019","stage":"production_pending_human","label":"…","version":"0.11.1",
                  "tickets":["QLKH-012"],"sha":"964b704","gate":null,"at":"10:06","summary":"…","runbook":"…",
                  "next":"Agent tự dừng, KHÔNG gate nào mở: …"}]
  },
  // ADR-0021 §f (N3): nghiệm thu contract chất lượng, đọc `<db>.quality.sqlite` CHỈ ĐỌC (console/quality.py).
  // `null` = chưa ai ký profile nào (chưa có file journal) — trang hiện "không có profile", KHÔNG tự tạo file.
  // Có journal thì LUÔN là list, kể cả rỗng; độc lập với `sources.software-company.ok` (journal là nguồn riêng).
  "quality": [{"run_id":"RUN-2026-09-25-P1","status":"failed",   // trạng thái task `quality:accept` trong journal
               "checks_total":["lint","tests"],"checks_passed":["lint"],   // suy từ blockers `<check>:<lý do>` của lần chấm gần nhất
               "blocker":"tests:missing"}],                       // `RunState.blocked_reason` của core, "" khi không bị chặn
  "pending_decisions": [{"id":"REL-020","decision":"approve","by":"human:lead","kind":"escalation","minutes":12,"reason":"…"}],
  "running": {"queue": 7, "head": {"topic":"tasks","key":"TCK-…","minutes": 5}, "last_event_minutes": 1, "topics": ["tasks"]},
  "deadlocks": [{"kind":"ticket|release|idle","id":"QLKH-010","state":"blocked","why":"…","integrated":true}],
  // 4L-5: đo vòng tool (`company.metrics.collect()["loops"]`, đặc tả L3 "cách đo"). `empty=true` (không có
  // audit `tools_used` nào) → MỌI trường số khác là `null`, KHÔNG phải 0 — 0 thật (vd `capped_ratio: 0`) và
  // "chưa đo được" (`empty: true`) là hai trạng thái khác nhau, trang phải tô khác nhau (ADR-0003, xem `.tile.zero`
  // ở `static/index.html`). Chỉ xưởng phần mềm.
  "loops": {"turns_p50": 6.5, "turns_p90": 15.0, "turns_max": 25, "capped_ratio": 0.08,
             "no_progress_ratio": 0.0, "retry_max_ratio": 0.12, "n": 40, "empty": false},
  // BT8: công ty bảo trì `keeper`. `ran=false` (chưa cấu hình DB, chưa có file, HOẶC file có mà log rỗng) →
  // MỌI `cards[].v` là `null` và trang in `empty_note` thay cho số. `v: 0` chỉ xuất hiện khi `ran=true`, tức
  // là một số 0 THẬT. Bốn ô luôn có mặt, đúng thứ tự `KEEPER_KEYS`.
  "keeper": {"ran": true, "empty_note": "chưa chạy lần nào",
             "cards": [{"k": "Hàng đợi ticket", "v": 1, "n": "2 ticket bảo trì đã mở"}, …],
             "tickets": [{"id":"KT-1","subject":"docs/…","tier":"high","due":"…","gate":true,"st":"open"}],
             "debts": [{"subject":"…","reason":"…","due":"…","tier":"medium"}],
             "gates": [ … như `gates` ở trên, `xuong="keeper"` … ]}
}
```

Nguồn của từng phần:

| Phần | Lấy từ |
|---|---|
| `tiles`, `agents`, `cost_days`, `supervisor` | `supervisor.sprint_report()` + quét `audit-log` |
| `gates` | `gate.request` chưa có `gate.decide` tương ứng, tính `hours` từ timestamp; cộng `clarification-questions` chưa được `clarification-answers` trả lời đủ (`company.orch.guards.pending_clarifications`) |
| `tickets` | `tasks` + `TicketState` suy ra như `orchestrator.status()` |
| `prs`, `reviews` | topic `pull-requests`, `review-results` |
| `backends` | `routing.status()` nếu đọc được `llm.yaml`, nếu không thì gateway `/auth/status` |
| `log` | `audit-log`, mới nhất trước, tối đa 200 bản ghi |
| `delivery`, `pending_decisions`, `running`, `deadlocks` | `truth.py`: `release-candidates` + `release-events` + audit (`delivery.done`, `release.void`, `release.staged`, `integration.merged`, `orchestrated`, `gate.decide`) + `gate.pending/history` |
| `quality` | `console/quality.py`: `<db>.quality.sqlite` (ADR gốc 0021 §f), đọc bằng `RunSpec`/`ExecutionEvent`/`RunState` của `xagents_core.execution`, KHÔNG dùng `ExecutionJournal` (constructor của nó ghi/tạo file) |
| `tickets[].integrated/sha/human_hint/hint/gate`, `reviews[].trim/at`, `gates[].effect` | `truth.py` — sự thật git (merge commit), hint agent đang cầm, ngữ cảnh bị cắt khi chấm, hậu quả khi duyệt |
| `keeper` | `maintenance-tickets` + `debt-ledger` (`keeper.ledger.Ledger.overdue`) + `release-notes` + `PersistentGate` của `keeper`; hạn mức tuần từ `keeper.budget.max_pr_per_week()` (`KEEPER_MAX_PR_PER_WEEK`). Số PR đang mở THẬT là câu trả lời của `gh` — console không gọi `gh` nên không nói con số đó |
| `loops` | `company.metrics.collect(bus)["loops"]` — audit `tools_used` (`turns`, `capped`, `max_turns`) + `ticket.blocked` trên ticket có `tasks` |

`hours` làm tròn xuống. `sev`: `signed` khi reviewer đã ký hợp lệ nhưng cờ đọc tắt;
ngoài ra `over` khi ≥ 24 giờ (quá hạn), `warn` khi ≥ 12 giờ (đến hạn nhắc), còn lại `calm`.

## `decide.py`

```python
def decide(company_db: Path | None, keeper_db: Path | None = None, *,
           subject_id: str, xuong: str, decision: str, by: str, reason: str) -> dict
```

- `xuong` ∈ `{"software-company", "keeper"}` chọn DB và lớp `HumanGate` tương ứng.
- `decision` phải nằm trong `Decision` của công ty đó; sai thì `ValueError`.
- `by` phải là người (`human` / `human:<tên>`), ≤ `MAX_ACTOR_LEN` (80) ký tự, không ký tự điều khiển; sai thì
  `ValueError`. Cùng luật `actor_problem` áp cho `actor` của `submit.py` và `by` của `/api/engine`.
- Gọi đúng `HumanGate.decide(...)` của công ty, **không tự dựng event**, để four-eyes,
  allowlist người duyệt và ghi audit đi qua đúng đường của repo.
- Trả `{"ok": true, "subject_id": …, "decision": …, "event_id": …}` hoặc ném
  `GateError` với thông điệp tiếng Việt để server đổi thành HTTP 4xx.

## `submit.py`

```python
def submit(company_db: Path | None, keeper_db: Path | None = None, *,
           xuong: str, topic: str, payload: dict, actor: str) -> dict
```

- Giao việc = publish một event do NGƯỜI tạo vào bus SQLite của xưởng. `FORMS` liệt kê topic nạp tay được
  và trường payload làm `key`: software-company `research-requests` / `clarification-answers` (key `project_id`),
  keeper `maintenance-signals` (key `subject`) — cùng quy ước với CLI `publish` của từng công ty. `keeper`
  KHÔNG có form cho `maintenance-tickets`: ticket phải đi qua `triager` để có `risk_tier`
  (`keeper.core.HUMAN_TOPICS`).
- Đi qua đúng `SQLiteBus` + `Envelope` của công ty nên payload được kiểm theo `topics/schemas/<topic>.json`;
  bus từ chối → `SubmitError` (400) nguyên văn. Sai `xuong`/`topic`/`actor`/thiếu key → `ValueError` (400).
- File bus chưa có thì tạo (như CLI): yêu cầu đầu tiên của công ty chưa chạy lần nào là chuyện bình thường.
- Trả `{"ok": true, "xuong", "topic", "key", "event_id"}`.

## `server.py`

```
GET  /                  → static/index.html, chèn <script>window.__CONSOLE__={token,readonly,can_submit,can_engine}</script>
GET  /static/*          → file tĩnh trong static/
GET  /sw.js             → static/sw.js — PHẢI ở gốc, service worker chỉ điều khiển được
                          những đường trong thư mục chứa nó, mà nó cần điều khiển "/"
GET  /manifest.webmanifest → static/manifest.webmanifest (application/manifest+json)
GET  /api/state         → collect(...) + {"engine": {"engines": [...], "allowed": bool}}  (ADR-0004)
GET  /api/stream        → SSE: `event: state` mỗi khi bus đổi, `event: error` khi collect() ném,
                          `: ping` giữ nhịp 15 giây. Không có Content-Length; đóng kết nối là hết thân bài.
GET  /api/gate/brief    → ?id=<subject>[&xuong=software-company][&closed=1]
                          {"ok":true,"subject_id","kind","md"} — Markdown y hệt `python -m company.gate_brief <subject>`;
                          {"ok":false,"subject_id","error"} khi không dựng được (200, không phải 5xx).
                          CHỈ ĐỌC: không cần --allow-decide — đọc bằng chứng phải rẻ hơn ký (ADR-0003 §7)
GET  /api/settings      → settings.read_settings(...) + {"can_edit": bool}
POST /api/settings      → body {company, models?, prefer?, enable?, disable?}  (cần --allow-config)
POST /api/gate/decide   → body {subject_id, xuong, decision, by, reason}      (cần --allow-decide)
POST /api/request       → body {xuong, topic, payload, actor}                 (cần --allow-submit)
                          giao việc: submit.submit(...) publish event vào bus của xưởng, chỉ nhận
                          topic do người nạp (`submit.FORMS`); payload kiểm theo schema của topic
POST /api/engine        → body {xuong, action: "start"|"stop", by, interval?}  (cần --allow-engine)
                          bật/tắt `orchestrator run --watch` của xưởng; `interval` giây, kẹp [5, 3600],
                          mặc định `DEFAULT_ENGINE_INTERVAL` = 30. Trả trạng thái sau thao tác.
                          409 khi bật cái đang chạy / tắt cái không chạy; 400 tham số sai; 500 không spawn được
GET  /healthz           → {"ok": true}
```

Bảo mật — bắt buộc, đây là bề mặt đầu tiên cho phép duyệt gate qua HTTP:

1. Chỉ bind loopback. `--host` khác `127.0.0.1`/`::1` thì **từ chối khởi động**, trừ khi
   có cờ `--i-know` kèm cảnh báo in ra.
2. Mọi `/api/*` yêu cầu header `X-Console-Token` khớp token phiên. Token sinh ngẫu nhiên
   bằng `secrets.token_urlsafe(32)` mỗi lần chạy, ghi `console/.console-token` quyền 0600,
   và chèn vào trang. Không có token hợp lệ → 401.
3. Chống DNS rebinding: từ chối request có `Host` không phải loopback (404), và từ chối
   `Origin` khác `http://127.0.0.1:<port>` (403). Token nằm ở header chứ không phải cookie
   nên trang ngoài không giả mạo được POST.
4. Bốn quyền ghi TÁCH RIÊNG, không cái nào mở cái nào: `--allow-decide` cho `/api/gate/decide`,
   `--allow-config` cho `POST /api/settings`, `--allow-submit` cho `POST /api/request`,
   `--allow-engine` cho `POST /api/engine`. Duyệt gate, đổi model, giao việc và bật động cơ là bốn rủi
   ro khác nhau — `--allow-engine` nặng nhất: nó tạo tiến trình con gọi model và ghi vào repo khách.
5. `--readonly` (mặc định **bật**) chặn mọi POST. Muốn duyệt gate từ trang thì chạy
   `--allow-decide`, và trang hiện rõ đang ở chế độ nào.
6. Không log token, không log body. Vì `log_message` ghi nguyên dòng request, token **không được**
   đi qua query string — đó là lý do trang đọc `/api/stream` bằng `fetch` + `ReadableStream`
   (đặt được header) chứ không phải `EventSource` (không đặt được).

Lỗi trả `{"error": "…"}` kèm mã HTTP đúng nghĩa: 400 sai tham số, 401 sai token,
403 bị chặn, 404 không có, 409 gate đã quyết rồi, 500 lỗi không lường trước.

## `engine.py`

```python
class EngineManager:
    def status(self) -> dict            # {"engines": [{xuong, label, db, configured, state, pid, ...}]}
    def fingerprint(self) -> str        # đổi khi động cơ bật/tắt/chết → /api/stream đẩy khung mới
    def start(self, xuong, *, interval: float, by: str) -> dict
    def stop(self, xuong, *, by: str) -> dict
    def stop_all(self) -> None          # chạy ở server_close() và atexit
```

- Một động cơ = một tiến trình con chạy đúng CLI mà người vẫn gõ: company
  `python -m company.orchestrator --db <db> run --watch <N>`, keeper `python -m keeper.cli watch --db <db>
  --repo <repo> --interval <N>`. Dòng lệnh dựng từ `SPECS` chốt cứng trong mã nguồn — **không tham số nào của
  client đi vào `argv`** ngoài `interval` đã kẹp; không `shell=True` (ADR-0004).
- `state` là thứ ĐO ĐƯỢC mỗi lần hỏi (`Popen.poll`): `running` | `stopped` (chưa bật trong phiên console
  này) | `exited` (đã chạy và đã kết thúc — kèm `exit_code`, `stopped_by` nếu do người tắt, và `tail` là
  ~12 dòng cuối của `console/.engine/<xuong>.log`). Không có trạng thái nào suy từ "đã bấm Bật".
- Động cơ do console bật **chết cùng console**; console không thấy orchestrator do người bật ở terminal.
- Model dùng gói thuê bao trong `llm.yaml` của công ty (tiến trình con thừa kế env của console) — console
  không truyền model, không truyền API key.

## `settings.py`

```python
def read_settings(paths: dict[str, Path] | None = None, gateway_url: str = ...) -> dict
def update_settings(path: Path, *, models=None, prefer=None, enable=None, disable=None) -> dict
```

- **Mặc định = hiện trạng.** Không có bảng giá trị mặc định riêng: cái đang nằm trong `llm.yaml` là cái hiển thị.
- **Tắt backend phải tắt thật.** `company.llm.load_config` bỏ qua khoá lạ nên `enabled: false` vô tác dụng;
  tắt = chuyển phần tử sang `disabled_backends:` (loader không đọc), bật = chuyển ngược.
- `prefer` trỏ vào backend đang tắt bị bỏ, ghi rõ trong `changes` — để trống thì router chọn hụt.
- Validate xong mới ghi (đổi trọn hoặc không đổi gì); ghi nguyên tử, để lại `llm.yaml.bak`.
- `catalog` lấy từ `GET <gateway>/v1/models`; gateway tắt → rỗng và **không** cảnh báo tên model, vì backend
  `claude-code`/`codex` vốn không đi qua gateway.
- Không có file → `ok: false` kèm lý do, không ném lỗi.

## `static/index.html`

Một file, không framework, không bước build. Phần dữ liệu:

- Khi tải: hiện khung xám, rồi nối `GET /api/stream`.
- **Đẩy trước, hỏi sau.** Có stream thì trạng thái mới về trong khoảng một giây (nhãn *trực tiếp*).
  Stream đứt → lùi về `GET /api/state` mỗi 10 giây (nhãn *hỏi lại 10s*) và thử nối lại với backoff
  gấp đôi, trần 60 giây. Mất stream chỉ là chậm hơn, không phải hỏng.
- **Không vẽ đè dưới tay người đang đọc.** Ngăn kéo đang mở hoặc đã bấm Tạm dừng thì trạng thái mới
  được giữ lại và hiện nút *Có dữ liệu mới — xem*; bấm mới vẽ.
- Lỗi mạng hoặc 5xx: hiện dải cảnh báo trên cùng, giữ dữ liệu lần cuối đọc được.
- `sources[x].ok === false`: phần của xưởng đó hiện trạng thái rỗng có lý do, không hiện số 0 giả.
- Nút quyết định gate gọi `POST /api/gate/decide`; `readonly` thì nút bị khoá kèm giải thích
  cách bật `--allow-decide`.
- Khối **Giao việc** ở đầu màn Xưởng phần mềm: form yêu cầu phần mềm (kèm nơi lưu dự án `repo`/`base`,
  ADR-0025 của công ty) và trả lời câu hỏi làm rõ. Hai form = hai topic trong `submit.FORMS`. Trang chỉ gom
  trường thành payload đúng hình schema (danh sách: mỗi dòng một mục; trả lời: `question_id: nội dung`), gọi
  `POST /api/request`; `can_submit` false thì nút khoá kèm cách bật `--allow-submit`. Gửi xong hiện key + event id.
- Không còn dữ liệu mẫu nào trong file.

Vỏ PWA — `manifest.webmanifest` + `sw.js`, để trang cài được thành app có cửa sổ riêng.
Service worker **không bao giờ** cache `/api/*` (dữ liệu sống; `/api/stream` là luồng không kết thúc,
cache là treo) và **không bao giờ** cache `/` (HTML mang token phiên, token đổi mỗi lần chạy server).
Chỉ icon được cache. Icon sinh lại bằng `uv run python tools/make_icons.py` (stdlib, không Pillow).

Điều hướng — địa chỉ là trạng thái (ADR-0011 §5 giai đoạn 5/5: sáu màn "thông tin" — `truc-ban`, `phieu`,
`phan-mem`, `bao-tri`, `chi-phi`, `nhat-ky` — nay LUÔN hiển thị cùng lúc trên một trang cuộn dài; `<màn>` chỉ
còn quyết định nav cuộn tới đâu và tiêu đề nào hiện ở đầu trang, KHÔNG còn ẩn/hiện section. `cai-dat` và
`huong-dan` không đổi):

```
#/<màn>                     truc-ban | phieu | phan-mem | bao-tri | chi-phi | nhat-ky | cai-dat | huong-dan
#/<màn>/gate/<id>           cuộn tới màn đó, ngăn kéo gate đang mở
#/<màn>/ticket/<id>         ngăn kéo ticket
```

Dùng hash chứ không `history.pushState`: server chỉ phục vụ một đường `/`, đẩy đường dẫn thật vào
thanh địa chỉ thì F5 ăn 404. Back đóng ngăn kéo thay vì rời trang; địa chỉ trỏ tới id không còn tồn
tại thì tự rút về màn tương ứng, không để thanh địa chỉ nói dối.

Lọc, tìm, sắp xếp — hoàn toàn phía client trên dữ liệu đã có, không thêm vòng gọi server nào:

- Ô tìm chung (phím `/`) lọc gate, ticket, PR, review, số liệu và audit-log cùng lúc.
  Gấp dấu tiếng Việt bằng NFD; chỗ khớp được tô khi gõ có dấu.
- Bảng ticket có chip lọc theo trạng thái kèm số đếm; chọn một trạng thái thì thu về một cột.
- `<th data-k>` trong `<tr data-sort>` sắp xếp được, `data-t="n"` là cột số. Trạng thái sắp xếp nằm
  ở `aria-sort` nên đọc màn hình cũng biết.
- Phím tắt: `/` vào ô tìm, `1`–`8` nhảy màn (theo thứ tự `VIEWS` trong `static/js/router.js`), `g` về Trực ban,
  `Esc` xoá ô tìm hoặc đóng ngăn kéo.
