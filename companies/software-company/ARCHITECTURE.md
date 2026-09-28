# ARCHITECTURE.md — software-company

Bản đồ đầy đủ: [`docs/architecture.md`](docs/architecture.md) (nguyên tắc, bảng topic producer/consumer được test đối
chiếu với `ROUTES`, vòng đời ticket, trạng thái, human gate). Tiêu chuẩn ngành từng khối: `docs/standards.md`. Quyết
định: `docs/adr/` 0001–0042. File này chỉ là lối vào nhanh.

## Năm công đoạn (ADR-0037)

`product` (pha `intake`/`research`/`spec`/`plan`) · `builder` (pha = `stack` của ticket: backend, frontend, mobile,
database, platform, data) · `qa` (pha `author`/`review`) · `security` (không pha) · `ops` (pha `deploy`/`docs`/
`account`). Cộng `supervisor` — code, không phải công đoạn — nên `load_agents()` trả **6**. Pha quyết định skill nào
được nạp cho lượt đó (`phases:` trong front matter), không phải một agent khác.

## Một ticket đi qua đâu

```
yêu cầu thô ─► product[intake] ─► product[research] (4 mảng) ─► product[spec] (draft kèm risks)
   ─► product[intake] (câu hỏi làm rõ) ⇄ người ─► product[spec] → approved-specs
   ─► GATE spec ─► security (threat model) ─► product[plan] (C4, contract, ticket) ─► _check_plan (CODE, không gate)
   ─► [qa[author] lượt mù] ─► builder[stack] (worktree ticket/<id>, lint/test thật) ─► qa[review] (+ security nếu risk_tags)
   ─► delivery.py: approved → merge vào company/integration ─► release-candidate
   ─► ops[deploy] staging ─► ORCHESTRATOR SMOKE (ADR-0029) ─► qa[review] hồi quy ─► GATE release
   ─► ops[deploy] production ─► tag v<version> + company/release (ADR-0027) ─► GATE acceptance (khách ký)
   ─► ops[docs] (release notes, incident) · ops[account] (UAT, change request)
```

`delivery.py` phát event dưới actor `delivery-lead` (`roles.LEAD_ACTOR`) — đó là CODE đóng vòng, không phải agent.

Kẹt ở đâu cũng có đường ra: agent tự dừng / smoke fail / retry hết / plan lỗi / threat model chặn / transient quá trần → gate
`escalation` (một cửa `_mark_unhandled`); câu hỏi làm rõ quá hạn → giả định theo `default` rồi pha `spec` chạy; supervisor đếm ngân sách và
bế tắc. Không đường nào được kết thúc trong im lặng (`../../TRAPS.md` §1).

## Lớp code (`src/company/`)

| Lớp | Module | Vai trò |
|---|---|---|
| Tên vai | `roles.py` | NƠI DUY NHẤT id agent là chuỗi trong `src/` (ADR-0037 PR-4): `ROLE.*`, `PHASE.*`, `STACK`/`BUILD_PHASES`, nhãn `SOURCE.*`, `LEAD_ACTOR` |
| Hợp đồng | `events.py`, `topics/schemas/`, `registry.py` | topic, payload Pydantic, agent đọc/ghi gì, `phases:` của agent |
| Bus | `bus.py`, `sqlite_bus.py`, `blackboard.py` | publish có kiểm producer + schema; replay; artifact theo namespace |
| Điều phối | `orchestrator.py`, `delivery.py`, `gates.py`, `gate_cli.py`, `supervisor.py` | route, máy trạng thái ticket/release, human gate bền, watchdog |
| Tự duyệt theo sàn | `quality_floor.py`, `gate_risk.py` | ADR-0043: bằng chứng máy + mức nâng dự án → release/nghiệm thu tự duyệt; thiếu → người |
| Chạy agent | `runner.py`, `tools.py`, `guard.py`, `context.py`, `subagents.py` | vòng lặp tool, ranh giới tin cậy, injection, hạn mức ngữ cảnh |
| Bằng chứng | `workspace.py`, `stacks.py`, `smoke.py` | worktree, lint/test thật, merge/deliver, smoke |
| Model | `llm.py`, `routing.py`, `mcp_bridge.py`, `probe.py`, `web.py` | adapter, tier, xoay quota, cầu MCP |
| Quan sát | `metrics.py`, `evals.py`, `assetscan.py`, `gate_brief.py`, `gate_checklists.py` | số liệu, eval ghi/phát lại, quét prompt, hồ sơ gate |

## Ranh giới tin cậy — thứ giữ cho hệ không tự lừa mình

Model **chỉ trả JSON**; mọi hành động có hậu quả là code: ghi file trong worktree qua `tools.py` (allowlist, khoá
đường dẫn, env đã lọc, không hook git), lint/test qua `stacks.py`, merge/tag/push qua `workspace.py`, smoke qua
`smoke.py`. Trường "đã làm được" do code điền (`verified_by=workspace|orchestrator`); identity của event do ROUTE
quyết. Chi tiết: ADR-0010, 0013, 0027, 0028, 0029.

Gate `release`/`acceptance` chỉ được code tự duyệt (cờ `COMPANY_GATE_AUTOAPPROVE`, ADR-0043) khi CHÍNH các trường
máy điền ấy đạt sàn `quality_floor.floor_gaps` — verdict của model chỉ được dùng để chặn, không để cho qua. Máy
nghiệm thu không ghi `acceptance-results` (chữ ký khách); `spec` và `escalation` luôn là của người.
