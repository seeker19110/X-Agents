"""Tiến trình con cho các ca `Lease` chạy THẬT nhiều tiến trình ở `test_sqlite_bus.py`.

Tách khỏi file test vì `multiprocessing` kiểu spawn (kiểu duy nhất Windows có, nên dùng nó ở mọi nền tảng cho
cùng một hành vi) nhập lại module chứa hàm đích trong tiến trình con: module nhỏ này chỉ kéo `xagents_core`,
không kéo pytest + conftest theo. pytest không thu thập file này (tên không bắt đầu bằng `test_`).
"""

from __future__ import annotations

import time
from typing import Any

from xagents_core import sqlite_bus as SB

CHO_S = 30.0  # mọi lần chờ đều có hạn: hỏng thì đỏ, không treo cả bộ test


class GapNhauMotLan:
    """Thay `_alive` trong tiến trình con: lần gọi đầu đứng chờ tiến trình kia ở `gap`, rồi trả "pid đã chết".

    Mã cũ gọi `_alive` đúng giữa lúc ĐỌC pid trong lock và lúc GHI pid của mình — chờ nhau ở đó là giữ cửa sổ đua
    mở chắc chắn (cả hai đã đọc "pid chết", chưa ai ghi), không phải trông vào may rủi của bộ lập lịch. Mã có khoá
    OS gọi `_alive` khi đã giữ khoá, nên kẻ kia bị chặn trước khi tới đây và chỉ tới điểm hẹn sau khi nhận
    `LeaseError` (`gap_nhau()` ở `dua`)."""

    def __init__(self, gap: Any) -> None:
        self.gap, self.da_gap = gap, False

    def __call__(self, pid: int) -> bool:
        self.gap_nhau()
        return False

    def gap_nhau(self) -> None:
        if not self.da_gap:
            self.da_gap = True
            self.gap.wait(CHO_S)


def dua(db: str, so_vong: int, xuat_phat: Any, gap: Any, ket_qua: Any, da_dem: Any, da_nha: Any) -> None:
    """Mỗi vòng: cùng xuất phát với tiến trình kia, cùng chiếm lock cũ mà cha vừa dựng, báo thắng/thua."""
    for vong in range(so_vong):
        xuat_phat.wait(CHO_S)
        hen = GapNhauMotLan(gap)
        SB._alive = hen
        lease = SB.Lease(db)
        try:
            lease.acquire()
            thang = True
        except SB.LeaseError:
            thang = False
        hen.gap_nhau()  # kẻ thua (bị chặn trước khi gọi `_alive`) vẫn phải tới điểm hẹn
        ket_qua.put((vong, thang))
        da_dem.wait(CHO_S)  # cha đếm xong vòng này mới nhả
        lease.release()
        da_nha.wait(CHO_S)  # cả hai đã nhả: cha dựng lại lock cũ cho vòng sau


def giu(db: str, san_sang: Any) -> None:
    """Giữ lease rồi ngủ tới khi bị kill — chết không kịp `release()`, đúng như orchestrator bị giết."""
    lease = SB.Lease(db)
    lease.acquire()
    san_sang.set()
    time.sleep(CHO_S * 10)
    lease.release()
