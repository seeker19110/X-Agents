"""Escalation của một RELEASE đi qua orchestrator: người chấp nhận (waive) hay từ chối (rework) — và trạng thái
"đã chấp nhận" phải sống sót qua restart bus. Xem `DeliveryLead.waive_release_findings`/`rework_release_tickets`.

Đo được 2026-09-05 (dự án QLKH): finding cấp release KHÔNG có code để sửa (DPIA — RISK-6) làm mọi ticket đã merged
trong release bị đá về rework và đốt retry, lặp qua nhiều release liên tiếp trên các ticket khác nhau.
"""
from __future__ import annotations

from company.events import Envelope, ReviewResult, Task
from company.gates import GateRequest
from company.llm import FakeClient
from company.orchestrator import Orchestrator
from company.sqlite_bus import SQLiteBus
from test_orchestrator import handler


def _blocked_release(orch, rid="REL-001", tid="T1"):
    """Dựng trạng thái: ticket đã merged, release chứa nó bị qa chặn, gate escalation của RELEASE đang chờ."""
    t = Task(ticket_id=tid, project_id="P", requirement_id="R1", assignee="builder", title=tid, acceptance=["a"])
    orch.lead.tickets[tid] = t
    orch.lead.state[tid] = "merged"
    orch.lead.releases.append(rid)
    orch.lead.release_tickets[rid] = [tid]
    orch.lead.release_reviews[rid]["qa"] = ReviewResult(
        ticket_id=rid, source="qa", verdict="fail",
        findings=[{"level": "block", "text": "DPIA (RISK-6) chưa hoàn thành"}])
    orch.gate.request(GateRequest(kind="escalation", subject_id=rid, created_by="delivery-lead",
                                  checklist=["root_cause", "decision:reopen|close", "hint"]))
    return rid, tid


def test_nguoi_chap_nhan_finding_cap_release_thi_khong_dung_ticket(tmp_path):
    bus = SQLiteBus(tmp_path / "c.sqlite")
    orch = Orchestrator(bus, FakeClient(handler=handler))
    rid, tid = _blocked_release(orch)

    orch.gate.decide(rid, "approve", by="human:owner", reason="dự án thử nghiệm, chấp nhận rủi ro DPIA")
    res = orch.run()

    assert orch.lead.release_waived[rid] == {"qa"}, "nguồn bị chặn được ghi nhận là đã chấp nhận"
    assert orch.lead.state[tid] == "merged" and orch.lead.tickets[tid].retry == 0, "ticket đã merged KHÔNG bị đụng"
    assert any(a.startswith(f"release_waived:{rid}:qa") for r in res for a in r.actions), [r.actions for r in res]
    acts = [e.payload["action"] for e in bus.replay(topic="audit-log")]
    assert "release.finding_waived" in acts, "phải có audit bền để dựng lại sau restart"

    # sống sót qua restart: bộ đếm/waiver dựng lại từ audit-log (cùng khuôn `ticket.blocked`, `integration.conflict`)
    bus.close()
    o2 = Orchestrator(SQLiteBus(tmp_path / "c.sqlite"), FakeClient(handler=handler))
    assert o2.lead.release_waived[rid] == {"qa"}


def test_nguoi_tu_choi_finding_cap_release_thi_ticket_moi_ve_rework(tmp_path):
    bus = SQLiteBus(tmp_path / "c.sqlite")
    orch = Orchestrator(bus, FakeClient(handler=handler))
    rid, tid = _blocked_release(orch)

    orch.gate.decide(rid, "reject", by="human:owner", reason="p95 480ms — lỗi thật, sửa code")
    res = orch.run()

    assert orch.lead.release_waived[rid] == set(), "từ chối thì không chấp nhận nguồn nào"
    # rework thật: retry+1 và hint là lý do người ghi. (Client giả chạy tiếp cả vòng nên state cuối có thể đã đi xa
    # hơn `dispatched` — bằng chứng bền là retry và event `tasks`, không phải trạng thái tức thời.)
    assert orch.lead.tickets[tid].retry == 1, "chỉ khi người từ chối mới rework"
    assert "p95" in (orch.lead.tickets[tid].hint or "")
    assert any(a == f"release_reworked:{rid}" for r in res for a in r.actions), [r.actions for r in res]
    tasks = [e for e in bus.replay(topic="tasks") if e.key == tid]
    assert tasks and tasks[-1].payload["retry"] == 1


