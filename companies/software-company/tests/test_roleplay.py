"""Role-play đề xuất/phản biện TRƯỚC pha `research` (ADR-0050, lấy ý `RolePlayingWorker` của CAMEL): hai vai thay
phiên, vai phản biện mới được kết thúc, hạn mức lượt + token là hàng rào, kết quả vào payload `debate` của lượt
research và một audit `research.debate` để chạy lại không tốn lượt model nữa."""
from __future__ import annotations

import json

import pytest

from company.bus import InMemoryBus
from company.events import Envelope
from company.llm import FakeClient, LLMError, Pricing
from company.orchestrator import ROUTES, Orchestrator
from company.orchestrator import main as orch_main
from company.registry import ROOT
from company.roleplay import ROLEPLAY_DIR, TURN_SCHEMA, Debate, RolePlay, load_roles
from company.sqlite_bus import SQLiteBus

TASK = {"project_id": "P1", "kind": "intake", "data": {"goals": [{"id": "G1", "text": "bán vé online"}]}}


def _turn(msg: str, points=(), questions=(), done=False) -> dict:
    return {"message": msg, "points": list(points), "open_questions": list(questions), "done": done}


def _who(system: str) -> str:
    return system.split("\n", 1)[0].lstrip("# ").strip()


# ---------- tài sản ----------

def test_hai_vai_trong_repo_la_tai_san_prompt_co_version():
    roles = load_roles()
    assert set(roles) == {"proposer", "critic"}
    for r in roles.values():
        assert r.version >= 1 and len(r.system) > 200 and r.system.startswith("# ")
    assert "phản biện" in roles["critic"].system and "đề xuất" in roles["proposer"].system
    from company.assetscan import ASSET_DIRS, asset_files
    assert "roleplay" in ASSET_DIRS
    assert {p.name for p in asset_files(ROOT) if p.parent == ROLEPLAY_DIR} == {"proposer.md", "critic.md"}


