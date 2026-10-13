"""Nợ kiến trúc đã được quyết vẫn được hỏi lại, nhưng GIÃN DẦN: lần chạm ngưỡng thứ 1, 2, 4, 8… (ADR-0032 §4, sửa 2026-10-14).

Hub thật 2026-10-14 (QLKH-DD-CSV): SD-14 (DPIA khách phải ký — không agent nào làm được) được nhắc trong mọi review `qa`.
Ngưỡng 3 ⇒ cứ 3 review là một gate nợ: ×3 18:13, ×6 18:34, ×9/×12 21:39, ×21 21:57 — mỗi gate một lượt
`reviewer:tu-dong` (~15k token, luôn `hold` vì chỉ người ký được DPIA), một chữ ký `reject` (chấp nhận treo), và chiếm
subject dự án nên escalation khác của dự án phải đợi. Câu trả lời đã có và không đổi giữa hai lần hỏi.

Luật: chỉ mở gate khi `times` (lần thứ mấy chạm bội số ngưỡng) là luỹ thừa của 2 — một nguồn thì ×3, ×6, ×12, ×24…
Hàm thuần của `times` nên dựng lại từ bus y hệt (khuôn 2, `TRAPS.md`), không thêm trạng thái.
"""

from __future__ import annotations

import json

from company.bus import InMemoryBus
from test_no_kien_truc_adr0032 import _dua_toi_ke_hoach, _review


def _escalated(bus) -> list[int]:
    return [
        json.loads(e.payload["evidence"])["consecutive"]
        for e in bus.replay(topic="audit-log")
        if e.payload["action"] == "debt.escalated"
    ]


def test_no_da_quyet_hoi_lai_gian_dan_theo_luy_thua_2():
    bus = InMemoryBus()
    o = _dua_toi_ke_hoach(bus)
    for i in range(24):
        _review(bus, "T1", f"SD-14 DPIA chưa ký ({i})")
        o.run()
        if "P1" in o.gate.pending:
            o.gate.decide("P1", "reject", by="human:cto", reason="chấp nhận treo, DPIA khách ký sau")
            o.run()
    assert _escalated(bus) == [3, 6, 12, 24], "8 lần chạm ngưỡng → 4 lần hỏi, không phải 8"
