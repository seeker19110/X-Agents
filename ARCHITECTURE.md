# ARCHITECTURE.md — bản đồ hệ thống X-Agents

Đọc để biết **thứ gì nằm ở đâu và vì sao**. Chi tiết từng package: `<pkg>/ARCHITECTURE.md`. Muốn đổi một thứ cụ
thể: `CODEMAP.md`.

## Bức tranh lớn

```
                       ┌──────────────── platform/console/ (127.0.0.1:8200) ────────────────┐
                       │  đọc bus SQLite chỉ-đọc của công ty; duyệt gate qua       │
                       │  đúng HumanGate; giao việc qua đúng bus + schema           │
                       └────────────────────────────┬───────────────────────────────┘
                                                     │
                       ┌─────────────────────────────▼─────────────────────────┐
                       │ companies/software-company/  (package company)                  │
                       │ 6 agent · 45 skill · 19 topic                        │
                       │ 3 human gate + escalation                             │
                       │ code thật trên git worktree của khách                 │
                       └────────────────────────────┬───────────────────────────┘
                                                     ▼
                    platform/xagents-core/  (package xagents_core)
                    lõi chung: bus, llm, runner, guard, gate, execution state/journal, trace, metrics, context, sandbox
                                   ▲
                    ┌──────────────┴───────────┐
                    │  llm.yaml: backends      │
        claude-code CLI · codex CLI · platform/gateway/ (127.0.0.1:1123, xoay tài khoản Google) · model local · API
```

Bố cục thư mục (ADR-0011) tách theo vai trò: `platform/` (`xagents-core`, `gateway`, `console`) là hạ tầng dùng
chung không thuộc công ty nào; `companies/` (`software-company`, `keeper`) là các công ty có agent, topic, gate và
khách riêng. `gateway` và `console` KHÔNG nằm trong một công ty vì cả hai phục vụ nhiều hơn một công ty.

Năm package là năm thành viên của một **uv workspace** — một `.venv`, một `uv.lock`. Không có `[project.scripts]`:
mọi entry point là `python -m <package>.<module>`. Repo khách nằm **ngoài** repo này (`--repo <đường dẫn>`).

## Kiến trúc chung của một "công ty"

```
topic (JSON Schema, có key) ──► registry: agent nào nhận topic nào
        │                              │
        ▼                              ▼
   sqlite_bus ◄──── orchestrator ──► runner (vòng lặp tool, guard, cắt ngữ cảnh) ──► routing → llm (adapter từng gói)
        │                 │
        │                 ├── human gate: chờ người duyệt (gate_cli / console)
        │                 └── supervisor: watchdog, ngân sách token, bài học
        ▼
   blackboard (artifact store, namespace theo owner) + audit-log (token thật, chi phí USD)
```

Năm nguyên tắc, mỗi cái có chỗ cắm trong code:

| Nguyên tắc | Nghĩa là | Ở đâu |
|---|---|---|
| **Model quyết định – code hành động** | tính toán, kiểm định, render, deploy, đăng… là code xác định; model chỉ trả JSON | `tools.py`, `workspace.py`, `smoke.py` (company) |
| **Prompt là code** | agent/skill có `version`, golden test, eval ghi/phát lại chạy trong CI không gọi model | `agents/*.md` front matter, `tests/golden/`, `evals/recordings/` |
| **Guardrail có hạn mức** | ngân sách token, retry, timeout đều có ngưỡng; hết ngưỡng → escalate, không đi tiếp | `supervisor.py`, `guard.py`, `context.py` |
| **Self-hosted, resume được** | bus SQLite + execution journal; dừng và chạy tiếp, state dựng lại từ log thay vì context | `sqlite_bus.py`, `execution.py`, `_rehydrate` trong orchestrator |
| **Trung lập provider** | đổi model bằng `llm.yaml`/env, không đổi code hay prompt | `llm.py`, `routing.py`, `docs/DIEU-PHOI-MODEL.md` |