def test_escalation_cua_release_khong_chan_gate_release_mo_sau_do(tmp_path):
    """`HumanGate.is_approved` không phân biệt kind: duyệt escalation của REL-001 từng làm gate release (Gate 3) của
    chính REL-001 không bao giờ mở được nữa. `DeliveryLead._gate_kind_approved` phân biệt kind cho đúng."""
    bus = SQLiteBus(tmp_path / "c.sqlite")
    orch = Orchestrator(bus, FakeClient(handler=handler))
    rid, _tid = _blocked_release(orch)
    orch.gate.decide(rid, "approve", by="human:owner", reason="chấp nhận")
    orch.run()

    assert rid in orch.gate.pending and orch.gate.pending[rid].kind == "release", \
        "đủ nguồn (qa đã waived) → mở gate release cho Gate 3, dù escalation cùng subject_id đã được duyệt"
    assert not orch.lead._gate_kind_approved(rid, "release") and orch.lead._gate_kind_approved(rid, "escalation")


def test_nguon_fail_sau_khi_da_ap_mien_thi_mo_escalation_moi(tmp_path):
    """Hub thật 2026-10-17 (QLKH-DD-CSV): escalation REL-* được duyệt và ÁP (miễn security) trước khi QA hồi quy báo
    fail. QA không nằm trong phần đã miễn, mà escalation mới bị chặn vì "escalation của RC này đã duyệt", nên Gate 3
    cần QA pass-hoặc-miễn không bao giờ mở: RC kẹt, không đường nào tự đi tiếp. Nguồn fail SAU khi miễn đã áp
    phải có escalation mới để reviewer xét đúng nguồn đó."""
    bus = SQLiteBus(tmp_path / "c.sqlite")
    orch = Orchestrator(bus, FakeClient(handler=handler))
    rid, tid = _blocked_release(orch)
    orch.lead.tickets[tid].risk_tags = ["crypto"]  # release cần cả security
    del orch.lead.release_reviews[rid]["qa"]
    orch.lead.release_reviews[rid]["security"] = ReviewResult(
        ticket_id=rid, source="security", verdict="block", findings=[{"level": "block", "text": "CVE không bản sửa"}])
    orch.gate.decide(rid, "approve", by="human:owner", reason="miễn CVE không bản sửa")
    orch.run()
    assert orch.lead.release_waived[rid] == {"security"} and rid not in orch.gate.pending

    orch.lead._on_release_qa(ReviewResult(ticket_id=rid, source="qa", verdict="fail",
                                          findings=[{"level": "block", "text": "RC không có ký miễn"}]))
    assert rid in orch.gate.pending and orch.gate.pending[rid].kind == "escalation", "nguồn mới fail → escalation mới"


def test_mien_da_duyet_nhung_chua_ap_thi_khong_mo_escalation_trung(tmp_path):
    """Chiều ngược lại (REL-126 thật): quyết định đã ký nhưng orchestrator chưa áp giữa hai lô. Nguồn fail tới lúc đó
    sẽ được chính lượt áp đó miễn (`waive_release_findings` lấy mọi nguồn chưa pass), nên không mở escalation trùng."""
    bus = SQLiteBus(tmp_path / "c.sqlite")
    orch = Orchestrator(bus, FakeClient(handler=handler))
    rid, _tid = _blocked_release(orch)
    orch.gate.decide(rid, "approve", by="human:owner", reason="miễn")
    orch.lead._on_release_qa(ReviewResult(ticket_id=rid, source="security", verdict="block", findings=[]))
    assert rid not in orch.gate.pending, "chưa áp miễn: không mở escalation trùng"


def test_escalation_cua_ticket_van_di_duong_cu(tmp_path):
    """Chốt chặn: nhánh mới chỉ bắt release_id. Escalation của TICKET vẫn `reopen` như trước (không rơi nhầm vào
    nhánh release)."""
    bus = SQLiteBus(tmp_path / "c.sqlite")
    orch = Orchestrator(bus, FakeClient(handler=handler))
    tid = "T9"
    orch.lead.tickets[tid] = Task(ticket_id=tid, project_id="P", requirement_id="R1", assignee="builder",
                                  title=tid, acceptance=["a"])
    orch.lead.state[tid] = "blocked"
    orch.gate.request(GateRequest(kind="escalation", subject_id=tid, created_by="supervisor",
                                  checklist=["root_cause", "decision:reopen|close", "hint"]))
    orch.gate.decide(tid, "approve", by="human:lead", reason="thử lại")
    res = orch.run()

    assert any(a == f"reopen:{tid}" for r in res for a in r.actions), [r.actions for r in res]
    assert [e for e in bus.replay(topic="tasks") if e.key == tid], "reopen phát lại task cho ticket"
    assert not any(a.startswith("release_") for r in res for a in r.actions)


