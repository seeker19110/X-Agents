# xagents-core — luật riêng (bổ sung `../../AGENTS.md`, không thay)

Package `xagents_core`. Lõi chung mà `companies/software-company` và `companies/keeper` import thay vì tự fork:
bus sự kiện, client LLM, runner, chống prompt injection, human gate, blackboard, sandbox, quan sát được (span).
Danh sách module ở `CODEMAP.md` (có cổng canh); `docs/adr/0001-loi-chung-xagents-core.md` (gốc repo) là ADR khai
sinh. Package này **không có `docs/` riêng** — tri thức "vì sao" nằm trong docstring đầu mỗi module, đọc ở đó trước
khi hỏi.

## Chạy ở đâu

```bash
scripts/dev-task.sh gate core      # ở GỐC repo: ruff + mypy (strict lấy từ pyproject) + pytest --cov, khớp ci.yml
```

Không có CLI/daemon riêng — package chỉ là thư viện, không có `__main__.py` hay module nào chạy bằng `-m`.

## TDD ở package này

`../../AGENTS.md` luật bắt buộc 4 áp nguyên vẹn, siết chặt hơn các package khác: `mypy --strict` từ đầu (không
`--ignore-missing-imports` toàn cục — ngoại lệ hẹp duy nhất là `anthropic.*`), và `branch = true` +
`fail_under = 100` đã bật (không phải mục tiêu, đã đạt). Runtime chỉ 3 dependency thật (`observe.py` thuần
stdlib, `otel_sink()` import bên trong hàm, lùi về `NullSink` nếu thiếu) — thêm dependency mới vào lõi là quyết
định kiến trúc, cần ADR trước.

## Bốn điều không được phá

1. **`PersistentGate.trusted_decision` không tin `evidence.by`** — chỉ tin `env.actor` (ACL producer lúc
   publish). Lỗ hổng "tin lời khai trong evidence" đã bị vá 2 lần ở 2 chỗ khác nhau trước khi hai công ty hợp
   nhất về đây (`gate_cli.py`) — đừng mở lại đường tin `evidence.by`.
2. **`GateRequest.seq` là bộ đếm tăng dần, không dùng `created_at`** để phân biệt các thế hệ gate cùng
   `subject_id` — đồng hồ Windows có bước ~15,6ms, hai gate mở cách nhau dưới 16ms từng trùng khoá `once` và
   nuốt mất lần quá hạn thứ hai (`gates.py`).
3. **`ContainerSandbox` fail-closed và mạng tắt mặc định** (ADR-0010) — khai `container` mà máy thiếu binary
   phải ném `SandboxError`, không bao giờ âm thầm tụt về `SubprocessSandbox`. Git không đi qua sandbox.
4. **`RoutingClient`: mọi backend nghỉ hết → `TransientError`, không phải lỗi agent thường** — để orchestrator
   của công ty hoãn event thay vì tính là một lần thất bại; lỗi nội dung (JSON hỏng, model từ chối) không xoay
   backend, ném thẳng (`routing.py`).

Phụ, ít nghiêm trọng hơn nhưng vẫn có test khoá riêng: `blackboard.snapshot()` chỉ giữ **bản mới nhất** mỗi
`(project_id, namespace)` — không phải lịch sử; `observe.py` với `sink=None` phải là no-op tuyệt đối, không đọc
đồng hồ, không cấp phát (`test_sink_none_la_no_op_that_su` ném exception nếu `time.monotonic_ns` bị gọi).

## Sửa cái gì phải làm gì

| Sửa | Phải |
|---|---|
| Thêm provider LLM mới | Client cạnh `ClaudeCodeClient`/`OpenAICompatClient` trong `llm.py`; phân loại lỗi đúng 3 nhóm (quota/transient/auth) ở `routing.py` — không suy đoán bằng regex chung |
| Thêm loại gate mới | `GateKind`/`kind` là `str` ở core (`gates.py`) — công ty tự thu hẹp Literal ở lớp con, không thêm literal cứng vào đây |
| Đổi schema event | Sửa lớp con `Envelope`/`AuditLog` của TỪNG công ty, không sửa 5 lớp chung ở `events.py`. Trường mới chung cho cả hai công ty phải chứng minh cả hai miền cùng cần — nếu không là vi phạm "core không biết tên công ty nào" (`config.py`, ADR-0001 §2) |
| Thêm span quan sát mới | Thêm điểm gọi `Span`/`SpanSink` quanh ranh giới mới trong `observe.py`; giữ `sink=None` là no-op tuyệt đối, cha truyền qua `contextvars` (không biến toàn cục) |
| Đổi guard chống injection | Cơ chế (mẫu, chuẩn hoá, quét) ở `guard.py`; chính sách theo topic (từ chối/lọc) ở `CoreConfig` của công ty — hai lớp tách biệt có chủ ý |
| Đổi cách cắt ngữ cảnh | `context.py` (ADR-0012): system trừ trước, payload cắt-giữa có nhãn, blackboard water-filling theo namespace |
