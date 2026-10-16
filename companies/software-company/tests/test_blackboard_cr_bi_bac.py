"""Bản blackboard viết cho kế hoạch của một CR ĐÃ BỊ BÁC không phải bản hiện hành (ADR-0007 bổ sung 2026-10-16 (b)).

Hub thật (QLKH-DD-CSV, 2026-10-16): impact của REWORK-DDCSV-109-2 / REWORK-DDCSV-100-1 ghi architecture v43/v44
(`change/<CR>/plan-v1`: "cấm merge allowlist DDCSV-116"). Cả hai CR bị bác, nhưng v44 vẫn là bản mới nhất: ops ĐỌC nó
và từ chối dựng staging cho REL-105 (RC chứa DDCSV-116), security chặn vì "chưa có DAST". #531 chặn bản ghi mới kiểu
này; bản đã ghi thì phải không còn được đọc như hiện hành — sửa phía ĐỌC, không ghi tay blackboard.

Hai chiều (luật bắt buộc 4): bỏ phép lọc ở `Blackboard.read/snapshot` → ca 1, 4, 5 đỏ; ca 2 (CR accepted) và ca 3 (bản ghi sau) xanh cả hai."""

from __future__ import annotations

from company.bus import InMemoryBus
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.sqlite_bus import SQLiteBus
from test_orchestrator import _pub, handler

PLAN = "architecture/P1/change/CR-X/plan-v1"


def _cr(bus, decision: str) -> None:
    _pub(
        bus,
        "change-requests",
        "CR-X",
        "delivery-lead",
        {
            "change_id": "CR-X",
            "project_id": "P1",
            "requested_by": "delivery-lead",
            "description": "rework",
            "decision": decision,
        },
    )


def _dung(bus, decision: str) -> Orchestrator:
    orch = Orchestrator(bus, FakeClient(handler=handler))
    orch.blackboard.write("product", "architecture", "docs/c4.md", "gốc", content="# C4 gốc", project_id="P1")
    orch.blackboard.write("product", "architecture", PLAN, "kế hoạch CR-X", content="# cấm merge", project_id="P1")
    _cr(bus, decision)
    return orch


def test_ban_cua_cr_bi_bac_khong_con_la_hien_hanh():
    orch = _dung(InMemoryBus(), "rejected")
    bb = orch.blackboard
    assert bb.content("architecture", "P1") == "# C4 gốc", "đọc rơi về bản hợp lệ gần nhất"
    assert bb.snapshot("P1")["architecture"].version == 1, "ngữ cảnh agent (runner) cũng không thấy bản của CR bị bác"
    assert bb.read("architecture", "P1").content_ref == "docs/c4.md"


def test_cr_accepted_thi_ban_ke_hoach_van_hien_hanh():
    orch = _dung(InMemoryBus(), "accepted")
    assert orch.blackboard.content("architecture", "P1") == "# cấm merge"


def test_ban_ghi_sau_cr_bi_bac_van_la_moi_nhat_va_so_ban_khong_lui():
    orch = _dung(InMemoryBus(), "rejected")
    sc = orch.blackboard.write("product", "architecture", "docs/c4.md", "v3", content="# C4 v3", project_id="P1")
    assert sc.version == 3, "số bản đếm theo bus, không lùi về bản được đọc"
    assert orch.blackboard.content("architecture", "P1") == "# C4 v3"


def test_sau_khoi_dong_lai_van_bo_ban_cua_cr_bi_bac(tmp_path):
    db = tmp_path / "c.sqlite"
    _dung(SQLiteBus(db), "rejected")
    o2 = Orchestrator(SQLiteBus(db), FakeClient(handler=handler))
    assert o2.blackboard.content("architecture", "P1") == "# C4 gốc"


def test_moi_ban_deu_cua_cr_bi_bac_thi_khong_co_ban_hien_hanh():
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler))
    orch.blackboard.write("product", "architecture", PLAN, "kế hoạch CR-X", content="# cấm merge", project_id="P1")
    _cr(bus, "rejected")
    assert orch.blackboard.read("architecture", "P1") is None and "architecture" not in orch.blackboard.snapshot("P1")
