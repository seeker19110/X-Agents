"""ADR gốc 0034: agent duyệt tự động `reviewer:tu-dong` — tiến trình riêng đọc hồ sơ `gate_brief`, hỏi model, ký qua
đúng đường `gate_reviewer.decide()`; không quyết được thì ghi `reviewer.hold` để phiên chính can thiệp.

Đo hai chiều: model `approve` → gate đóng có chữ ký; model `hold`/đầu ra hỏng/ngoài phạm vi → gate vẫn chờ, có
`reviewer.hold`; cùng (subject, thế hệ) không hỏi model lần hai.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from company import gate_reviewer as gr
from company.gate_cli import PersistentGate
from company.gate_cli import main as gate_main
from company.gates import GateRequest
from company.llm import FakeClient, LLMError
from company.roles import ROLE
from company.sqlite_bus import SQLiteBus
from test_gate_reviewer import DU_AN, TICKET, _gate

ID = "reviewer:tu-dong"
OK = {
    "decision": "approve",
    "root_cause": "builder hết lượt tool, WIP còn nguyên",
    "hint": "làm tiếp từ WIP, chạy test trước",
}


@pytest.fixture
def khoa(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv(gr.FLAG_ENV, "1")
    monkeypatch.setenv(gr.SCOPE_ENV, gr.SCOPE_TOAN_BO)
    monkeypatch.setenv(gr.REGISTRY_ENV, str(tmp_path / "registry.json"))
    return gr.new_key(ID, tmp_path / "registry.json", tmp_path / "keys")


@pytest.fixture
def brief(tmp_path) -> Path:
    p = tmp_path / "T1.json"
    p.write_text('{"subject_id": "T1"}', encoding="utf-8")
    return p


def _client(payload: dict | None = None, raise_: Exception | None = None) -> FakeClient:
    def h(system: str, user: str) -> dict:
        if raise_ is not None:
            raise raise_
        return payload or {}

    return FakeClient(handler=h)


def _holds(gate: PersistentGate) -> list[dict]:
    return [
        json.loads(e.payload["evidence"])
        for e in gate.bus.replay(topic="audit-log")
        if e.payload.get("action") == "reviewer.hold"
    ]


# ---------- prompt là code ----------


def test_prompt_reviewer_co_version_va_hop_dong_dau_ra():
    version, body = gr.load_prompt()
    assert isinstance(version, int) and version >= 1
    for tu in ("root_cause", "hint", "approve", "reject", "hold"):
        assert tu in body, f"prompt phải nêu `{tu}`"


def test_prompt_reviewer_duoc_uy_quyen_ky_mien_cve_va_dpia_du_lieu_gia():
    """ADR gốc 0036 (chủ repo chọn 2026-10-13): reviewer ký miễn CVE KHÔNG có bản sửa (danh sách + hạn xem lại trong
    root_cause) và DD-C6/DPIA CHỈ cho dữ liệu giả; mọi finding block khác vẫn `reject`/`hold`. Trước đó prompt cấm
    tuyệt đối "đổi chính sách bảo mật của khách" nên REL-022…035 kẹt chờ người dù chủ repo đã ủy quyền."""
    version, body = gr.load_prompt()
    assert version >= 2, "đổi luật ký là đổi prompt — tăng version"
    for tu in ("ADR gốc 0036", "không có bản sửa", "hạn xem lại", "dữ liệu giả", "dữ liệu thật"):
        assert tu in body, f"prompt phải nêu `{tu}`"


# ---------- review_one: hai chiều ----------


def test_model_approve_thi_gate_dong_co_chu_ky(khoa, brief):
    g = _gate("T1", TICKET)
    out = gr.review_one(g, "T1", "hồ sơ T1", brief, _client(OK), ID, khoa)
    assert out == "approve"
    assert "T1" not in g.pending and g.history[-1].decided_by == ID
    assert "root_cause:" in g.history[-1].reason and "hint:" in g.history[-1].reason
    assert not _holds(g)


def test_model_hold_thi_gate_van_cho_va_ghi_reviewer_hold(khoa, brief):
    g = _gate("T1", TICKET)
    out = gr.review_one(
        g,
        "T1",
        "hồ sơ T1",
        brief,
        _client({"decision": "hold", "root_cause": "không rõ nguyên nhân", "hint": ""}),
        ID,
        khoa,
    )
    assert out == "hold" and "T1" in g.pending
    h = _holds(g)
    assert len(h) == 1 and h[0]["subject_id"] == "T1" and "không rõ" in h[0]["reason"]
    assert h[0]["generation"] == gr.generation_of(g.pending["T1"])
    assert not any(e.payload.get("action") == "gate.decide" for e in g.bus.replay(topic="audit-log"))


@pytest.mark.parametrize(
    "payload", [{}, {"decision": "approve"}, {"decision": "maybe", "root_cause": "x", "hint": "y"}]
)
def test_dau_ra_khong_hop_le_thi_hold(khoa, brief, payload):
    g = _gate("T1", TICKET)
    assert gr.review_one(g, "T1", "hồ sơ", brief, _client(payload), ID, khoa) == "hold"
    assert "T1" in g.pending and "không hợp lệ" in _holds(g)[0]["reason"]


def test_model_loi_thi_hold_khong_no(khoa, brief):
    g = _gate("T1", TICKET)
    assert gr.review_one(g, "T1", "hồ sơ", brief, _client(raise_=LLMError("quota")), ID, khoa) == "hold"
    assert "quota" in _holds(g)[0]["reason"]


def test_ngoai_pham_vi_thi_code_chan_va_hold(khoa, brief, monkeypatch):
    """Model nói approve một gate spec khi phạm vi là `rong` (spec của người): `refusal()` chặn — hold kèm lý do."""
    monkeypatch.setenv(gr.SCOPE_ENV, gr.SCOPE_RONG)
    g = PersistentGate(_gate().bus)
    g.request(GateRequest(kind="spec", subject_id="SPEC-P1", created_by=ROLE.PRODUCT, checklist=["prd"]))
    assert gr.review_one(g, "SPEC-P1", "hồ sơ", brief, _client(OK), ID, khoa) == "hold"
    assert "SPEC-P1" in g.pending and "ngoài phạm vi" in _holds(g)[0]["reason"]


def test_reject_di_dung_duong_chu_ky(khoa, brief):
    g = _gate("T1", TICKET)
    out = gr.review_one(
        g,
        "T1",
        "hồ sơ",
        brief,
        _client({"decision": "reject", "root_cause": "lỗi thật trong code", "hint": "sửa X"}),
        ID,
        khoa,
    )
    assert out == "reject" and g.history[-1].decision == "reject" and g.history[-1].decided_by == ID


def test_ho_so_dai_bi_cat_theo_max_input_chars(khoa, brief):
    c = _client(OK)
    c.max_input_chars = 500  # type: ignore[attr-defined]
    gr.review_one(_gate("T1", TICKET), "T1", "x" * 10_000, brief, c, ID, khoa)
    assert len(c.calls[0]["user"]) <= 600


# ---------- held: phiên chính nhìn thấy ----------


def test_held_chi_tinh_the_he_hien_tai(khoa, brief):
    g = _gate("T1", TICKET)
    gr.review_one(g, "T1", "hồ sơ", brief, _client({"decision": "hold", "root_cause": "r", "hint": ""}), ID, khoa)
    assert set(gr.held(g)) == {"T1"} and gr.held(g)["T1"]["by"] == ID
    g.decide("T1", "reject", by="human:owner", reason="đóng")
    g.request(GateRequest(kind="escalation", subject_id="T1", created_by=ROLE.SUPERVISOR, checklist=TICKET))
    assert gr.held(g) == {}, "gate mở lại là thế hệ mới — hold cũ không còn tính"


def test_gate_cli_list_in_may_giu(khoa, brief, tmp_path, capsys):
    db = tmp_path / "c.sqlite"
    assert (
        gate_main(
            ["--db", str(db), "request", "escalation", "T1", "--by", ROLE.SUPERVISOR, "--checklist", ",".join(TICKET)]
        )
        == 0
    )
    bus = SQLiteBus(db)
    g = PersistentGate(bus)
    gr.review_one(
        g, "T1", "hồ sơ", brief, _client({"decision": "hold", "root_cause": "thiếu log", "hint": ""}), ID, khoa
    )
    bus.close()
    capsys.readouterr()
    assert gate_main(["--db", str(db), "list"]) == 0
    assert "máy giữ: thiếu log" in capsys.readouterr().out


# ---------- run_tick: một lượt mỗi thế hệ, trần mỗi vòng ----------


def _stub_brief(tmp_path):
    def f(orch, sid):
        p = tmp_path / f"{sid}.json"
        p.write_text(json.dumps({"subject_id": sid}), encoding="utf-8")
        return f"hồ sơ {sid}", p

    return f


def test_run_tick_khong_hoi_model_lan_hai_cho_cung_the_he(khoa, tmp_path):
    db = tmp_path / "c.sqlite"
    gate_main(
        ["--db", str(db), "request", "escalation", "T1", "--by", ROLE.SUPERVISOR, "--checklist", ",".join(TICKET)]
    )
    c = _client({"decision": "hold", "root_cause": "r", "hint": ""})
    assert gr.run_tick(db, ID, khoa, c, brief_fn=_stub_brief(tmp_path)) == [("T1", "hold")]
    assert gr.run_tick(db, ID, khoa, c, brief_fn=_stub_brief(tmp_path)) == []
    assert len(c.calls) == 1


def test_run_tick_tran_moi_vong(khoa, tmp_path):
    db = tmp_path / "c.sqlite"
    for sid in ("T1", "T2", "T3"):
        gate_main(
            ["--db", str(db), "request", "escalation", sid, "--by", ROLE.SUPERVISOR, "--checklist", ",".join(TICKET)]
        )
    c = _client(OK)
    assert [s for s, _ in gr.run_tick(db, ID, khoa, c, brief_fn=_stub_brief(tmp_path), max_per_tick=2)] == ["T1", "T2"]
    assert [s for s, _ in gr.run_tick(db, ID, khoa, c, brief_fn=_stub_brief(tmp_path), max_per_tick=2)] == ["T3"]
    assert "T3" not in PersistentGate(SQLiteBus(db)).pending


def test_run_tick_khong_cham_gate_da_ky_cho_du_co_tat(khoa, tmp_path, monkeypatch):
    """Gate reviewer đã ký mà cờ tắt (chữ ký chưa áp): không hỏi model lần nữa — `reviewer_signed_pending`."""
    db = tmp_path / "c.sqlite"
    gate_main(["--db", str(db), "request", "escalation", "P1", "--by", ROLE.SUPERVISOR, "--checklist", ",".join(DU_AN)])
    c = _client(OK)
    assert gr.run_tick(db, ID, khoa, c, brief_fn=_stub_brief(tmp_path)) == [("P1", "approve")]
    monkeypatch.delenv(gr.FLAG_ENV)
    assert "P1" in PersistentGate(SQLiteBus(db)).pending, "cờ tắt: chữ ký không áp, gate hiện lại"
    monkeypatch.setenv(gr.FLAG_ENV, "1")
    assert len(c.calls) == 1


# ---------- CLI: hồ sơ thật, model giả ----------


def test_cli_run_once_dung_ho_so_that_va_hold_khi_model_khong_tra_loi(khoa, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("COMPANY_LLM_PROVIDER", "fake")
    db = tmp_path / "c.sqlite"
    gate_main(["--db", str(db), "request", "escalation", "P1", "--by", ROLE.SUPERVISOR, "--checklist", ",".join(DU_AN)])
    assert gr.main(["--db", str(db), "run", "--id", "tu-dong", "--key", str(khoa), "--once"]) == 0
    out = capsys.readouterr().out
    assert "P1" in out and "hold" in out
    g = PersistentGate(SQLiteBus(db))
    assert "P1" in g.pending and gr.held(g)["P1"]["reason"]
    assert (tmp_path / "c.artifacts" / "_" / "gate-brief" / "P1.md").is_file(), "hồ sơ ghi ra đĩa như người đọc"
    capsys.readouterr()
    assert gr.main(["--db", str(db), "holds"]) == 0
    assert "P1" in capsys.readouterr().out


def test_held_bo_qua_evidence_khong_phai_json(khoa):
    """Bản ghi `reviewer.hold` hỏng (evidence không phải JSON) không làm `held()` nổ — bỏ qua như bản ghi lạ."""
    from company.events import AuditLog, Envelope

    g = _gate("T1", TICKET)
    g.bus.publish(
        Envelope(
            topic="audit-log",
            key=ID,
            actor=ID,
            payload=AuditLog(actor=ID, action=gr.HOLD_ACTION, evidence="không phải json").model_dump(),
        )
    )
    assert gr.held(g) == {}


def test_cli_holds_rong_noi_ro(tmp_path, capsys):
    db = tmp_path / "c.sqlite"
    gate_main(
        ["--db", str(db), "request", "escalation", "T1", "--by", ROLE.SUPERVISOR, "--checklist", ",".join(TICKET)]
    )
    assert gr.main(["--db", str(db), "holds"]) == 0
    assert "không giữ gate nào" in capsys.readouterr().out


def test_cli_run_watch_lap_va_thoat_sach_khi_sigint(khoa, tmp_path, monkeypatch, capsys):
    """Unit systemd dừng bằng SIGINT (`KillSignal=SIGINT`): vòng `--watch` phải thoát mã 0, không traceback —
    cùng khuôn `orchestrator run` bắt KeyboardInterrupt."""
    monkeypatch.setenv("COMPANY_LLM_PROVIDER", "fake")
    db = tmp_path / "c.sqlite"
    gate_main(
        ["--db", str(db), "request", "escalation", "T1", "--by", ROLE.SUPERVISOR, "--checklist", ",".join(TICKET)]
    )
    ngu: list[float] = []

    def sleep(s: float) -> None:
        ngu.append(s)
        if len(ngu) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(gr.time, "sleep", sleep)
    assert gr.main(["--db", str(db), "run", "--id", "tu-dong", "--key", str(khoa), "--watch", "7"]) == 0
    assert ngu == [7.0, 7.0]
    out = capsys.readouterr().out
    assert out.count("T1: hold") == 1, "vòng hai không hỏi lại gate đã giữ ở cùng thế hệ"


def test_prompt_he_thong_neu_tran_han_ky_mien_cve(khoa, brief, monkeypatch):
    """Hub REL-122: model ký hạn 90 ngày theo prompt tĩnh, dù dự án chỉ cho 7. Trần đang bật phải nằm trong prompt,
    để lượt đầu ký đúng. Nếu chỉ dựa vào `decide` thì model ký sai, bị chặn rồi thành hold, tốn thêm một lượt."""
    monkeypatch.setenv(gr.WAIVER_MAX_DAYS_ENV, "7")
    seen: list[str] = []
    def h(system: str, user: str) -> dict:
        seen.append(system); return OK
    gr.review_one(_gate("T1", TICKET), "T1", "hồ sơ", brief, FakeClient(handler=h), ID, khoa)
    assert "7 ngày" in seen[0] and gr.WAIVER_MAX_DAYS_ENV in seen[0]
