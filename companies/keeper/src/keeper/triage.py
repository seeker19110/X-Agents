"""`triager`: `maintenance-signals` → `maintenance-tickets` (BT4, `DAC-TA-KEEPER.md` §6).

## Khoá chống-trùng theo DANH TÍNH EVENT — vì sao đổi khỏi "thế hệ"

Cạm bẫy §6 (bug `once="no-test-author:{tid}"`, K1.7): một khoá chống-trùng không mang thế hệ sẽ nuốt lần thứ
hai HỢP LỆ. Bản BT4 chống bằng một **thế hệ** = "số vòng đời ticket đã ĐÓNG của chủ thể đó". `sc-security` đo
lại ở BT7 và thế hệ ấy **không bao giờ tăng**: không chỗ nào trong `keeper/src/` đặt `Ticket.status="closed"`,
nên thế hệ vĩnh viễn bằng 0 và mọi signal hợp lệ phát lại SAU khi một vòng đã xong bị nuốt vĩnh viễn — dạng
nặng hơn chính cái bug nó sinh ra để chặn.

Bản sửa đổi trục chống trùng sang thứ bus đã có sẵn và không phải suy ra: **`Envelope.event_id`**. Mỗi lần
`submit_signal` là một envelope riêng với id riêng; `bus.replay()` trả lại ĐÚNG những id đó. Hai tính chất bắt
buộc vì thế đều đo được, không phải suy luận:

* **idempotent khi replay** — cùng bộ envelope dựng lại thì mọi id đã tiêu thụ vẫn nằm trong `TriageState`
  (dựng lại từ `Ticket.signal_event_ids`, không từ một biến RAM), nên không ticket nào ra lần hai;
* **không nuốt signal MỚI** — một envelope mới có id mới, chưa ai tiêu thụ, nên ra ticket ngay cả khi
  `(kind, subject)` trùng hệt vòng trước.

Cái giá: `ticket_id` không còn đọc ra được `(kind, subject)` (nó là `KEEP:<event_id>`). Đổi lại nó là một khoá
thật sự duy nhất trong đời repo, và `subject`/`signal_subjects`/`signal_event_ids` vẫn nằm trong payload cho
người lần ngược. Sự đánh đổi này chọn được vì phía kia là một cổng im lặng nuốt việc — thứ TRAPS gọi là "chế
độ hỏng không tự khai báo".

`state` là tham số, không phải state trong module: đúng như `can_open_pr` không tin biến đếm trong RAM,
`triager` không tự nhớ gì giữa hai lời gọi — nó nhận sổ đã dựng lại từ nơi giữ trạng thái thật.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from .events import RiskTier, Signal, Ticket
from .risk import TIER_RANK, risk_tier
from .signals import dedupe

__all__ = ["DUE_DAYS", "TICKET_PREFIX", "DedupeKey", "ObservedSignal", "TriageState", "event_identity",
           "legacy_generation_key", "triager"]

# Hạn xử lý theo tier (`Ticket.due_at`, tiêu thụ bởi `ledger.overdue`). Bảng, không `if`.
DUE_DAYS: dict[RiskTier, int] = {"high": 1, "medium": 7, "low": 30}

TICKET_PREFIX = "KEEP:"


class ObservedSignal(NamedTuple):
    """Một `Signal` CÙNG danh tính event của nó trên bus (`Envelope.event_id`).

    Cặp này không gộp vào `Signal` được: `Signal` là payload, `event_id` là thuộc tính của ENVELOPE — nhét id
    vào payload là để agent tự khai được danh tính event của mình, đúng thứ `AGENTS.md` cấm §8."""

    event_id: str
    signal: Signal


class TriageState:
    """Sổ `event_id` đã tiêu thụ. Dựng lại từ `Ticket.signal_event_ids` khi orchestrator replay bus."""

    def __init__(self, seen: Iterable[str] | None = None) -> None:
        self.seen: set[str] = set(seen or ())


#: Trục chống-trùng: một `ObservedSignal` → khoá. Tham số hoá vì cùng lý do như `evidence.rules_without` /
#: `budget.checks_without`: ca "chiều ngược" phải ĐỔI ĐƯỢC đúng bản sửa (ở đây bản sửa CHÍNH LÀ trục) rồi đo
#: lại trên cùng đầu vào. Mã sản xuất không bao giờ truyền tham số này.
DedupeKey = Callable[["ObservedSignal"], str]


def event_identity(observed: ObservedSignal) -> str:
    """Trục đang dùng: danh tính event trên bus. Xem docstring module."""
    return observed.event_id


def legacy_generation_key(observed: ObservedSignal) -> str:
    """Trục CŨ (BT4): `<thế hệ>:<kind>:<subject>`. Thế hệ viết cứng 0 vì đó là giá trị nó có trong thực tế —
    không mã nào trong `keeper/src/` đặt `Ticket.status="closed"`, nên bộ đếm thế hệ không bao giờ tăng.

    CHỈ ca chiều ngược dùng hàm này: nó là hình dạng hỏng, giữ lại để đo được rằng bản sửa có tác dụng thật,
    chứ không phải để ai đó gọi."""
    return f"0:{observed.signal.kind}:{observed.signal.subject}"


def _due_at(tier: RiskTier, now: datetime) -> str:
    reference = now.replace(tzinfo=UTC) if now.tzinfo is None else now
    return (reference + timedelta(days=DUE_DAYS[tier])).isoformat()


def _groups(observed: Sequence[ObservedSignal]) -> list[list[ObservedSignal]]:
    """Gom theo `(kind, subject)`, giữ thứ tự nhóm theo lần xuất hiện ĐẦU TIÊN — cùng phép gom `signals.dedupe`
    dùng, ở đây phải làm lại vì `dedupe` chỉ trả về `Signal` đã gộp, không trả về id của từng bản."""
    order: list[tuple[str, str]] = []
    groups: dict[tuple[str, str], list[ObservedSignal]] = {}
    for o in observed:
        key = (o.signal.kind, o.signal.subject)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(o)
    return [groups[k] for k in order]


def triager(
    observed: Sequence[ObservedSignal], *, state: TriageState, now: datetime,
    key: DedupeKey = event_identity,
) -> list[Ticket]:
    """Bỏ event đã tiêu thụ → gộp trùng (`signals.dedupe`) → xếp bậc (`risk.risk_tier`) → `Ticket` mang hạn;
    tier `high` đính kèm yêu cầu gate `keeper` (`requires_gate=True`).

    Trả về CHỈ ticket mới của lần gọi này. `ticket_id` lấy danh tính của envelope MỚI NHẤT trong nhóm — cùng
    bản quan sát mà `dedupe` giữ lại nội dung (`signals.py`), nên id và nội dung nói về cùng một event.

    Tier thì KHÔNG lấy riêng bản mới nhất: gộp trùng không được hạ bậc (K3, audit 2026-10-10). Một alert
    `critical` rồi bản sau `low`, một bump `major` rồi `minor`, một evidence chạm `agents/` rồi không — tier là
    bậc CAO NHẤT trong cả nhóm, để `requires_gate` không biến mất chỉ vì bản nhẹ hơn tới sau."""
    out: list[Ticket] = []
    fresh = [o for o in observed if key(o) not in state.seen]
    for group in _groups(fresh):
        merged = dedupe([o.signal for o in group])[0]
        event_ids = [o.event_id for o in group]
        state.seen.update(key(o) for o in group)
        tier = min((risk_tier(o.signal) for o in group), key=TIER_RANK.__getitem__)
        out.append(Ticket(
            ticket_id=f"{TICKET_PREFIX}{event_ids[-1]}",
            subject=merged.subject,
            risk_tier=tier,
            signal_subjects=[merged.subject],
            signal_event_ids=event_ids,
            due_at=_due_at(tier, now),
            requires_gate=tier == "high",
        ))
    return out
