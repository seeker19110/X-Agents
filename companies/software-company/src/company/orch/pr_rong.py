"""PR rỗng của ticket CHƯA từng tích hợp: builder dừng (bị chặn, đầu vào mâu thuẫn, cần quyết định) chứ không làm xong.

Runner cho phép PR không đổi file khi agent ghi `no_changes_reason` — đường hợp lệ của TCK-CR-RUNTIME-01 ("đã xong từ
lượt trước": nhánh có commit thật). Nhưng prompt builder cũng dặn dùng đúng trường đó khi "bị chặn, cần người quyết",
và ở lượt ĐẦU nhánh không có gì: PR 0 file ở sha nền. Hub thật 2026-10-14 (QLKH-DD-CSV): DDCSV-73 dừng vì spec ghi cổng
8080 còn compose publish 8000; QA chấm pass kèm warn "ticket chưa làm, không được tính là xong", orchestrator
`integration.noop` rồi tạo REL-062 với đúng ticket chưa làm đó.

Ticket đã tích hợp mà làm lại không đổi code là ADR-0057 (`rework_no_change`) — transition đó đứng trước và guard ở
đây loại trừ nó (`tid not in o.integrated`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..events import Envelope
from .fsm import Transition

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator, StepResult


def _guard(env: Envelope, o: Orchestrator) -> bool:
    tid = str(env.payload.get("ticket_id") or env.key)
    # Chỉ khi CODE đã đo worktree (runner điền `impact.files` + `verified_by=workspace`): dự án chạy không repo thì
    # PR không có danh sách file nào để nói là rỗng.
    measured = (env.payload.get("local_checks") or {}).get("verified_by") == "workspace"
    empty = (env.payload.get("impact") or {}).get("files") == []
    return o.lead.state.get(tid) == "in_review" and tid not in o.integrated and measured and empty


def _act(o: Orchestrator, env: Envelope, res: StepResult) -> bool:
    tid = str(env.payload.get("ticket_id") or env.key)
    reason = str(env.payload.get("no_changes_reason") or env.payload.get("summary") or "?")[:500]
    o._audit(
        "pr.empty",
        {"ticket_id": tid, "pr_ref": env.payload.get("pr_ref"), "reason": reason},
        ticket_id=tid,
        project_id=o.project_for(env),
    )
    o.lead.block_empty_pr(tid, reason)
    res.actions.append(f"empty_pr:{tid}")
    o._mark(env, res)
    return True


EMPTY_PR = Transition("empty_pr", frozenset({"pull-requests"}), _act, guard=_guard)
