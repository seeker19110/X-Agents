"""ADR gốc 0021 (N1): orchestrator đăng ký run quality cho dự án có ProjectProfile người ký kèm spec, chiếu
`lead.state` sang journal, và `quality:accept` chỉ do trusted driver nộp qua `commit_quality_result`.

Receipt ở đây là fixture tổng hợp ký bằng khoá Ed25519 sinh lúc chạy — không phải bằng chứng sản phẩm thật."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from xagents_core.execution import (
    ExecutionEventKind,
    ExecutionJournal,
    RunStatus,
    TaskResult,
    TaskStatus,
)

from company.events import Task
from company.gate_cli import main as gate_main
from company.llm import FakeClient
from company.orch import quality_flow, quality_release
from company.orchestrator import Orchestrator
from company.product_quality import CATALOG, Evidence, sign_evidence
from company.quality_execution import QUALITY_TASK_ID
from company.sqlite_bus import SQLiteBus
from test_orchestrator import T1, _drive_to_spec_gate, handler
from test_product_quality import make_profile
from test_receipt_signature import ED25519_POLICY, key_id_of, pem_of
from test_tools_and_agentic import _init_repo, _repo_tool_handler

RUN = "run-P1"
SCOPES = {"ci": ("runtime-ci", "runner"), "qa": ("independent-qa", "independent_review")}


def v4_profile(**changes):
    return make_profile(**{"project_id": "P1", "run_id": RUN, "evidence_policy": ED25519_POLICY, **changes})


def write_trust(path: Path, signers: dict[str, Ed25519PrivateKey]) -> Path:
    not_after = (datetime.now(UTC) + timedelta(days=90)).isoformat()
    doc = {issuer: {"principal_id": SCOPES[issuer][0], "mode": SCOPES[issuer][1],
                    "allowed_checks": sorted(k for k, c in CATALOG.items() if c.mode == SCOPES[issuer][1]),
                    "keys": [{"key_id": key_id_of(key), "public_key_pem": pem_of(key), "not_after": not_after}]}
           for issuer, key in signers.items()}
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


@dataclass
class FakeDriver:
    """Trusted driver giả: đọc bindings coordinator đã ghim trong journal, ký receipt pass cho từng check."""

    signers: dict[str, Ed25519PrivateKey]
    drop: frozenset[str] = frozenset()
    o: Orchestrator | None = None
    calls: list[tuple[str, str, tuple[str, ...]]] = field(default_factory=list)

    def run(self, run_id: str, checks: tuple[str, ...]) -> tuple[TaskResult, list]:
        assert self.o is not None
        b = quality_flow.active_bindings(self.o, run_id)
        assert b is not None
        self.calls.append((run_id, b.expected_attempt_id, checks))
        root = quality_flow.evidence_root(self.o, run_id)
        root.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC)
        receipts = []
        for check_id in checks:
            if check_id in self.drop: continue
            issuer = "ci" if CATALOG[check_id].mode == "runner" else "qa"
            art = root / f"{check_id}.txt"
            art.write_text(f"synthetic {check_id}\n", encoding="utf-8")
            ev = Evidence(schema_version=1, check_id=check_id, run_id=run_id, candidate_sha=b.candidate_sha,
                          context_hash=b.context_hash, contract_hash=b.expected_contract_hash, issuer=issuer,
                          status="pass", created_at=now - timedelta(minutes=1), expires_at=now + timedelta(hours=1),
                          artifact_path=art.name, artifact_sha256=hashlib.sha256(art.read_bytes()).hexdigest(),
                          details="Synthetic fixture; not a real product test.",
                          covered_acceptance=["AC-1"] if check_id == "testing.acceptance" else [],
                          measurements={"latency-p95": 100.0} if check_id == "performance.budget" else {})
            receipts.append(sign_evidence(ev, self.signers[issuer], key_id_of(self.signers[issuer])))
        result = TaskResult(QUALITY_TASK_ID, b.expected_attempt_id, TaskStatus.SUCCEEDED, b.expected_base_sha,
                            b.candidate_sha, b.expected_diff_hash)
        return result, receipts


def _signers():
    return {"ci": Ed25519PrivateKey.generate(), "qa": Ed25519PrivateKey.generate()}


def _journal(tmp_path: Path) -> ExecutionJournal:
    return ExecutionJournal(tmp_path / "c.quality.sqlite")


def _start(tmp_path: Path, driver: FakeDriver | None, *, profile=None, trust: Path | None = None):
    repo = tmp_path / "repo"
    if not repo.exists(): _init_repo(repo)
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db)
    o = Orchestrator(bus, FakeClient(handler=handler, tool_handler=_repo_tool_handler), repo=repo, base="main",
                     quality_driver=driver, quality_trust=trust)
    if driver is not None: driver.o = o
    return bus, o


def _sign_spec_with_profile(tmp_path: Path, bus, o, profile=None) -> None:
    _drive_to_spec_gate(bus, o)
    pf = tmp_path / "profile.json"
    pf.write_text((profile or v4_profile()).model_dump_json(), encoding="utf-8")
    assert gate_main(["--db", str(tmp_path / "c.sqlite"), "approve", "SPEC-P1", "--by", "human:po",
                      "--quality-profile", str(pf)]) == 0
    o.tick()


def _quality_starts(tmp_path: Path) -> list:
    with _journal(tmp_path) as j:
        return [e for e in j.events(RUN) if e.task_id == QUALITY_TASK_ID and e.kind is ExecutionEventKind.TASK_STARTED]


# ---------- e2e: đủ receipt / thiếu receipt ----------

def test_e2e_du_receipt_thi_quality_accept_succeeded(tmp_path):
    signers = _signers()
    driver = FakeDriver(signers)
    bus, o = _start(tmp_path, driver, trust=write_trust(tmp_path / "trust.json", signers))
    _sign_spec_with_profile(tmp_path, bus, o)
    assert o.lead.state["T1"] == "merged" and o.lead.state["T2"] == "merged", o.lead.state
    with _journal(tmp_path) as j:
        state = j.resume(RUN)
        assert state.status is RunStatus.SUCCEEDED, state
        assert state.tasks == {"T1": TaskStatus.SUCCEEDED, "T2": TaskStatus.SUCCEEDED,
                               QUALITY_TASK_ID: TaskStatus.SUCCEEDED}
    [(run_id, attempt, checks)] = driver.calls
    assert run_id == RUN and attempt == f"REL-002@{o.release_sha['REL-002']}", "candidate = sha đã staged của RC"
    assert "goal.traceability" in checks
    assert not [t for t in o.lead.tickets if t.startswith("quality:")], "không agent nào được giao quality:accept"
    assert not [e for e in bus.replay(topic="tasks") if str(e.key).startswith("quality:")]


def test_e2e_thieu_mot_receipt_thi_failed_voi_check_missing(tmp_path):
    signers = _signers()
    driver = FakeDriver(signers, drop=frozenset({"goal.traceability"}))
    bus, o = _start(tmp_path, driver, trust=write_trust(tmp_path / "trust.json", signers))
    _sign_spec_with_profile(tmp_path, bus, o)
    with _journal(tmp_path) as j:
        state = j.resume(RUN)
    assert state.tasks[QUALITY_TASK_ID] is TaskStatus.FAILED
    assert "goal.traceability:missing" in state.blocked_reason
    assert o.lead.state["T1"] == "merged", "task công việc chạy như cũ dù nghiệm thu hỏng"


def test_khong_driver_thi_quality_accept_dung_running_cho_toi_khi_co_receipt(tmp_path):
    bus, o = _start(tmp_path, None)
    _sign_spec_with_profile(tmp_path, bus, o)
    o.tick()
    with _journal(tmp_path) as j:
        assert j.resume(RUN).tasks[QUALITY_TASK_ID] is TaskStatus.RUNNING
    assert len(_quality_starts(tmp_path)) == 1


# ---------- restart ----------

def test_restart_giua_task_started_va_submit_resume_dung_khong_nhan_doi(tmp_path):
    bus, o = _start(tmp_path, None)
    _sign_spec_with_profile(tmp_path, bus, o)
    with _journal(tmp_path) as j:
        before = j.events(RUN)
    [started] = _quality_starts(tmp_path)
    bus.close()

    signers = _signers()
    driver = FakeDriver(signers)
    _bus2, o2 = _start(tmp_path, driver, trust=write_trust(tmp_path / "trust.json", signers))
    with _journal(tmp_path) as j:
        assert j.events(RUN) == before, "mở lại (chỉ đọc) không ghi journal"
    o2.gate.decide("REL-001", "approve", by="human:rm")  # một event bất kỳ đi qua _mark
    o2.run()
    with _journal(tmp_path) as j:
        after = j.events(RUN)
        assert j.resume(RUN).status is RunStatus.SUCCEEDED
    assert after[:len(before)] == before and len(after) == len(before) + 1, "chỉ thêm đúng một kết quả"
    assert [c[1] for c in driver.calls] == [started.payload["attempt_id"]], "driver chạy lại CÙNG attempt"
    assert len({e.event_id for e in after}) == len(after)


# ---------- ranh giới tin cậy ----------

def test_ke_hoach_tu_agent_co_task_quality_bi_tu_choi():
    from company.bus import InMemoryBus
    o = Orchestrator(InMemoryBus(), FakeClient(handler=handler))
    bad = Task.model_validate({**T1, "ticket_id": "quality:accept"})
    assert any("quality:" in p for p in o._check_plan([bad], "P1"))


def test_approve_spec_thieu_quality_profile_khi_du_an_da_co_profile_bi_tu_choi(tmp_path):
    bus, o = _start(tmp_path, None)
    _drive_to_spec_gate(bus, o)
    pf = tmp_path / "profile.json"
    pf.write_text(v4_profile().model_dump_json(), encoding="utf-8")
    db = str(tmp_path / "c.sqlite")
    assert gate_main(["--db", db, "request_changes", "SPEC-P1", "--by", "human:po", "--quality-profile", str(pf)]) == 2
    assert gate_main(["--db", db, "approve", "SPEC-P1", "--by", "human:po", "--quality-profile", str(pf)]) == 0
    # spec mở gate lại (pha spec chạy lại sau thay đổi): dự án ĐÃ có profile ⇒ ký thiếu cờ bị từ chối
    assert gate_main(["--db", db, "request", "spec", "SPEC-P1", "--by", "product", "--checklist", "prd"]) == 0
    assert gate_main(["--db", db, "approve", "SPEC-P1", "--by", "human:po"]) == 2
    gate = SQLiteBus(tmp_path / "c.sqlite")
    pending = [e for e in gate.replay(topic="audit-log") if e.payload.get("action") == "gate.decide"]
    assert len(pending) == 1, "lần ký thiếu cờ không để lại quyết định nào"
    assert gate_main(["--db", db, "approve", "SPEC-P1", "--by", "human:po", "--quality-profile", str(pf)]) == 0


def test_approve_spec_chua_tung_co_profile_giu_hanh_vi_cu(tmp_path):
    bus, o = _start(tmp_path, None)
    _drive_to_spec_gate(bus, o)
    assert gate_main(["--db", str(tmp_path / "c.sqlite"), "approve", "SPEC-P1", "--by", "human:po"]) == 0
    o.tick()
    assert o.lead.state["T1"] == "merged"
    assert not (tmp_path / "c.quality.sqlite").exists(), "không profile ⇒ không file journal"
    acts = {e.payload["action"] for e in bus.replay(topic="audit-log")}
    assert not {a for a in acts if a.startswith("quality.")}


def test_register_quality_run_tu_choi_profile_legacy(tmp_path):
    _bus, o = _start(tmp_path, None)
    o.plans["PLAN-P1-1"] = {"plan_id": "PLAN-P1-1", "project_id": "P1", "source_topic": "approved-specs",
                            "tickets": [T1]}
    legacy = make_profile(project_id="P1", run_id=RUN)
    with pytest.raises(ValueError, match="allowed_schemes"):
        quality_flow.register_quality_run(o, "PLAN-P1-1", legacy)
    assert not (tmp_path / "c.quality.sqlite").exists()


# ---------- biên: chiếu ticket, lỗi đồng bộ, profile hỏng, CLI commit ----------

PLAN = {"plan_id": "PLAN-P1-1", "project_id": "P1", "source_topic": "approved-specs", "tickets": [T1]}


def _pin(o, db: Path, profile=None, pid: str = "P1") -> Path:
    from company.product_quality import compile_contract
    from company.quality_execution import pinned_profile_path
    profile = profile or v4_profile()
    raw = profile.model_dump_json().encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    path = pinned_profile_path(db, pid, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    quality_flow.note_profile(o, {"project_id": pid, "run_id": profile.run_id, "profile_sha256": digest,
                                  "contract_hash": compile_contract(profile)["contract_hash"]})
    return path


def _unit(tmp_path: Path, **kw):
    bus = SQLiteBus(tmp_path / "c.sqlite")
    return bus, Orchestrator(bus, FakeClient(handler=handler), **kw)


def _acts(bus, action: str) -> list[dict]:
    return [json.loads(e.payload["evidence"]) for e in bus.replay(topic="audit-log") if e.payload.get("action") == action]


def _task(bus):
    from company.events import Envelope
    return bus.publish(Envelope(topic="tasks", key="T1", actor="delivery-lead", payload=T1))


def test_chieu_ticket_lam_lai_va_giao_lai_thanh_attempt_moi_roi_succeeded(tmp_path):
    bus, o = _unit(tmp_path)
    _pin(o, tmp_path / "c.sqlite"); o.plans["PLAN-P1-1"] = PLAN
    o.lead.state["T1"] = "dispatched"; _task(bus)
    quality_flow.sync_quality(o)
    o.lead.state["T1"] = "changes_requested"
    quality_flow.sync_quality(o)
    o.lead.state["T1"] = "dispatched"; _task(bus)
    quality_flow.sync_quality(o)
    _task(bus)  # giao lại mà sync không kịp thấy changes_requested
    quality_flow.sync_quality(o)
    o.lead.state["T1"] = "approved"; o.lead.integrated.add("T1")
    quality_flow.sync_quality(o); quality_flow.sync_quality(o)
    with _journal(tmp_path) as j:
        ids = [e.event_id.removeprefix(f"{RUN}:") for e in j.events(RUN)]
        assert j.resume(RUN).tasks == {"T1": TaskStatus.SUCCEEDED, QUALITY_TASK_ID: TaskStatus.READY}
    assert ids == ["run:start", "T1:start:0", "T1:fail:0", "T1:retry:0", "T1:start:1", "T1:fail:1", "T1:retry:1",
                   "T1:start:2", "T1:ok"]
    assert _acts(bus, "quality.registered") == [{"project_id": "P1", "plan_id": "PLAN-P1-1", "run_id": RUN,
                                                 "contract_hash": o.quality_profiles["P1"]["contract_hash"]}]
    assert quality_flow.active_bindings(o, RUN) is None, "chưa mở attempt quality nào"
    assert quality_release.runs_for_release(o, "REL-X") == ()
    # RC huỷ bị bỏ qua; RC còn lại không có nhánh tích hợp (không --repo) ⇒ không tính được bindings ⇒ sync_error
    o.lead.releases += ["REL-1", "REL-2"]; o.lead.release_tickets.update({"REL-1": ["T1"], "REL-2": ["T1"]})
    o.void_releases.add("REL-2"); o.release_sha.update({"REL-1": "a" * 40, "REL-2": "b" * 40})
    quality_flow.sync_quality(o)
    [err] = _acts(bus, "quality.sync_error")
    assert err["run_id"] == RUN and "nhánh tích hợp" in err["error"]
    assert RUN in o.paused and "P1" not in o.paused, "escalate theo run, không chặn vòng ticket của dự án"
    quality_flow.note_profile(o, {"project_id": "P2", "run_id": "run-P2"})  # run chưa đăng ký: không thuộc RC nào
    assert quality_release.runs_for_release(o, "REL-1") == ((RUN, "ready", None),)


def test_bus_khong_ben_thi_khong_doc_duoc_profile_va_khong_vo_vong_mark():
    from company.bus import InMemoryBus
    bus = InMemoryBus(); o = Orchestrator(bus, FakeClient(handler=handler))
    quality_flow.note_profile(o, {"project_id": "P1", "run_id": RUN, "profile_sha256": "a" * 64, "contract_hash": "b"})
    o.plans["PLAN-P1-1"] = PLAN
    quality_flow.sync_quality(o)
    assert ["bus SQLite" in json.loads(e.payload["evidence"])["reason"] for e in bus.replay(topic="audit-log")
            if e.payload.get("action") == "quality.profile_invalid"] == [True]


def test_registry_nam_trong_worktree_bi_tu_choi(tmp_path):
    repo = tmp_path / "repo"; (repo / ".git").mkdir(parents=True)
    _bus, o = _unit(tmp_path, repo=repo, quality_trust=repo / ".worktrees" / "T1" / "trust.json")
    o.plans["PLAN-P1-1"] = PLAN
    with pytest.raises(ValueError, match="worktree"):
        quality_flow.register_quality_run(o, "PLAN-P1-1", v4_profile())
    with pytest.raises(ValueError, match="kế hoạch"):
        quality_flow.register_quality_run(o, "PLAN-P1-1", v4_profile(project_id="P9"))


def test_ban_ghi_profile_hong_hoac_thieu_du_an_khong_ghi_nhan(tmp_path):
    from company.events import AuditLog, Envelope
    bus, o = _unit(tmp_path)
    for ev in ("not json", "[1]", json.dumps({"run_id": RUN})):
        bus.publish(Envelope(topic="audit-log", key="human:po", actor="human:po",
                             payload=AuditLog(actor="human:po", action="quality.profile_set", evidence=ev).model_dump()))
    assert o.quality_profiles == {}
    with pytest.raises(Exception, match="chỉ người"):
        bus.publish(Envelope(topic="audit-log", key="builder", actor="builder",
                             payload=AuditLog(actor="builder", action="quality.profile_set", evidence="{}").model_dump()))


def test_profile_bi_sua_sau_khi_ky_thi_khong_dang_ky_va_audit_mot_lan(tmp_path):
    bus, o = _unit(tmp_path)
    path = _pin(o, tmp_path / "c.sqlite"); o.plans["PLAN-P1-1"] = PLAN
    path.write_text(v4_profile(goal="Một mục tiêu khác người chưa ký.").model_dump_json(), encoding="utf-8")
    quality_flow.sync_quality(o); quality_flow.sync_quality(o)
    assert len(_acts(bus, "quality.profile_invalid")) == 1
    assert not (tmp_path / "c.quality.sqlite").exists()
    o.quality_profiles["P1"]["profile_sha256"] = "zz"  # dấu băm không hợp lệ ⇒ không bao giờ thành đường dẫn
    quality_flow.sync_quality(o)
    assert "ValueError" in _acts(bus, "quality.profile_invalid")[-1]["reason"]
    with pytest.raises(ValueError, match="profile hợp lệ"):
        quality_flow.submit_quality(o, RUN, None, [])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="profile hợp lệ"):
        quality_flow.submit_quality(o, "run-khong-co", None, [])  # type: ignore[arg-type]


def test_submit_thieu_registry_bi_tu_choi_va_ke_hoach_cr_khong_vao_run(tmp_path):
    _bus, o = _unit(tmp_path)
    _pin(o, tmp_path / "c.sqlite")
    o.plans["PLAN-P1-1"] = {**PLAN, "source_topic": "change-requests"}
    assert quality_flow._plan_for(o, "P1") is None
    # spec của CR đổi requirement (key chuỗi = mã CR, hub 2026-10-14) cũng là `approved-specs` nhưng không phải của run
    o.plans["PLAN-P1-9"] = {**PLAN, "plan_id": "PLAN-P1-9", "source_key": "CR-1"}
    assert quality_flow._plan_for(o, "P1") is None
    o.plans["PLAN-P1-2"] = {**PLAN, "plan_id": "PLAN-P1-2"}
    assert quality_flow._plan_for(o, "P1") == "PLAN-P1-2"
    with pytest.raises(ValueError, match="registry"):
        quality_flow.submit_quality(o, RUN, None, [])  # type: ignore[arg-type]


def test_candidate_khong_co_trong_repo_thi_sync_error(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    bus, o = _unit(tmp_path, repo=repo, base="main")
    _pin(o, tmp_path / "c.sqlite"); o.plans["PLAN-P1-1"] = PLAN
    o.lead.state["T1"] = "approved"; o.lead.integrated.add("T1"); _task(bus)
    o.lead.releases.append("REL-1"); o.lead.release_tickets["REL-1"] = ["T1"]; o.release_sha["REL-1"] = "f" * 40
    quality_flow.sync_quality(o)
    assert "gốc/diff" in _acts(bus, "quality.sync_error")[0]["error"]


def _to_running(tmp_path):
    bus, o = _start(tmp_path, None)
    _sign_spec_with_profile(tmp_path, bus, o)
    return bus, o


def test_driver_loi_thanh_sync_error_roi_driver_tot_nghiem_thu_duoc(tmp_path):
    bus, o = _to_running(tmp_path)

    class Boom:
        def run(self, run_id, checks):
            raise RuntimeError("trình duyệt chết")

    o.quality_driver = Boom()
    quality_flow.sync_quality(o)
    assert "driver: RuntimeError" in _acts(bus, "quality.sync_error")[0]["error"]
    signers = _signers()
    o.quality_trust = write_trust(tmp_path / "trust.json", signers)
    o.quality_driver = good = FakeDriver(signers, o=o)
    quality_flow.sync_quality(o)
    assert good.calls == [], "cùng attempt, escalation chưa xử lý ⇒ không chạy lại (N1.b)"
    o.tick()
    o.gate.decide(RUN, "approve", by="human:rm", reason="đã thay driver trình duyệt chết bằng driver chạy được")
    o.run()
    rid = o.lead.releases[-1]
    assert quality_release.runs_for_release(o, rid) == ((RUN, "succeeded", o.release_sha[rid]),)


def test_quality_hong_roi_sha_moi_duoc_staged_thi_attempt_moi(tmp_path):
    import subprocess
    signers = _signers()
    driver = FakeDriver(signers, drop=frozenset({"goal.traceability"}))
    bus, o = _start(tmp_path, driver, trust=write_trust(tmp_path / "trust.json", signers))
    _sign_spec_with_profile(tmp_path, bus, o)
    quality_flow.sync_quality(o)  # cùng candidate đã hỏng: không tự chấm lại
    assert len(driver.calls) == 1
    wt = tmp_path / "repo" / ".worktrees" / "_integration"
    (wt / "fix.py").write_text("X = 1\n", encoding="utf-8")
    for args in (["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "fix"]):
        subprocess.run(["git", "-C", str(wt), *args], check=True, capture_output=True)
    sha = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"], check=True, capture_output=True,
                         text=True).stdout.strip()
    o.lead.releases.append("REL-009"); o.lead.release_tickets["REL-009"] = ["T1", "T2"]; o.release_sha["REL-009"] = sha
    driver.drop = frozenset()
    quality_flow.sync_quality(o)
    assert driver.calls[-1][1] == f"REL-009@{sha}"
    with _journal(tmp_path) as j:
        assert j.resume(RUN).status is RunStatus.SUCCEEDED
        assert f"{RUN}:quality:retry:{driver.calls[0][1]}" in {e.event_id for e in j.events(RUN)}


def test_cli_commit_doc_bindings_tu_journal(tmp_path, capsys):
    from company.quality_execution import _result_document, main
    _bus, o = _to_running(tmp_path)
    signers = _signers()
    driver = FakeDriver(signers, o=o)
    result, receipts = driver.run(RUN, tuple(sorted(c.id for c in __import__(
        "company.product_quality", fromlist=["required_checks"]).required_checks(v4_profile()))))
    files = {"result": _result_document(result), "receipts": [r.model_dump(mode="json") for r in receipts]}
    for name, doc in files.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(doc), encoding="utf-8")
    base = ["commit", RUN, "--journal", str(tmp_path / "c.quality.sqlite"), "--profile", str(tmp_path / "profile.json"),
            "--result", str(tmp_path / "result.json"), "--receipts", str(tmp_path / "receipts.json"),
            "--trust", str(write_trust(tmp_path / "trust.json", signers)),
            "--evidence-root", str(quality_flow.evidence_root(o, RUN))]
    capsys.readouterr()
    assert main(base) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "succeeded"
    assert main(base) == 0, "nộp lại cùng kết quả ⇒ ACK"
    (tmp_path / "bad.json").write_text("{}", encoding="utf-8")
    other = tmp_path / "other.json"; other.write_text(v4_profile(run_id="run-khac").model_dump_json(), encoding="utf-8")
    for swap in ({"--receipts": "bad.json"}, {"--profile": "other.json"}, {"--journal": "khong-co.sqlite"}):
        argv = list(base)
        for flag, name in swap.items(): argv[argv.index(flag) + 1] = str(tmp_path / name)
        assert main(argv) == 2


def test_result_from_document_la_nghich_dao_cua_result_document():
    from xagents_core.execution import ArtifactRef, DecisionRequest, EvidenceReceipt

    from company.quality_execution import _result_document, result_from_document
    r = TaskResult(QUALITY_TASK_ID, "a1", TaskStatus.FAILED, "c" * 40, "d" * 40, "e" * 64,
                   artifacts=(ArtifactRef("x.txt", "f" * 64),),
                   evidence=(EvidenceReceipt("pytest", ".", 0, "d" * 40, "0" * 64, datetime.now(UTC), 1.0),),
                   findings=("x",), unresolved=(DecisionRequest("D1", "?", "vì", ("a", "b")),))
    assert result_from_document(json.loads(json.dumps(_result_document(r)))) == r


def test_bindings_trong_journal_hong_thi_khong_nop_duoc(tmp_path):
    from xagents_core.execution import ExecutionEvent, ExecutionJournalError

    from company.quality_execution import bindings_from_journal, compile_execution
    from test_quality_execution import work_for
    profile = v4_profile()
    good = {"expected_attempt_id": "a1", "expected_base_sha": "c" * 40, "expected_diff_hash": "d" * 64,
            "expected_contract_hash": "e" * 64, "candidate_sha": "f" * 40, "context_hash": "0" * 64,
            "author_principals": ["builder"]}
    for i, (payload, match) in enumerate([({"attempt_id": "a1"}, "no coordinator-bound"),
                                          ({"attempt_id": "a1", "bindings": {"x": 1}}, "malformed"),
                                          ({"attempt_id": "a2", "bindings": good}, "do not belong")]):
        with ExecutionJournal(tmp_path / f"j{i}.sqlite") as j:
            spec = compile_execution(profile, work_for(profile))
            j.register(spec)
            j.transition(ExecutionEvent(RUN, ExecutionEventKind.RUN_STARTED), expected_count=0)
            for t in spec.tasks:
                n = len(j.events(RUN))
                j.transition(ExecutionEvent(RUN, ExecutionEventKind.TASK_STARTED, t.task_id,
                                            payload=payload if t.task_id == QUALITY_TASK_ID else {}), expected_count=n)
                if t.task_id != QUALITY_TASK_ID:
                    j.transition(ExecutionEvent(RUN, ExecutionEventKind.TASK_SUCCEEDED, t.task_id), expected_count=n + 1)
            with pytest.raises(ExecutionJournalError, match=match):
                bindings_from_journal(j, RUN)
    assert bindings_from_journal.__module__ == "company.quality_execution"


@pytest.mark.parametrize("profile,msg", [
    (lambda: v4_profile(project_id="P9"), "khác dự án"),
    (lambda: make_profile(project_id="P1", run_id=RUN), "allowed_schemes"),
    (None, "FileNotFoundError"),
])
def test_approve_spec_voi_profile_hong_thi_chua_ky(tmp_path, capsys, profile, msg):
    bus, o = _start(tmp_path, None)
    _drive_to_spec_gate(bus, o)
    pf = tmp_path / "profile.json"
    if profile is not None: pf.write_text(profile().model_dump_json(), encoding="utf-8")
    assert gate_main(["--db", str(tmp_path / "c.sqlite"), "approve", "SPEC-P1", "--by", "human:po",
                      "--quality-profile", str(pf)]) == 2
    assert msg in capsys.readouterr().err
    o.tick()
    assert "SPEC-P1" in o.gate.pending, "spec chưa ký"


# ---------- N1.b: phát hiện review ----------

def _mark_n(o, bus, n: int = 1) -> None:
    """n event đi qua `scheduler._mark` thật (điểm gọi duy nhất của sync_quality)."""
    from company.orchestrator import StepResult
    for _ in range(n):
        env = _task(bus)
        o._mark(env, StepResult(env.event_id, env.topic, env.key))


def _escalations(o, target: str) -> list:
    return [a for a in o.supervisor.actions if a.target == target and a.action == "escalate"]


@pytest.mark.parametrize("plan,msg", [
    ({"project_id": "P1", "source_topic": "approved-specs", "tickets": [T1]}, "plan_id"),
    ({**PLAN, "tickets": [{"title": "không có mã"}]}, "ticket_id"),
])
def test_ke_hoach_thieu_khoa_khong_lam_vo_mark(tmp_path, plan, msg):
    bus, o = _unit(tmp_path)
    _pin(o, tmp_path / "c.sqlite"); o.plans["PLAN-P1-1"] = plan
    _mark_n(o, bus)
    [err] = _acts(bus, "quality.sync_error")
    assert err["error"].startswith("ExecutionJournalError") and msg in err["error"]
    assert len(_escalations(o, RUN)) == 1


def test_spec_bien_mat_sau_register_la_sync_error_khong_phai_assert(tmp_path, monkeypatch):
    bus, o = _unit(tmp_path)
    _pin(o, tmp_path / "c.sqlite"); o.plans["PLAN-P1-1"] = PLAN
    monkeypatch.setattr(ExecutionJournal, "load_spec", lambda self, run_id: None)
    _mark_n(o, bus)
    [err] = _acts(bus, "quality.sync_error")
    assert err["error"] == f"ExecutionJournalError: run {RUN} chưa đăng ký ngay sau register"


def test_sync_error_escalate_theo_thong_diep_khong_theo_lop(tmp_path, monkeypatch):
    from xagents_core.execution import ExecutionJournalError
    bus, o = _unit(tmp_path)
    _pin(o, tmp_path / "c.sqlite")
    msgs = iter(["lỗi A", "lỗi A", "lỗi B"])

    def boom(o, pid):
        raise ExecutionJournalError(next(msgs))

    monkeypatch.setattr(quality_flow, "_sync_project", boom)
    for _ in range(3): quality_flow.sync_quality(o)
    assert [e["error"] for e in _acts(bus, "quality.sync_error")] == ["ExecutionJournalError: lỗi A",
                                                                     "ExecutionJournalError: lỗi B"]
    assert len(_escalations(o, RUN)) == 2, "lỗi khác trên cùng run escalate lại; lỗi y hệt không spam"


def test_sync_error_khong_co_run_id_thi_chi_audit_khong_pause_du_an(tmp_path, monkeypatch):
    from xagents_core.execution import ExecutionJournalError
    bus, o = _unit(tmp_path)
    quality_flow.note_profile(o, {"project_id": "P1", "run_id": ""})

    def boom(o, pid):
        raise ExecutionJournalError("hỏng")

    monkeypatch.setattr(quality_flow, "_sync_project", boom)
    quality_flow.sync_quality(o); quality_flow.sync_quality(o)
    [err] = _acts(bus, "quality.sync_error")
    assert err["run_id"] == "" and err["project_id"] == "P1"
    assert "P1" not in o.paused and not _escalations(o, "P1") and not _escalations(o, "")


def test_commit_bi_tu_choi_thi_driver_khong_chay_lai_cung_attempt(tmp_path):
    signers = _signers()
    driver = FakeDriver(signers)
    bus, o = _start(tmp_path, driver)  # không registry ⇒ submit bị từ chối, escalate
    _sign_spec_with_profile(tmp_path, bus, o)
    assert len(driver.calls) == 1
    assert "registry" in _acts(bus, "quality.sync_error")[0]["error"] and RUN in o.paused
    _mark_n(o, bus, 3)
    assert len(driver.calls) == 1, "cùng attempt, escalation chưa xử lý ⇒ không chạy lại driver"
    # người xử lý escalation (có registry rồi duyệt gate escalation) ⇒ chạy lại đúng một lần và nghiệm thu
    o.quality_trust = write_trust(tmp_path / "trust.json", signers)
    o.tick()
    assert RUN in o.gate.pending
    o.gate.decide(RUN, "approve", by="human:rm", reason="đã cấp registry khoá công khai cho quality")
    o.run()
    assert RUN not in o.paused and len(driver.calls) == 2
    with _journal(tmp_path) as j:
        assert j.resume(RUN).status is RunStatus.SUCCEEDED


@pytest.mark.parametrize("drop", [frozenset(), frozenset({"goal.traceability"})])
def test_run_da_ket_thuc_o_candidate_hien_tai_khong_mo_journal_nua(tmp_path, monkeypatch, drop):
    signers = _signers()
    driver = FakeDriver(signers, drop=drop)
    bus, o = _start(tmp_path, driver, trust=write_trust(tmp_path / "trust.json", signers))
    _sign_spec_with_profile(tmp_path, bus, o)
    opened = [0]
    orig = ExecutionJournal.__init__

    def counting(self, *a, **k):
        opened[0] += 1
        orig(self, *a, **k)

    monkeypatch.setattr(ExecutionJournal, "__init__", counting)
    _mark_n(o, bus, 3)
    assert opened[0] == 0
    o._quality_done.clear()  # như restart: mất cache ⇒ đối chiếu lại một lần, không chấm lại cùng candidate
    _mark_n(o, bus, 2)
    assert opened[0] > 0 and len(driver.calls) == 1
    opened[0] = 0
    _mark_n(o, bus)
    assert opened[0] == 0, "đối chiếu lại xong thì cache lại"


def test_thanh_phan_duong_dan_duoc_kiem_va_tach_namespace(tmp_path):
    from company.quality_execution import _safe_component, pinned_profile_path
    db = tmp_path / "c.sqlite"
    _bus, o = _unit(tmp_path)
    for bad in ("../x", "..", ".", "a/b", "a\\b", "", "-x", "x" * 129):
        with pytest.raises(ValueError):
            _safe_component(bad)
        with pytest.raises(ValueError):
            pinned_profile_path(db, bad, "a" * 64)
        with pytest.raises(ValueError):
            quality_flow.evidence_root(o, bad)
    assert _safe_component("run-P1.v2_x") == "run-P1.v2_x"
    art = db.with_suffix(".artifacts") / "quality"
    assert pinned_profile_path(db, "P1", "a" * 64) == art / "profiles" / "P1" / f"{'a' * 64}.json"
    assert quality_flow.evidence_root(o, "P1") == art / "runs" / "P1", "pid == run_id không va chạm"
    assert gate_main(["--db", str(db), "approve", "SPEC-../x", "--by", "human:po",
                      "--quality-profile", str(tmp_path / "p.json")]) == 2
    assert not (tmp_path / "x").exists() and not art.exists()


def test_require_profile_for_spec_dung_chung(tmp_path):
    from company.gate_cli import require_profile_for_spec
    bus, o = _start(tmp_path, None)
    _drive_to_spec_gate(bus, o)
    assert require_profile_for_spec(bus, "SPEC-P1", "approve", has_profile_arg=False) is None, "chưa từng có profile"
    pf = tmp_path / "profile.json"
    pf.write_text(v4_profile().model_dump_json(), encoding="utf-8")
    assert gate_main(["--db", str(tmp_path / "c.sqlite"), "approve", "SPEC-P1", "--by", "human:po",
                      "--quality-profile", str(pf)]) == 0
    why = require_profile_for_spec(bus, "SPEC-P1", "approve", has_profile_arg=False)
    assert why is not None and "gate_cli approve SPEC-P1 --quality-profile" in why
    assert require_profile_for_spec(bus, "SPEC-P1", "approve", has_profile_arg=True) is None
    assert require_profile_for_spec(bus, "SPEC-P1", "reject", has_profile_arg=False) is None
    assert require_profile_for_spec(bus, "REL-001", "approve", has_profile_arg=False) is None


def test_cli_commit_profile_co_delivery_tu_choi_khong_ghi_failed(tmp_path, capsys):
    from company.quality_execution import main
    from test_delivery_contract import delivery_data
    _to_running(tmp_path)
    prof = tmp_path / "delivery.json"
    prof.write_text(json.dumps({**json.loads(v4_profile().model_dump_json()), "delivery": delivery_data()}),
                    encoding="utf-8")
    with _journal(tmp_path) as j:
        before = j.events(RUN)
    for name in ("result", "receipts", "trust"):
        (tmp_path / f"{name}.json").write_text("[]", encoding="utf-8")
    capsys.readouterr()
    assert main(["commit", RUN, "--journal", str(tmp_path / "c.quality.sqlite"), "--profile", str(prof),
                 "--result", str(tmp_path / "result.json"), "--receipts", str(tmp_path / "receipts.json"),
                 "--trust", str(tmp_path / "trust.json"), "--evidence-root", str(tmp_path / "ev")]) == 2
    assert "commit CLI không có ApprovalLookup; để driver của orchestrator nộp" in capsys.readouterr().err
    with _journal(tmp_path) as j:
        assert j.events(RUN) == before and j.resume(RUN).tasks[QUALITY_TASK_ID] is TaskStatus.RUNNING
