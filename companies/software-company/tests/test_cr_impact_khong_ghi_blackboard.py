"""Lượt ước lượng impact của change request CÒN CHỜ (`change-requests → product → audit-log`) không ghi blackboard.

CR chưa được quyết thì kế hoạch cho nó chưa là sự thật của dự án. Trước bản vá, product trả kèm `context_writes`
(vd architecture `change/<cid>/plan-v1`) và orchestrator ghi luôn — CR bị bác thì bản đó vẫn là bản MỚI NHẤT mọi
agent đọc. Hub thật (QLKH-DD-CSV, 2026-10-16): impact của REWORK-DDCSV-109-2 ghi architecture v43 lúc 01:31 ("rút
allowlist", lập DDCSV-127), CR bị bác lúc 01:33; security đọc v43 và chặn DDCSV-116 làm đúng CR-DDCSV-SEC-008 đã
accepted, ticket bị đẩy về builder thêm một lượt.

Hai chiều (luật bắt buộc 4): bỏ `context_writes=False` khỏi route impact → cả hai ca đỏ."""

from __future__ import annotations

from company.bus import InMemoryBus
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from test_orchestrator import _pub, handler

PLAN = "docs/change/CR-1/plan-v1.md"


def _chay(tmp_path):
    users: list[str] = []

    def ghi_ke_hoach(system, user):
        out = handler(system, user)
        if isinstance(out, dict) and out.get("action") == "change.impact":
            users.append(user)
            return {
                "payload": out,
                "context_writes": [
                    {
                        "namespace": "architecture",
                        "content_ref": PLAN,
                        "summary": "kế hoạch cho CR chưa quyết",
                        "content": "# rút allowlist",
                    }
                ],
            }
        return out

    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=ghi_ke_hoach))
    orch.blackboard.write("product", "architecture", "docs/c4.md", "L1-L2", project_id="P1")
    orch.blackboard.write("product", "api-contract", "openapi.yaml", "v1", project_id="P1")
    _pub(
        bus,
        "external-feedback",
        "P1",
        "human:customer",
        {"project_id": "P1", "from": "chị Lan", "text": "muốn xuất Excel"},
    )
    orch.run()
    return bus, users


def test_impact_cua_cr_dang_cho_khong_ghi_architecture(tmp_path):
    bus, users = _chay(tmp_path)
    assert users, "lượt impact phải chạy"
    impact = [e for e in bus.replay(topic="audit-log") if e.payload.get("action") == "change.impact"]
    assert impact, "ước lượng impact vẫn được publish"
    refs = [e.payload.get("content_ref") for e in bus.replay(topic="shared-context") if e.key.endswith("architecture")]
    assert PLAN not in refs, f"kế hoạch của CR chưa quyết không được lên blackboard: {refs}"


def test_impact_khong_xin_model_context_writes(tmp_path):
    """Không xin thì model không tốn token đầu ra viết toàn văn artifact mà code sẽ bỏ."""
    _bus, users = _chay(tmp_path)
    assert users and all('Kèm "context_writes"' not in u for u in users), users[0][-600:]