def test_load_roles_bao_loi_khi_thieu_vai(tmp_path):
    (tmp_path / "proposer.md").write_text("---\nid: proposer\nversion: 1\n---\n# x\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="critic"):
        load_roles(tmp_path)


# ---------- phiên ----------

def test_hai_vai_thay_phien_va_chi_phan_bien_moi_ket_thuc():
    client = FakeClient(responses=[
        _turn("đề xuất A", points=["A: web app"], done=True),            # proposer nói done: KHÔNG có hiệu lực
        _turn("A thiếu gì?", points=["A chưa tính offline"], questions=["offline?"]),
        _turn("đề xuất A+", points=["A+: PWA"]),
        _turn("đủ rồi", points=["A+ chấp nhận được"], done=True),
    ])
    rp = RolePlay(client, turn_limit=6, model_tier="standard")
    d = rp.run(TASK)
    assert [t["role"] for t in d.turns] == ["proposer", "critic", "proposer", "critic"]
    assert d.stopped_by == "done" and len(client.calls) == 4 and d.tokens == 4 * 1300
    assert d.proposals == ["A: web app", "A+: PWA"] and d.objections == ["A chưa tính offline", "A+ chấp nhận được"]
    assert d.open_questions == ["offline?"]
    s = d.summary()
    assert s == {"proposals": d.proposals, "objections": d.objections, "open_questions": d.open_questions,
                 "turns": 4, "stopped_by": "done", "tokens": 5200}
    # mỗi lượt: đúng vai, đúng schema, đúng tier, cache theo vai, và thấy toàn bộ transcript trước đó
    assert [_who(c["system"]) for c in client.calls] == ["Vai đề xuất", "Vai phản biện", "Vai đề xuất", "Vai phản biện"]
    assert all(c["schema"] == TURN_SCHEMA and c["model_tier"] == "standard" for c in client.calls)
    assert [c["cache_key"] for c in client.calls][:2] == ["roleplay:proposer", "roleplay:critic"]
    last = json.loads(client.calls[3]["user"])
    assert last["task"] == TASK and [t["message"] for t in last["transcript"]] == ["đề xuất A", "A thiếu gì?", "đề xuất A+"]
    assert last["turn"] == 4 and last["turns_left"] == 2


def test_het_luot_thi_dung_du_chua_done():
    client = FakeClient(handler=lambda s, u: _turn("tiếp", points=["p"]))
    d = RolePlay(client, turn_limit=3).run(TASK)
    assert d.stopped_by == "turn_limit" and len(client.calls) == 3 and len(d.turns) == 3


def test_vuot_ngan_sach_token_thi_dung_som():
    client = FakeClient(handler=lambda s, u: _turn("tiếp"), tokens_per_call=(1_000, 500))
    d = RolePlay(client, turn_limit=10, token_budget=3_000).run(TASK)
    assert d.stopped_by == "budget" and len(client.calls) == 2 and d.tokens == 3_000


def test_turn_limit_phai_duong():
    with pytest.raises(ValueError, match="turn_limit"):
        RolePlay(FakeClient(), turn_limit=0)


def test_gia_tien_tinh_qua_pricing():
    client = FakeClient(responses=[_turn("a"), _turn("b", done=True)])
    pricing = Pricing({"fake-standard": {"input": 1.0, "output": 2.0}})
    d = RolePlay(client, turn_limit=2, pricing=pricing).run(TASK)
    assert d.cost_usd == pytest.approx(2 * (1_000 * 1.0 + 300 * 2.0) / 1_000_000)
    assert RolePlay(FakeClient(responses=[_turn("a", done=True)]), turn_limit=1).run(TASK).cost_usd == 0.0


def test_loi_json_mot_luot_la_loi_model_khong_nuot():
    client = FakeClient(responses=[{"message": "thiếu points"}])
    with pytest.raises(LLMError, match="points"):
        RolePlay(client, turn_limit=2).run(TASK)


def test_from_env_tat_mac_dinh_bat_bang_so_luot(monkeypatch):
    monkeypatch.delenv("COMPANY_DEBATE_TURNS", raising=False)
    assert RolePlay.from_env(FakeClient()) is None
    monkeypatch.setenv("COMPANY_DEBATE_TURNS", "0")
    assert RolePlay.from_env(FakeClient()) is None
    monkeypatch.setenv("COMPANY_DEBATE_TURNS", "4")
    monkeypatch.setenv("COMPANY_DEBATE_BUDGET", "9000")
    rp = RolePlay.from_env(FakeClient())
    assert rp is not None and rp.turn_limit == 4 and rp.token_budget == 9_000
    assert RolePlay.from_env(FakeClient(), turns=2).turn_limit == 2, "tham số CLI thắng biến môi trường"
    monkeypatch.setenv("COMPANY_DEBATE_TURNS", "nhiều")
    with pytest.raises(ValueError, match="COMPANY_DEBATE_TURNS"):
        RolePlay.from_env(FakeClient())


# ---------- nối vào route research ----------

def _handler(system: str, user: str) -> dict:
    who = _who(system)
    if who == "Vai đề xuất": return _turn("đề xuất", points=["web app"])
    if who == "Vai phản biện": return _turn("phản biện", points=["chưa có offline"], questions=["offline?"], done=True)
    p = json.loads(user.split("```json\n", 1)[1].split("\n```", 1)[0])
    _handler.seen.append(p)  # type: ignore[attr-defined]
    return {"project_id": "P1", "kind": "researcher", "data": {"domain": {}, "ux": {}, "codebase": {}, "tech": {}}}


def _intake(bus):
    return bus.publish(Envelope(topic="research-findings", key="P1", actor="product", payload=TASK))


@pytest.fixture
def seen():
    _handler.seen = []  # type: ignore[attr-defined]
    return _handler.seen  # type: ignore[attr-defined]


def test_research_nhan_debate_va_audit_mot_lan(seen):
    bus = InMemoryBus(); client = FakeClient(handler=_handler)
    orch = Orchestrator(bus, client, roleplay=RolePlay(client, turn_limit=4))
    env = _intake(bus); orch.process(env)
    assert len(seen) == 1 and seen[0]["debate"]["proposals"] == ["web app"] and seen[0]["debate"]["stopped_by"] == "done"
    audits = [e for e in bus.replay(topic="audit-log") if e.payload["action"] == "research.debate"]
    assert len(audits) == 1 and audits[0].payload["tokens"] == 2 * 1300 and audits[0].payload["project_id"] == "P1"
    ev = json.loads(audits[0].payload["evidence"])
    assert ev["source_event"] == env.event_id and [t["role"] for t in ev["turns"]] == ["proposer", "critic"]
    assert [_who(c["system"]) for c in client.calls[:2]] == ["Vai đề xuất", "Vai phản biện"]


def test_chay_lai_cung_event_khong_ton_luot_model_nua(tmp_path, seen):
    """Khoá theo event nguồn, đọc từ bus (khuôn 2 `TRAPS.md`): mở lại bus và xử lý lại event thì lấy audit cũ."""
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db); c1 = FakeClient(handler=_handler)
    o1 = Orchestrator(bus, c1, roleplay=RolePlay(c1, turn_limit=4))
    env = _intake(bus); o1.process(env)
    n1 = len(c1.calls)
    bus2 = SQLiteBus(db); c2 = FakeClient(handler=_handler)
    o2 = Orchestrator(bus2, c2, roleplay=RolePlay(c2, turn_limit=4))
    with o2._lock: o2.processed.discard(env.event_id)   # cho xử lý lại như `_retry_unhandled`
    o2._recall("product", env); o2.process(env)
    assert n1 == 3 and [_who(c["system"]) for c in c2.calls] == ["product"], "lượt research chạy, debate thì không"
    assert seen[1]["debate"] == seen[0]["debate"]
    assert sum(1 for e in bus2.replay(topic="audit-log") if e.payload["action"] == "research.debate") == 1


