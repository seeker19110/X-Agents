# ADR-0009: quan sát được bằng span

Ngày: 2026-09-09 · Trạng thái: được chấp nhận · Mẫu: đo đạc tại chỗ (span lồng nhau quanh ranh giới có sẵn,
không đổi luồng điều khiển) · Lớp: 3

## Bối cảnh

Sáu package chạy song song, nhưng khi một ticket kẹt thì người vận hành chỉ có event log để đọc bằng mắt.
Số đếm được từ mã (không phải latency ước lượng — **latency chưa đo được, đó chính là vấn đề**):

- **Không có một dòng đo thời gian nào trong đường gọi model.** `grep -n "monotonic\|latency\|elapsed"` trên
  `platform/xagents-core/src/xagents_core/llm.py`, `companies/software-company/src/company/llm.py`,
  `platform/xagents-core/src/xagents_core/runner.py`, `companies/software-company/src/company/runner.py` trả **0 dòng**.
  `Completion` (`xagents_core/llm.py:206`) có `input_tokens`, `output_tokens`, `cached_input_tokens`,
  `cache_write_tokens`, `tool_calls`, `tool_mode` — **không có trường thời gian**. Một lời gọi model tốn bao lâu
  là thông tin không tồn tại ở bất kỳ đâu trong repo.
- **Thời gian duy nhất đang có là một con số phẳng, và chỉ của một công ty.** `Generated.duration_ms`
  (`company/runner.py:172`) là một trong **năm** trường riêng của company; `xagents_core.runner.Generated` (bảy
  trường chung) **không có nó**, studio cũng không ghi. `metrics.collect` (`company/metrics.py:39`) cộng nó thành
  `duration_ms_avg` cho cả một bước agent — không tách được "bước 40 giây này là 3 lời gọi model chậm hay 20 lời
  gọi tool".
- **Chỉ tool là đã có số đo mức lời gọi.** `ToolBox.call` (`xagents_core/tools.py:78`) ghi
  `ms = round((time.monotonic() - t0) * 1000, 1)` vào `self.calls`, và `ToolBox.trace()` (dòng 119) đưa nó ra
  audit `tools_trace` (4L-2). Đây là mức chi tiết cần có ở cả hai ranh giới còn lại, chứ không phải chỗ thiếu.
- **Một bước agent có thể là 25 lời gọi model.** `AgentRunner.generate` (`company/runner.py:406`) mặc định
  `max_turns: int = 25`, `_tool_loop`/`_turns` (dòng 268/285) lặp tới đó, mỗi lượt một `client.complete`. Cây
  "một bước → n lời gọi model → m lời gọi tool" là hình thật của runtime; không có gì trong repo dựng ra được nó.
- **Core có đúng 3 dependency runtime** (`jsonschema`, `pydantic`, `pyyaml`) và `strict = true` trong
  `[tool.mypy]`, với **một** ngoại lệ hẹp `ignore_missing_imports` cho module `anthropic.*` — cố ý không dùng cờ
  toàn cục `--ignore-missing-imports` như bốn package kia.
- **Có 12 hàm `def complete`** trong `platform/xagents-core/src`, `companies/software-company/src`, `Studio-creators/src`:
  core `llm.py` ×5 (dòng 474 là **khai báo** `Protocol`, bốn cái còn lại 545/618/675/792 là hiện thực),
  core `evals.py` ×3, core `routing.py` ×1, `company/llm.py` ×2, `studio/llm.py` ×1. Chúng **lồng nhau**:
  `make_client` (`company/llm.py`) dựng `_single_client` → `RetryingClient` → gói trong `Backend` →
  `RoutingClient`; `evals.py` bọc thêm `RecordingClient`/`ReplayClient` ở ngoài cùng.

`trace.py` (core và company) là cơ chế **post-hoc**: `trace.build(events, ...)` dựng bảng từ bus SAU khi việc
xong, trả lời "ticket này đã đi qua những bước nào, ai chờ ai". Nó không có, và không thể có, câu trả lời cho
"bước này tốn bao lâu ở đâu" — bus chỉ nhận sự kiện tại ranh giới publish, còn thời gian trôi bên trong một bước
không sinh sự kiện nào.

## Quyết định