## Ranh giới tin cậy (quan trọng nhất để không tự lừa mình)

Mọi trường mang nghĩa "đã làm được" phải do **code** điền, không phải model:

- PR: `local_checks.verified_by=workspace` — lint/test chạy thật trong worktree (ADR-0010, ADR-0013).
- Release: `release-events.smoke.verified_by=orchestrator` — sản phẩm được khởi động thật, gọi một request thật
  (ADR-0029).
- Identity của event (`env`, `release_id`, `ticket_id`) lấy từ ROUTE, model lệch thì `*_overridden` (#72, #75).

**Không chốt duyệt mức tool — có chủ đích**: thay bằng "không cấp tool thì không có hành động" (`allow_write/allow_run/write_scope`, sandbox, bốn gate công đoạn). Chi tiết: `docs/KIEN-TRUC-4-LOP.md` §A1 mục 4 (A1.4).

Còn lại là lời khai — hữu ích, nhưng chỉ ký gate trên bằng chứng.

## Human gate

| Công ty | Gate | Gác cái gì |
|---|---|---|
| software-company | `spec` → `release` → `acceptance` (+ `escalation`) | PRD; production; khách ký UAT (kế hoạch ticket do `_check_plan` chặn bằng code, không còn gate `plan` từ ADR-0037) |
| keeper | `patch` (BT7 đã merge: `KeeperOrchestrator.ensure_gate` là nơi gọi duy nhất; `release`/`escalation` khai trong `GateKind` nhưng chưa nơi nào mở; chưa qua chu kỳ thật — chờ canary BT8) | patch rủi ro cao: semver major, chạm `xagents-core`/`agents`/`.github`, security ≥ high |

Gate là thật: hạn 24h, nhắc 12h, quá hạn escalate, four-eyes (người duyệt ≠ người tạo; allowlist người duyệt
`COMPANY_GATE_APPROVERS` mặc định tắt). Mỗi gate của software-company có trợ lý kiểm duyệt
chỉ đọc `sc-gate-<kind>` và hồ sơ bằng chứng `gate_brief`.

## CI (`.github/workflows/`)

Bốn workflow. Required check của `main` (`.github/rulesets/main.json`) là **`quality`** và **`metadata`** — tên bất
biến, đổi tên là khoá cửa merge. Trên máy, `scripts/dev-task.sh gate <gói>` chạy đúng lệnh của cặp job
`*-static`/`*-unit` của gói đó. Mục này có cổng (`platform/console/tests/test_cong_tai_lieu.py`): thêm workflow hay
job mà không kể ở đây là `console-unit` đỏ.

**`ci.yml`** — mỗi PR và mỗi push `main`; 19 job, `quality` (`if: always()`) gom 18 job còn lại. Ma trận `*-unit`
và `unit`: ubuntu 3.11 + 3.13, windows 3.13; `core-static`/`keeper-static`: ubuntu + windows.

| Gói | Job | Chạy gì |
|---|---|---|
| software-company | `static`, `unit`, `eval-replay`, `asset-scan` | ruff + mypy · pytest `-n auto` coverage 100 · `company.evals all --selftest` rồi `--replay --strict` · `assetscan scan` + `budget` (ADR-0022) |
| gateway | `gateway-static`, `gateway-unit` | ruff + mypy · pytest coverage 100 |
| console | `console-static`, `console-unit` | ruff + mypy · pytest coverage 100 — gồm cả các cổng của repo (`tests/test_cong_*.py`, `test_readme_goc.py`) |
| xagents-core | `core-static`, `core-unit` | ruff + mypy (`strict = true` trong `pyproject.toml`) · pytest coverage 100 |
| keeper | `keeper-static`, `keeper-unit`, `keeper-eval-replay`, `drift-check` | ruff + mypy · pytest coverage 100 · `keeper.evals all --replay --strict` · `keeper.cli drift --repo .` (ba phép so cục bộ: `sc-*` và golden lệch `version` nguồn, CHANGELOG còn chỗ trống số PR kiểu `(#PENDING)`) |
| hai công ty | `golden-check` | golden agent sinh lại phải khớp bản đã commit (ma trận `software-company`, `keeper`); riêng software-company: `company.subagents check` (`.claude/agents/sc-*` khớp nguồn) |
| phiên Claude Code | `ecc-check` | `scripts/ecc_vendor.py check`: tải nông ECC tại commit ghim, sinh lại rồi so `.claude/*/ecc-*` + lock (ADR gốc 0028; cần github.com) |
| toàn repo | `audit`, `protection-guard`, `quality` | pip-audit (một `uv.lock`) + gitleaks cả lịch sử · ruleset trong file ↔ ruleset thật, hai chiều · gom kết quả |

**`pr-policy.yml`** — mỗi PR (kể cả sửa thân PR, gắn/gỡ nhãn); job `metadata`: tiêu đề Conventional Commits, scope
một từ chữ thường · PR thêm ít nhất một dòng vào `CHANGELOG.md`, không bắt `(#<số PR>)`
(`scripts/pr_changelog_check.py`; nhãn `no-changelog` để miễn) · PR `fix(` chạm `orchestrator.py`/`orch/` phải dẫn ADR-0034 · mục Definition of Done và
BÁO CÁO XÁC THỰC không còn `- [ ]` (`scripts/pr_dod_check.py`; ô ghi `(sau merge)` được miễn) · thiếu
`docs/sessions/<hôm nay>.md` chỉ cảnh báo.

**`dependency-review.yml`** — mỗi PR; job `dependency-review` chặn phụ thuộc mới có lỗ hổng mức `high` trở lên.
Không phải required check.

**`eval-record.yml`** — chạy tay (`workflow_dispatch`); job `record` ghi lại eval của `company` bằng model THẬT (tốn
tiền) rồi mở PR với bản ghi mới — đường thay cho `make eval-record` khi máy không có khoá API.

## Lịch sử repo (đọc `git log` cho đúng)

Repo này bắt đầu là fork của `humanlayer/12-factor-agents` (khoảng 200 commit "Update factor-…", "wip on wtg"…), rồi
chứa dự án MEP-Agents/CAD (08/2026, có hai lần revert chéo). **Đầu thực của X-Agents là `2438d2f` (2026-09-02, "Add
software-company AI agent framework")**; `d4abda1` cùng ngày gỡ MEP-Agents. Muốn xem lịch sử có nghĩa:
`git log 2438d2f..main`. Không rewrite lịch sử cũ — chỉ cần biết mốc.

## Tài liệu nguồn

| Câu hỏi | Đọc |
|---|---|
| Cài và vận hành từng bước | `docs/HUONG-DAN-VAN-HANH.md` |
| Model nào cho agent nào, xoay quota ra sao | `docs/DIEU-PHOI-MODEL.md` |
| Dừng khẩn, lịch trực, thứ chưa có | `docs/TRUC-VA-DUNG-KHAN.md` |
| Git: nhánh, PR, CI, worktree | `docs/QUY-TRINH-GIT.md` |
| Sửa agent/skill phải chạy lại gì | `CONTRIBUTING.md` |
| Thi hành một đề bài lớn từ đặc tả tới PR merge, một lệnh | `docs/KHUON-THI-HANH.md`, `/thi-hanh` |
| Bốn lớp Prompt/Agent/Loop/Graph: hiện trạng, tám việc, gói việc, điều phối subagent, khuôn công ty mới | `docs/KIEN-TRUC-4-LOP.md` |
| Bảo mật: bí mật, phòng thủ, báo lỗi | `SECURITY.md` |
| Vì sao quyết định thế này | Bốn dãy ADR, mỗi dãy đánh số riêng từ 0001, không tiền tố: `docs/adr/` gốc (0001–0028, quyết định cấp repo/quy trình), `companies/software-company/docs/adr/` (0001–0047), `platform/console/docs/adr/` (0001–0004), `platform/gateway/docs/adr/` (0001–0004) |