def test_khong_bat_thi_khong_doi_gi(seen):
    bus = InMemoryBus(); client = FakeClient(handler=_handler)
    orch = Orchestrator(bus, client)
    orch.process(_intake(bus))
    assert orch.roleplay is None and "debate" not in seen[0] and [_who(c["system"]) for c in client.calls] == ["product"]


def test_debate_loi_model_thi_research_van_chay_kem_ly_do(seen):
    def boom(system, user):
        if _who(system) == "Vai đề xuất": raise LLMError("quota")
        return _handler(system, user)
    bus = InMemoryBus(); client = FakeClient(handler=boom)
    orch = Orchestrator(bus, client, roleplay=RolePlay(client, turn_limit=2))
    orch.process(_intake(bus))
    assert seen[0]["debate_error"].startswith("LLMError: quota") and "debate" not in seen[0]
    assert [e.payload["action"] for e in bus.replay(topic="audit-log") if e.payload["action"].startswith("research.debate")] \
        == ["research.debate_failed"]


def test_route_research_la_noi_duy_nhat_mang_enrich_debate():
    from company.orch.enrich import _with_debate
    co = [r for r in ROUTES if r.enrich is _with_debate]
    assert [(r.topic_in, r.phase, r.tools) for r in co] == [("research-findings", "research", "research")]


def test_cli_nhan_co_debate(tmp_path, monkeypatch):
    db = tmp_path / "c.sqlite"; SQLiteBus(db)
    built = {}
    from company.orch import cli as cli_mod
    real = cli_mod.RolePlay.from_env
    monkeypatch.setattr(cli_mod.RolePlay, "from_env", classmethod(lambda cls, client, **kw: built.setdefault("rp", real(client, **kw))))
    monkeypatch.delenv("COMPANY_DEBATE_TURNS", raising=False)
    assert orch_main(["--db", str(db), "--debate", "3", "status"]) == 0
    assert built["rp"].turn_limit == 3
    built.clear()
    assert orch_main(["--db", str(db), "status"]) == 0 and built["rp"] is None


def test_debate_dataclass_summary_khong_mang_transcript():
    d = Debate(turns=[{"role": "proposer", "message": "x" * 10_000, "points": [], "open_questions": []}],
               proposals=[], objections=[], open_questions=[], tokens=1, cost_usd=0.0, stopped_by="turn_limit")
    assert "turns" in d.as_audit() and len(json.dumps(d.summary())) < 200


def test_hai_du_an_hai_phien_rieng_khong_lay_nham_audit_cua_nhau(seen):
    """Khoá là `source_event`, không phải "audit research.debate gần nhất": dự án thứ hai phải chạy phiên của nó."""
    bus = InMemoryBus(); client = FakeClient(handler=_handler)
    orch = Orchestrator(bus, client, roleplay=RolePlay(client, turn_limit=4))
    orch.process(_intake(bus))
    e2 = bus.publish(Envelope(topic="research-findings", key="P2", actor="product", payload={**TASK, "project_id": "P2"}))
    orch.process(e2)
    audits = [json.loads(e.payload["evidence"])["source_event"] for e in bus.replay(topic="audit-log")
              if e.payload["action"] == "research.debate"]
    assert len(audits) == 2 and audits[1] == e2.event_id and len(seen) == 2
