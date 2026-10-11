"""Một bảng cho mọi lý do dừng của một lượt agent / một ticket (ADR-0052).

Trước ADR này mỗi lý do dừng có một bộ đếm, một hằng và một audit ở một file khác nhau (`turn_continuations` +
`MAX_TURN_CONTINUATIONS`, `conflict_retries` + `MAX_CONFLICT_RETRIES`, `transient_since` + `transient_limit()`,
`Task.retry` + `max_retries`…), và `ticket.blocked` chỉ nói `retry=3` — không nói ba lần đó là test đỏ hay xung đột
merge. Ở đây: **kiểu** (`StopKind`), **chính sách** cho từng kiểu (`STOP_POLICY`) và **một chỗ phân loại** lỗi
(`classify_error`). Các đường xử lý vẫn nằm ở `orch/error_flow.py`, `orch/worktree_flow.py`, `delivery.py` — chúng chỉ
đọc bảng này và ghi `stop_kind` vào audit, không giữ số riêng nữa.

Ý mượn từ blocker có kiểu của DeerFlow 2.0 (`docs/reports/2026-10-11-doi-chieu-deerflow.md`); ở đây kiểu do CODE gán từ
`TransientError`/`LLMError.head`, không phải model tự khai.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal, get_args

from .llm import TransientError

StopKind = Literal["agent_error", "turn_limit", "infra_transient", "merge_conflict", "budget", "needs_human", "no_progress"]
STOP_KINDS: Final[tuple[str, ...]] = get_args(StopKind)

#: Số lần builder hết lượt tool mà worktree có tiến độ được làm tiếp KHÔNG tính retry (xem `orchestrator.turn_continuations`).
MAX_TURN_CONTINUATIONS: Final = 3
#: Xung đột merge thứ N+1 liên tiếp cho một ticket mới tính vào retry nội dung (xem `orchestrator.conflict_retries`).
MAX_CONFLICT_RETRIES: Final = 6
#: `subtype` của `claude -p` là trục trặc của lượt ép đầu ra, không phải nội dung sai: thử lại đúng một lần trước khi hỏi
#: người. Đo được 2026-09-24 (CAMPUS-UNI/REL-003): ops trên `release-candidates` chết một lần là gate escalation.
AUTORETRY_SUBTYPES: Final = frozenset({"error_max_structured_output_retries"})


@dataclass(frozen=True)
class Policy:
    """`burns_retry`: có đốt `Task.retry` (trần `max_retries` của `DeliveryLead`) không. `free_stops`: số lần dừng kiểu
    này được miễn trước khi tính như `agent_error` (None = không có giai đoạn miễn). `then`: code làm gì ngay sau khi
    dừng (`retry` giao lại kèm hint · `continue` làm tiếp từ WIP · `defer` hoãn event · `escalate` mở gate cho người)."""
    burns_retry: bool
    free_stops: int | None
    then: Literal["retry", "continue", "defer", "escalate"]


STOP_POLICY: Final[dict[str, Policy]] = {
    "agent_error": Policy(burns_retry=True, free_stops=None, then="retry"),                       # test đỏ, review block, JSON hỏng, khách từ chối
    "turn_limit": Policy(burns_retry=True, free_stops=MAX_TURN_CONTINUATIONS, then="continue"),  # hết lượt tool; miễn khi worktree có tiến độ
    "infra_transient": Policy(burns_retry=False, free_stops=None, then="defer"),                 # 429/5xx, CLI ép schema hỏng (một lần)
    "merge_conflict": Policy(burns_retry=True, free_stops=MAX_CONFLICT_RETRIES, then="retry"),   # thua cuộc đua merge; miễn tới trần
    "budget": Policy(burns_retry=False, free_stops=None, then="escalate"),                       # chạm trần token/tiền (supervisor budget_cut)
    "needs_human": Policy(burns_retry=False, free_stops=None, then="escalate"),                  # không nhánh nào nhận, chuỗi nghiên cứu chết
    "no_progress": Policy(burns_retry=False, free_stops=None, then="escalate"),                  # cùng chữ ký lỗi ≥ 2 (supervisor)
}


def cli_subtype(error: object) -> str:
    """`subtype` của `claude -p` trong PHẦN ĐẦU thông điệp (`LLMError.head`, do adapter viết) — không soi phần chữ
    của model, để model viết "subtype=..." trong câu trả lời dở không đổi được cách xử lý lỗi."""
    m = re.search(r"subtype=([a-z_]+)", str(getattr(error, "head", "") or ""))
    return m.group(1) if m else ""


def classify_error(error: object) -> StopKind:
    """Kiểu dừng của một lỗi lượt agent, gán bằng code từ lớp lỗi và `head`. Chuỗi lạ / lỗi handler → `agent_error`
    (nội dung sai là mặc định an toàn: nó đốt retry và cuối cùng hỏi người)."""
    if isinstance(error, TransientError): return "infra_transient"
    st = cli_subtype(error)
    if st == "error_max_turns": return "turn_limit"
    if st in AUTORETRY_SUBTYPES: return "infra_transient"
    if st == "error_max_budget_usd": return "budget"
    return "agent_error"
