# ARCHITECTURE.md — xagents-core

```
companies/software-company, companies/keeper, platform/console
        │  import xagents_core.*  (27 + 15 + 3 file trong src/, đo 2026-09-28)
        ▼
┌─────────────────────────────── platform/xagents-core ───────────────────────────────┐
│  events.py (Envelope/AuditLog/SharedContext — 5 lớp chung, lớp con công ty thu hẹp)  │
│  config.py (CoreConfig/TopicACL — chỗ DUY NHẤT core biết một công ty khác ở đâu)     │
│                                                                                       │
│  bus.py / sqlite_bus.py ── ACL + validate schema + bền vững trên đĩa                 │
│  execution.py ── RunSpec/TaskSpec → state machine → evidence → SQLite journal          │
│  runner.py ── AgentRunner: build prompt → gọi model → tool loop → ghi audit          │
│       │            │             │                                                  │
│       ▼            ▼             ▼                                                  │
│  guard.py    llm.py/routing.py  tools.py    sandbox.py (tiến trình con, mạng tắt)    │
│  (injection) (client + xoay backend)  (ranh giới tin cậy)                            │
│                                                                                       │
│  blackboard.py (tri thức chung) · context.py (cắt ngân sách token, ADR-0012)         │
│  gates.py/gate_cli.py (human gate + PersistentGate) · registry.py (nạp agent/skill)  │
│  observe.py/trace.py (span, dòng thời gian) · evals.py (ghi/phát lại) · supervisor.py│
└───────────────────────────────────────────────────────────────────────────────────────┘
        │  Backend LLM thật (Claude CLI, OpenAI-compatible, gateway HTTP)
        ▼
platform/gateway (proxy) hoặc provider trả phí trực tiếp
```

## Bốn quyết định giữ hình dạng này

| Quyết định | Ở đâu |
|---|---|
| Core không biết tên công ty nào — mọi thứ đặc thù một công ty sống ở lớp con, không ở đây | ADR-0001 §2 (`docs/adr/0001-loi-chung-xagents-core.md`, gốc repo) |
| Chỉ 3 dependency runtime; `observe.py` thuần stdlib, OTel là lựa chọn import bên trong hàm | ADR-0009 |
| `mypy --strict` từ ngày đầu, không nới bằng `--ignore-missing-imports` toàn cục | `pyproject.toml` |
| `PersistentGate` không tin `evidence.by`, chỉ tin `env.actor` (ACL producer) | `gate_cli.py`, vá 2 lần độc lập trước khi hợp nhất |

## Ranh giới với phần còn lại của hub

- **Vào**: hai công ty import trực tiếp (không qua HTTP) — đây là thư viện Python, không phải service.
- **Ra**: `llm.py`/`routing.py` gọi model qua CLI (`claude -p`) hoặc HTTP OpenAI-compatible — có thể trỏ vào
  `platform/gateway` hoặc thẳng provider trả phí, core không phân biệt.
- **Đĩa**: `sandbox.py`/`sqlite_bus.py` giữ state runtime cũ; từ ADR-0017, `ExecutionJournal` ghi append-only
  khi harness được bật. File journal là state vận hành do caller chọn đường dẫn, không phải artifact Git.
- **Test**: số ca hiện tại ở dòng xagents-core trong `README.md` gốc (có cổng canh); `branch=true` +
  `fail_under=100` đã bật từ ngày đầu, không phải mục tiêu đang tới.
- **Tài liệu**: package này không có `docs/` riêng — ADR gốc `0001` ở `docs/adr/` cấp repo; mọi "vì sao" khác
  nằm trong docstring module, đọc trực tiếp thay vì tìm file riêng.

Lịch sử: tách ra từ hai bản trùng lặp gần như y hệt giữa `software-company` và `studio` (khi studio còn trong
repo này) qua bảy bước K3.1–K3.7 — mỗi bước dời một mảng dùng chung về đây, đối chiếu hành vi hai bản trước khi
xoá bản trùng. `Studio-creators` đã tách sang repo riêng ở #259; xagents-core ở lại vì `keeper` vẫn dùng.