def test_release_bi_chan_khong_con_tu_dong_day_ticket_ve_rework(tmp_path):
    """Đường đi thật (không dựng tay gate): review-results verdict fail cho một release → mở gate escalation của
    release, ticket giữ nguyên `merged`. Trước bản vá, chỗ này đá thẳng ticket về `changes_requested`."""
    bus = SQLiteBus(tmp_path / "c.sqlite")
    orch = Orchestrator(bus, FakeClient(handler=handler))
    tid, rid = "T1", "REL-001"
    orch.lead.tickets[tid] = Task(ticket_id=tid, project_id="P", requirement_id="R1", assignee="builder",
                                  title=tid, acceptance=["a"])
    orch.lead.state[tid] = "merged"
    orch.lead.releases.append(rid); orch.lead.release_tickets[rid] = [tid]

    bus.publish(Envelope(topic="review-results", key=rid, actor="qa",
                         payload=ReviewResult(ticket_id=rid, source="qa", verdict="fail",
                                              findings=[{"level": "block", "text": "DPIA chưa hoàn thành"}]).model_dump()))
    orch.run()

    assert orch.lead.state[tid] == "merged" and orch.lead.tickets[tid].retry == 0
    assert rid in orch.gate.pending and orch.gate.pending[rid].kind == "escalation"


def test_release_check_cong_don_theo_du_an_khong_chi_ticket_trong_rc(tmp_path):
    """Nhánh tích hợp CỘNG DỒN: RC sau chứa mọi code của RC trước. RC chỉ gồm ticket không `risk_tags` mà dự án đã có
    ticket `pii`/`auth` ở RC trước thì vẫn phải qua release-check của security. Đo được hub thật 2026-10-13
    (QLKH-DD-CSV): REL-036 chỉ có DDCSV-33 (vá image, không nhãn) lên thẳng Gate 3, không SCA/DAST, dù sha b2ec63b chứa
    mọi thứ security đã chặn ở REL-035."""
    orch = Orchestrator(SQLiteBus(tmp_path / "c.sqlite"), FakeClient(handler=handler))
    lead = orch.lead
    for tid, rid, pid, tags in (("T1", "REL-001", "P", ["pii"]), ("T2", "REL-002", "P", []), ("X1", "REL-003", "Q", [])):
        lead.tickets[tid] = Task(ticket_id=tid, project_id=pid, requirement_id="R1", assignee="builder", title=tid,
                                 acceptance=["a"], risk_tags=tags)
        lead.releases.append(rid); lead.release_tickets[rid] = [tid]
    assert lead.release_needs_security("REL-002"), "RC sau của cùng dự án mang code pii của RC trước"
    assert not lead.release_needs_security("REL-003"), "dự án khác không có ticket rủi ro thì không cần"
    assert not lead.release_needs_security("REL-404"), "RC lạ (chưa có trong sổ): không ticket nào, không cần"


def test_tu_choi_rc_deploy_hong_thi_ticket_approved_cung_ve_rework(tmp_path):
    """Hub thật 2026-10-16 (REL-113, DDCSV-142): deploy staging hỏng ⇒ ticket chưa từng lên `merged` (chỉ staging
    `deployed` mới đẩy approved → merged). Từ chối escalation chỉ đụng `merged` ⇒ không ai làm lại, hint đúng nguyên
    nhân rơi mất, mà orchestrator vẫn ghi `release_reworked`."""
    bus = SQLiteBus(tmp_path / "c.sqlite")
    orch = Orchestrator(bus, FakeClient(handler=handler))
    rid, tid = _blocked_release(orch)
    orch.lead.state[tid] = "approved"

    orch.gate.decide(rid, "reject", by="human:owner", reason="secret nguồn environment trong service read_only")
    res = orch.run()

    assert orch.lead.tickets[tid].retry == 1 and "read_only" in (orch.lead.tickets[tid].hint or "")
    assert any(a == f"release_reworked:{rid}" for r in res for a in r.actions), [r.actions for r in res]


def test_tu_choi_rc_khong_con_ticket_nao_de_lam_lai_thi_nop_cr(tmp_path):
    """Không ticket nào của RC còn làm lại được (đã đóng): lý do từ chối phải tới planner qua CR, không được ghi
    `release_reworked` rồi nuốt mất."""
    bus = SQLiteBus(tmp_path / "c.sqlite")
    orch = Orchestrator(bus, FakeClient(handler=handler))
    rid, tid = _blocked_release(orch)
    orch.lead.state[tid] = "closed"

    orch.gate.decide(rid, "reject", by="human:owner", reason="secret nguồn environment trong service read_only")
    res = orch.run()

    acts = [a for r in res for a in r.actions]
    assert f"release_reworked:{rid}" not in acts and f"release_rework_outside:{rid}" in acts, acts
    crs = [e for e in bus.replay(topic="change-requests") if e.key.startswith(f"REWORK-{rid}-")]
    assert crs and "read_only" in crs[0].payload["description"]