Thêm một lớp span **thuần stdlib** ở `xagents-core` (`p3.1` sẽ tạo `xagents_core/observe.py` với `Span`,
`SpanSink` Protocol, và context manager `span(...)` — **đây là API sẽ có, không phải API đang có**), chèn tại
ba ranh giới ở phía gọi.

1. **Span sống song song với `trace.py`, không thay nó.** Hai cơ chế trả lời hai câu hỏi khác nhau và đọc từ hai
   nguồn khác nhau: trace đọc bus sau khi xong (nguồn: sự kiện đã publish, bền, có sau); span đo trong lúc chạy
   (nguồn: đồng hồ trong tiến trình, phù du, có ngay). Gộp là sai ở cả hai chiều: đẩy span vào bus biến mỗi lời
   gọi model thành một event bền (25 event rác cho một bước), còn bắt trace đo thời gian đòi nó chạy trong tiến
   trình sinh sự kiện chứ không phải trên bản ghi — mất đúng tính chất "đọc lại được từ event log" mà trace có.
2. **Đúng ba ranh giới: `runner.step`, `llm.complete`, `tool.call`.** Ba cái này là ba ranh giới **đã có tên
   trong mã** và có quan hệ cha–con thật (một `run`/`generate` chứa n lượt `complete`, một lượt chứa m `call`),
   nên cây span dựng ra khớp hình runtime mà không phải bịa cấp. Dừng ở ba vì cấp thứ tư (parse JSON, kiểm
   schema, ghi workspace) là chi tiết trong một hàm, không phải ranh giới giữa hai hệ; đo nó tốn nhiễu nhiều hơn
   tin. Riêng `tool.call`: `ToolBox.call` **đã có `ms`** — span ở đây không thêm số đo mới, nó thêm *liên kết cha*
   (lời gọi tool này thuộc lượt model nào, thuộc bước agent nào) và *đường phát tại chỗ*, hai thứ `self.calls`
   không có vì nó là bộ đệm phẳng chỉ đọc được sau khi vòng kết thúc.
3. **Chèn phía GỌI, không phía client.** `ModelClient` là `Protocol` (`xagents_core/llm.py:470`) với 12 hiện thực
   lồng nhau (routing → retry → recording/replay → adapter). Đặt span trong `complete` của client sinh **nhiều
   span cho MỘT lời gọi** — `RoutingClient.complete` gọi `RetryingClient.complete` gọi `AnthropicClient.complete`
   là ba span cho một lượt, và số span thay đổi theo cấu hình `backends:` chứ không theo việc thật sự làm. Chèn ở
   `company/runner.py:_complete` (dòng 248) và `_turns` (dòng 285) — nơi runner *quyết định* gọi model — cho đúng
   một span mỗi lượt, bất kể phía dưới có mấy lớp bọc. Hệ quả cố ý: thời gian retry và thời gian đổi backend nằm
   TRONG span, đúng như người vận hành cảm nhận.
4. **Core không thêm dependency bắt buộc: lớp span thuần stdlib + `SpanSink` Protocol; sink OpenTelemetry là tuỳ
   chọn, `import` bên trong hàm, thiếu gói thì lùi về no-op.** Vì `strict = true` ở core không đi kèm cờ toàn cục
   `--ignore-missing-imports`, một `import opentelemetry` ở đỉnh file làm mypy core đỏ trên mọi máy không cài gói
   — đúng cái bẫy đã ghi trong `platform/xagents-core/pyproject.toml` về `types-PyYAML`. Hai cách khác bị loại:
   (a) **thêm OTel làm dep bắt buộc** — nâng core từ 3 lên ≥ 4 dep runtime cho một tính năng mặc định tắt, và
   phá nguyên tắc "chỉ phụ thuộc thứ mà CẢ HAI công ty đã dùng" (ADR-0001 §2); (b) **không có lớp trừu tượng, gọi
   thẳng OTel** — buộc test core phải cài OTel để đạt `fail_under = 100`, và trói core vào một vendor trong khi
   "trung lập provider" là nguyên tắc của repo. `SpanSink` là cơ chế thuộc core; sink cụ thể (OTel, JSON ra file,
   in ra console) là *nghĩa* và thuộc package gọi — đúng khuôn "core giữ cơ chế, package giữ nghĩa" (ADR-0001).
