"""ADR-0057 bổ sung 2026-10-16: từ chối escalation release → chỉ làm lại ticket mà file đã đổi chạm vị trí file của
finding `block`; không ticket nào chạm → không làm lại ai, nộp CR cho planner.

Hub thật (QLKH-DD-CSV, 2026-10-12 → 16): 44,9M token tiêu để làm lại ticket ĐÃ merge sau release reject — phần lớn vì
một phát hiện gitleaks ở file của một ticket không nằm trong RC. Phép so là sự thật git (merge commit của ticket) với
vị trí finding, không đoán. Không đo được thì trả `None` và nhánh gọi giữ hành vi cũ."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..workspace import WorkspaceError

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator

#: Token trông như đường dẫn file trong `location` của finding (`a/b.py:24`, `image db (docker-compose.yml)`); chỉ
#: token có thật trong cây tích hợp mới được tính.
_PATH = re.compile(r"[\w./-]+\.[A-Za-z0-9]+")


def finding_files(o: Orchestrator, rid: str, tree: set[str]) -> set[str]:
    """Vị trí file của mọi finding `block` trong các review của RC (bản mới nhất mỗi nguồn)."""
    out: set[str] = set()
    for r in o.lead.release_reviews.get(rid, {}).values():
        for f in r.findings:
            if f.level == "block":
                out |= {m for m in _PATH.findall(f.location or "") if m in tree}
    return out


def tickets_to_rework(o: Orchestrator, rid: str) -> tuple[list[str], set[str]] | None:
    """`(ticket cần làm lại, file của finding)`; `None` = không đo được (không có nhánh tích hợp, git lỗi)."""
    tids = [t for t in o.lead.release_tickets.get(rid, []) if o.lead.state.get(t) == "merged"]
    integ = o._integration_of_ticket(tids[0]) if tids and o._has_integration() else None
    if integ is None: return None
    try:
        ff = finding_files(o, rid, set(integ.files()))
        # Ticket không tìm thấy merge commit nào: không biết nó đổi gì → coi như chạm (hành vi cũ cho riêng nó).
        hit = [t for t in tids if (tf := integ.ticket_files(t)) & ff or not tf]
    except WorkspaceError:
        return None
    return hit, ff
