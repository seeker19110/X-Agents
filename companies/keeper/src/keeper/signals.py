"""Gộp trùng `Signal` (BT3, `DAC-TA-KEEPER.md` §5).

`Signal` (`events.py`) không mang mốc thời gian riêng — bus gắn `ts` ở `Envelope`, không phải ở payload. Vì vậy
"giữ cái mới nhất" ở đây nghĩa là giữ theo **thứ tự xuất hiện trong danh sách đưa vào** (`signals` được gọi theo
đúng thứ tự phát ra / đọc từ bus, phần tử cuối cùng của một nhóm là bản quan sát mới nhất) — không suy đoán thời
gian từ nội dung `detail`/`evidence`.
"""
from __future__ import annotations

from .events import Signal, SignalKind


def dedupe(signals: list[Signal]) -> list[Signal]:
    """Gộp theo `(kind, subject)`: giữ mọi trường của bản MỚI NHẤT (phần tử cuối cùng trong nhóm), cộng dồn
    `seen_count` của tất cả bản trùng. Thứ tự nhóm đầu ra theo lần xuất hiện ĐẦU TIÊN của mỗi khoá.

    Đừng xếp tier trên kết quả này: bản mới nhất có thể nhẹ hơn bản trước. `triage.triager` lấy bậc cao nhất
    của cả nhóm (K3, audit 2026-10-10)."""
    order: list[tuple[SignalKind, str]] = []
    groups: dict[tuple[SignalKind, str], list[Signal]] = {}
    for s in signals:
        key = (s.kind, s.subject)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(s)

    out: list[Signal] = []
    for key in order:
        items = groups[key]
        total_seen = sum(i.seen_count for i in items)
        out.append(items[-1].model_copy(update={"seen_count": total_seen}))
    return out