5. **Mặc định là no-op, và no-op phải thật sự không tốn gì.** Không cấu hình sink thì `span()` không cấp phát,
   không đọc đồng hồ, không ghi gì; hành vi runtime **không đổi một chút nào** so với trước. Đây là quyết định
   riêng chứ không phải chi tiết hiện thực, vì nó là thứ cho phép ghép span vào đường nóng của cả sáu package mà
   không phải bảo vệ từng chỗ ghép bằng một cờ cấu hình riêng.
6. **Span KHÔNG được đổi nội dung gửi tới model.** Không thêm trường vào `system`/`user`/`messages`, không thêm
   header ảnh hưởng nội dung, không đổi thứ tự tham số của `complete`. Khoá bản ghi eval là `hash(system, user)`
   (ADR-0010): `TRAPS.md` đã ghi rằng thêm một dấu cách cũng đủ làm lệch, và ADR-0007 đã trả giá này một lần có
   chủ ý. Đây là ranh giới phân biệt hai gói: **`p3.1` (ghép span) không được ghi lại một bản ghi eval nào**; nếu
   một thay đổi đòi ghi lại eval thì nó thuộc `p3.2`, tách PR, tách lý do.

## Hệ quả

**Được.** Một bước agent kẹt đọc được thành cây: `runner.step` bao nhiêu giây, trong đó bao nhiêu lượt
`llm.complete` và lượt nào chậm, mỗi lượt bao nhiêu `tool.call` và tool nào chậm. `Generated.duration_ms` (một
số phẳng, chỉ company) trở thành tổng của các span con, và studio/keeper có cùng mức đo mà không phải chép năm
trường riêng của company. Lời khai "chậm ở model" hay "chậm ở tool" thành số đo, đúng luật cấm 8 của `AGENTS.md`.

**Mất.** Thêm một cơ chế thứ hai bên cạnh `trace.py`, nên có hai chỗ phải đọc khi tìm hiểu một sự cố — chấp nhận
vì hai câu hỏi khác nhau (quyết định 1). Mức đo chi tiết nhất chỉ có khi bật sink; bật sink thì trả giá bằng chi
phí sink đó (ghi file, gửi OTLP), và chi phí ấy nằm trong span cha nên số đo bước agent sẽ nhích lên so với khi
tắt. Cấu hình sink là mặt phẳng mới người vận hành có thể cấu hình sai.

**Giới hạn ĐÃ BIẾT, chấp nhận, không phải lỗi sẽ sửa sau.** Chế độ `cli` (ADR-0023 của software-company,
`Completion.tool_mode == "cli"`, `company/llm.py:449`) chạy vòng tool bằng tool RIÊNG của CLI, **không đi qua
`ToolBox`** — nên các lượt ấy sẽ **không có span `tool.call`**, chỉ có `llm.complete` bao trọn thời gian CLI làm
việc. Không có đường sửa trong phạm vi này: repo không quan sát được bên trong một tiến trình CLI của bên thứ ba.
`tool_mode` đã ghi sẵn trong audit (`company/runner.py:379`) nên người đọc span biết vì sao thiếu cấp con, không
phải đoán rằng đo hỏng.

Giới hạn thứ hai, **khác hẳn** giới hạn trên: đường **cầu MCP** (ADR-0024 của software-company). Ở đó tool VẪN chạy
thật trong `ToolBox` của tiến trình cha, nên span `tool.call` VẪN sinh ra với đủ `tool`/`ok`/`chars` — chỉ **liên kết
cha là mất**, span nằm phẳng thay vì dưới `llm.complete` của lượt sinh ra nó. Cơ chế: `ToolBridge` phục vụ bằng
`socketserver.ThreadingTCPServer` (`companies/software-company/src/company/mcp_bridge.py:93-96`) và gọi `toolbox.call` trong
**thread handler** (`mcp_bridge.py:120-123`); thread mới bắt đầu với một `contextvars` Context RỖNG, nên `_current`
của `observe.py` là `None` và `parent` cũng vậy. Khắc phục được — truyền `contextvars.copy_context()` từ luồng mở cầu
vào handler — nhưng **ngoài phạm vi `p3.1`**: nó đụng vào vòng đời của cầu, không vào ba ranh giới ADR này quyết. Hành
vi hôm nay được **đo** chứ không để tự hiểu:
`companies/software-company/tests/test_span_runner.py::test_cau_mcp_mat_cha_cua_span_tool_call` khẳng định `parent is None` qua
cầu và `parent is` span đang mở khi gọi cùng luồng — ai truyền context qua cầu sẽ thấy test đỏ và biết mình vừa đổi
đúng cái gì.

