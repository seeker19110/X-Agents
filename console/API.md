# Hợp đồng nội bộ của `console` (không phải tài liệu người dùng)

File này là hợp đồng giữa ba lớp của gói `console`. Đọc trước khi sửa bất kỳ lớp nào.
Xoá file này khi console đã ổn định và hợp đồng chuyển hết vào docstring + test.

## Lớp

```
collect.py   đọc SQLite bus của hai công ty + trạng thái gateway  → dict thuần
decide.py    ghi quyết định gate thật qua HumanGate của từng công ty
server.py    ThreadingHTTPServer stdlib, phục vụ static/index.html + /api/*
static/      trang console (đã có thiết kế, chỉ cần nối dữ liệu)
```

Không dùng framework web. Chỉ `http.server`, `json`, `sqlite3` và hai gói `company`,
`studio` qua path dependency.

## `collect.py`

```python
def collect(company_db: Path | None, studio_db: Path | None,
            gateway_token_file: Path | None = None,
            gateway_url: str = "http://127.0.0.1:8100") -> dict
```

Trả về đúng cấu trúc dưới đây. Mọi khoá luôn có mặt; thiếu dữ liệu thì trả list rỗng
hoặc `None`, **không ném lỗi** — DB không tồn tại là trạng thái bình thường (chưa chạy
công ty đó bao giờ).

```jsonc
{
  "generated_at": "2026-09-03T08:41:12+07:00",
  "sources": {                       // để trang báo phần nào đang trống và vì sao
    "software-company": {"ok": true,  "db": "software-company/company.sqlite", "events": 238, "error": null},
    "Studio-creators":  {"ok": false, "db": null, "events": 0, "error": "chưa có file DB"},
    "gateway":          {"ok": true,  "url": "http://127.0.0.1:8100", "error": null}
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
    "id": "PUB-vid-042", "xuong": "Studio-creators", "kind": "publish",
    "by": "desk", "trigger": "human:owner", "hours": 26, "sev": "over",   // over|warn|calm
    "title": "…", "facts": [["video_id","vid-042"], …],
    "cl": [["review:fact:pass","mô tả ngắn lấy từ checklist/evidence"], …]
  }],
  "tickets": [{"id":"TCK-112","st":"in_review","who":"backend","t":"…",
               "used":82400,"bud":120000,"est":78000,"retry":0}],
  "prs":     [{"id":"TCK-112","br":"…","s":"…","lint":"pass","tests":"pass","v":"workspace"}],
  "reviews": [{"id":"TCK-112","src":"security","v":"block","f":"block · …"}],
  "videos":  [{"id":"vid-039","st":"published","t":"…","fmt":"long","used":132000,"bud":150000}],
  "perf":    [{"id":"vid-039","imp":41200,"views":7840,"ctr":0.19,"avd":284}],
  "retention": {"video_id": "vid-039", "points": [[0,100],[15,88], …]},
  "cost_days": {"days":["21/8", …], "series":[[0.42,0.31,0.06], …]},  // [strong, standard, light]
  "agents":  [["backend", 4.82], …],                                   // giảm dần, tối đa 10
  "backends":[{"n":"claude-code","tiers":"strong · standard","tools":"có",
               "ok":true,"st":"Sẵn sàng","calls":128,"fail":2,"note":"…"}],
  "supervisor":[{"t":"TCK-118","a":"budget_cut","r":"…","w":"08:12"}],
  "log":     [{"t":"08:41","a":"backend","ac":"produced:pull-requests","k":"TCK-112","tok":8420,"c":0.21}]
}
```

Nguồn của từng phần:

| Phần | Lấy từ |
|---|---|
| `tiles`, `agents`, `cost_days`, `supervisor` | `supervisor.sprint_report()` + quét `audit-log` |
| `gates` | `gate.request` chưa có `gate.decide` tương ứng, tính `hours` từ timestamp |
| `tickets` | `tasks` + `TicketState` suy ra như `orchestrator.status()` |
| `prs`, `reviews` | topic `pull-requests`, `review-results` |
| `videos`, `perf`, `retention` | `video-briefs`, `performance-snapshots` |
| `backends` | `routing.status()` nếu đọc được `llm.yaml`, nếu không thì gateway `/auth/status` |
| `log` | `audit-log`, mới nhất trước, tối đa 200 bản ghi |

`hours` làm tròn xuống. `sev`: `over` khi ≥ 24 giờ (quá hạn), `warn` khi ≥ 12 giờ
(đến hạn nhắc), còn lại `calm` — khớp `GATE_TIMEOUT_H` / `GATE_REMIND_H` của repo.

## `decide.py`

```python
def decide(company_db: Path | None, studio_db: Path | None, *,
           subject_id: str, xuong: str, decision: str, by: str, reason: str) -> dict
```

- `xuong` ∈ `{"software-company", "Studio-creators"}` chọn DB và lớp `HumanGate` tương ứng.
- `decision` phải nằm trong `Decision` của công ty đó; sai thì `ValueError`.
- Gọi đúng `HumanGate.decide(...)` của công ty, **không tự dựng event**, để four-eyes,
  allowlist người duyệt và ghi audit đi qua đúng đường của repo.
- Trả `{"ok": true, "subject_id": …, "decision": …, "event_id": …}` hoặc ném
  `GateError` với thông điệp tiếng Việt để server đổi thành HTTP 4xx.

## `server.py`

```
GET  /                  → static/index.html, chèn <script>window.__CONSOLE__={token,readonly}</script>
GET  /static/*          → file tĩnh trong static/
GET  /api/state         → collect(...)
POST /api/gate/decide   → body {subject_id, xuong, decision, by, reason}
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
4. `--readonly` (mặc định **bật**) chặn mọi POST. Muốn duyệt gate từ trang thì chạy
   `--allow-decide`, và trang hiện rõ đang ở chế độ nào.
5. Không log token, không log body.

Lỗi trả `{"error": "…"}` kèm mã HTTP đúng nghĩa: 400 sai tham số, 401 sai token,
403 bị chặn, 404 không có, 409 gate đã quyết rồi, 500 lỗi không lường trước.

## `static/index.html`

Giữ nguyên thiết kế đang có. Đổi phần dữ liệu:

- Khi tải: gọi `GET /api/state`, hiện khung xám trong lúc chờ.
- Lỗi mạng hoặc 5xx: hiện dải cảnh báo trên cùng, giữ dữ liệu lần cuối đọc được.
- `sources[x].ok === false`: phần của xưởng đó hiện trạng thái rỗng có lý do, không hiện số 0 giả.
- Tự làm mới mỗi 10 giây, có nút tạm dừng; không làm mới khi ngăn kéo đang mở.
- Nút quyết định gate gọi `POST /api/gate/decide`; `readonly` thì nút bị khoá kèm giải thích
  cách bật `--allow-decide`.
- Không còn dữ liệu mẫu nào trong file.
