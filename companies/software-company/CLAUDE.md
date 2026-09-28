# software-company — luật riêng (bổ sung `../../AGENTS.md`, không thay)

Package `company`. Công ty gia công phần mềm: 6 agent (5 công đoạn + supervisor), 45 skill, 19 topic, 3 human gate + escalation, code thật
trên git worktree của repo khách, giao hàng bằng tag + nhánh `company/release`.

## Chạy ở đâu

Mọi lệnh **trong thư mục này** (gốc hub có `company.sqlite` rỗng → `status` nhìn như không có gì):

```bash
../../scripts/dev-task.sh gate company   # ruff + mypy + pytest -n auto --cov, khớp đúng ci.yml
                                         # (Windows thiếu 2 dòng POSIX trong coverage là bình thường)
uv run python -m company.orchestrator status | diagnose | metrics
uv run python -m company.orchestrator --repo <repo khách> run --watch     # tự khởi động lại khi mã đổi
uv run python -m company.gate_cli list | approve <subject> --by human:<tên> --reason "<root_cause — decision — hint>"
```

## TDD ở package này

`../../AGENTS.md` luật bắt buộc 4 áp nguyên vẹn: viết test đỏ trong `tests/` trước, chạy
`uv run pytest -q -n auto --cov -k <tên test>` thấy đỏ đúng lý do, rồi mới viết code trong `src/company/` cho nó
xanh. `fail_under = 100` (luật cấm 6) nghĩa là code mới không có test đi trước sẽ tự lộ ngay ở bước coverage.

## Ba ranh giới không được phá

1. **Model chỉ khai, code mới chứng.** `local_checks.verified_by=workspace` (PR), `smoke.verified_by=orchestrator`
   (release), identity của event (`env`, `release_id`, `ticket_id`) từ ROUTE. Thêm trường "đã làm được" mới → code
   điền, không phải prompt dặn.
2. **Tool có ranh giới** (`src/company/tools.py` + `workspace.py`): allowlist `run`, khoá đường dẫn, lọc env `SECRET_ENV`, không hook
   git (`NO_HOOKS`). Nới tool = thêm test ranh giới, không chỉ thêm lệnh.
3. **Bản dẫn xuất không sửa tay**: `tests/golden/` (`make golden`), `../../.claude/agents/sc-*.md` (`make subagents`),
   `evals/recordings/` (`make eval-record AGENT=<id>` với model thật).

## Sửa cái gì phải làm gì

| Sửa | Phải |
|---|---|
| `agents/`, `skills/` | 7 bước `../../CONTRIBUTING.md` §3 — tăng version, golden, eval-record, assetscan, assetbudget, subagents |
| `topics/schemas/*.json` | đổi model Pydantic trong `src/company/events.py` cùng lúc; `tests/test_schema_consistency.py` |
| `gates/checklists.md` | khai nguồn bằng chứng ở `src/company/gate_checklists.py` trước, rồi `make subagents` |
| `ROUTES` trong orchestrator | front matter `reads`/`writes` của agent khớp; bảng Consumer ở `docs/architecture.md` |
| thêm file `tests/*.py` hoặc `docs/adr/*.md` | sửa số ca/file test và "ADR 0001–00xx" trong `README.md` — test đếm từ đĩa |
| kiến trúc, agent mới, schema | ADR trong `docs/adr/` trước, số kế tiếp |

## Đọc thêm

`ARCHITECTURE.md` (bản đồ, trỏ `docs/architecture.md`), `CODEMAP.md` (muốn đổi X sửa ở đâu), `TRAPS.md` (bẫy riêng
của package này), `docs/dac-ta-tro-ly-kiem-duyet.md` (trợ lý `sc-*`), `docs/reports/` (chuyện đã xảy ra thật).