**Không thuộc phạm vi.** Streaming (chưa có trong repo), hiển thị span trên `console`, span cho `gateway` và
`Studio-creators`, và mọi thay đổi tới `metrics.prometheus`. ADR này quyết cơ chế và ba ranh giới ở core +
software-company; ghép nơi khác là quyết định riêng, ADR riêng nếu cần.

## Bổ sung 2026-10-10 (ib1-quansat): sink nối được bằng cấu hình

Đo trước khi sửa: ba ranh giới đã ghép span, nhưng `AgentRunner.sink` (`xagents_core/runner.py`) khởi tạo `None`
và **không chỗ nào gán** — nên ở mọi tiến trình thật, quyết định 5 (no-op) là trạng thái duy nhất có thể có, và
câu "latency chưa đo được" ở Bối cảnh vẫn đúng. Bổ sung: `AgentRunner` của software-company (`company/runner.py`,
nơi orchestrator, `evals` và CLI `runner` cùng dựng) đọc **một** khoá env `COMPANY_OTEL=1` → `self.sink =
otel_sink("company")`; không đặt → `None` như cũ; đặt mà thiếu OTel → `NullSink`
(quyết định 4 giữ nguyên: OTel do người vận hành cài, không vào `pyproject.toml` nào). Chọn env thay vì khoá trong
`llm.yaml` vì sink không phải cấu hình model — đi qua `LLMConfig` là thêm một tầng chỉ để chuyển một cờ; cùng khuôn
`COMPANY_GATE_REVIEWER`. Cùng lượt, `correlation_id` được nối ở hai chỗ còn tạo `Envelope` mới: `tasks`
(`DeliveryLead`, con của event nguồn kế hoạch) và PR người tiếp quản (`orch/worktree_flow.py`, con của PR/`tasks`
gần nhất); bản đồ cha `DeliveryLead.cause` được `orch/rehydrate.py` dựng lại từ `plan.proposed.source_event`, nên
ticket còn `waiting` qua lần khởi động lại vẫn nối chuỗi (test `..._song_sot_qua_restart` khoá điều này).

## Liên quan

- `docs/adr/0001-loi-chung-xagents-core.md` — "core giữ cơ chế, package giữ nghĩa" (§2 về dependency, §6 về core
  không được lỏng hơn nơi gọi nó) là nguồn trực tiếp của quyết định 4.
- `docs/adr/0007-tia-tool-output-cu-trong-vong-tool.md` — ví dụ đối chiếu: một thay đổi **có** đổi nội dung gửi
  model và **phải** ghi lại eval; quyết định 6 ở đây là cam kết ngược lại.
- `platform/xagents-core/src/xagents_core/tools.py` — `ToolBox.call` (đã có `ms`), `ToolBox.trace` (4L-2), bộ đệm `calls`.
- `platform/xagents-core/src/xagents_core/runner.py` — `AgentRunner.run`/`generate`/`publish`/`_audit`, `Generated`
  (bảy trường chung, không có thời gian).
- `companies/software-company/src/company/runner.py` — `_complete` (248), `_tool_loop` (268), `_turns` (285),
  `generate(max_turns=25)` (406): bốn chỗ ghép span của `p3.1`.
- `platform/xagents-core/src/xagents_core/llm.py` — Protocol `ModelClient.complete` (470), `Completion` (206).
- `platform/xagents-core/src/xagents_core/routing.py` — `RoutingClient.complete` (205), lớp bọc ngoài cùng của chuỗi lồng.
- `companies/software-company/docs/adr/0023-claude-code-cli-tools.md` — chế độ `cli`, nguồn của giới hạn đã biết ở trên.
- `companies/software-company/docs/adr/0024-cau-mcp-cho-claude-code.md` — cầu MCP, nguồn của giới hạn "mất cha" ở trên;
  `companies/software-company/src/company/mcp_bridge.py:93-96,120-123` là chỗ thread handler cắt `contextvars` Context.
- `companies/software-company/src/company/metrics.py` — `collect` (39), `prometheus` (154): nơi `duration_ms` hiện được cộng.
