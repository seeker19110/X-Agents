"""`BusApprovalLookup` — ApprovalLookup thật cho pha Ready (ADR gốc 0021 §d, bổ sung pe2-duyet).

Người duyệt spec lấy từ bus (`gate.decide` approve `SPEC-<pid>` do chính actor người ghi), ràng vào hash spec qua
profile mà CÙNG người đó ghim lúc ký. Lời khai `approved_by` trong profile không bao giờ là nguồn sự thật.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from xagents_core.execution import RunStatus

from company.gate_cli import PersistentGate, _pin_profile
from company.orch import quality_flow
from company.product_quality import Evidence, ProjectProfile, sign_evidence
from company.quality_execution import QUALITY_TASK_ID
from company.quality_floor import PROFILE_ACTION
from company.spec_approval import BusApprovalLookup
from company.sqlite_bus import SQLiteBus
from test_delivery_contract import delivery_data, report
from test_product_quality import profile_data
from test_quality_flow import FakeDriver, _journal, _sign_spec_with_profile, _signers, _start, write_trust
from test_receipt_signature import ED25519_POLICY, key_id_of

SPEC_SHA = "a" * 64


def _profile(pid: str = "P1", **spec) -> ProjectProfile:
    delivery = delivery_data()
    delivery["spec"] = {
        **delivery["spec"],
        "approval_record": f"SPEC-{pid}",
        "artifact_sha256": SPEC_SHA,
        "approved_by": "human:po",
        **spec,
    }
    return ProjectProfile.model_validate_json(
        json.dumps(profile_data(project_id=pid, run_id=f"run-{pid}", evidence_policy=ED25519_POLICY, delivery=delivery))
    )


def _sign(
    tmp_path: Path,
    bus,
    *,
    decider: str = "human:po",
    pinner: str = "human:po",
    decision: str = "approve",
    decide_actor: str | None = None,
    pin_actor: str | None = None,
    profile: ProjectProfile | None = None,
    pid: str = "P1",
) -> dict:
    db = tmp_path / "c.sqlite"
    gate = PersistentGate(bus)
    gate._log(
        decide_actor or decider,
        "gate.decide",
        {"subject_id": f"SPEC-{pid}", "decision": decision, "by": decider, "reason": ""},
        by=decider,
    )
    src = tmp_path / f"profile-{pid}.json"
    src.write_text((profile or _profile(pid)).model_dump_json(), encoding="utf-8")
    pin = _pin_profile(db, f"SPEC-{pid}", src, pinner)
    gate._log(pinner, PROFILE_ACTION, pin, by=pinner)
    return pin


@pytest.fixture
def env(tmp_path):
    db = tmp_path / "c.sqlite"
    return SQLiteBus(db), db


def test_nguoi_ky_spec_kem_profile_thi_lookup_tra_dung_nguoi(tmp_path, env):
    bus, db = env
    _sign(tmp_path, bus)
    assert BusApprovalLookup(bus, db).approved("SPEC-P1", SPEC_SHA) == "human:po"


def test_hash_spec_khac_ban_nguoi_ky_thi_khong_xac_minh(tmp_path, env):
    bus, db = env
    _sign(tmp_path, bus)
    assert BusApprovalLookup(bus, db).approved("SPEC-P1", "b" * 64) is None


@pytest.mark.parametrize("record", ["fixture:decision-1", "SPEC-P2", "SPEC-", ""])
def test_record_khong_phai_gate_spec_da_ky_thi_khong_xac_minh(tmp_path, env, record):
    bus, db = env
    _sign(tmp_path, bus)
    assert BusApprovalLookup(bus, db).approved(record, SPEC_SHA) is None


def test_gate_bi_tu_choi_thi_khong_xac_minh(tmp_path, env):
    bus, db = env
    _sign(tmp_path, bus, decision="reject")
    assert BusApprovalLookup(bus, db).approved("SPEC-P1", SPEC_SHA) is None


def test_agent_gia_quyet_dinh_gate_duoi_ten_nguoi_thi_khong_xac_minh(tmp_path, env):
    bus, db = env
    _sign(tmp_path, bus, decide_actor="orchestrator")
    assert BusApprovalLookup(bus, db).approved("SPEC-P1", SPEC_SHA) is None


class _ReplayOnly:
    """Bus đã bị ghi thẳng vào SQLite (lách ACL của `publish`): lookup vẫn phải tự kiểm actor người."""

    def __init__(self, events):
        self.events = list(events)

    def replay(self, topic=None):
        return [e for e in self.events if topic is None or e.topic == topic]


def test_ghim_profile_boi_actor_khong_phai_nguoi_lot_vao_bus_thi_khong_xac_minh(tmp_path, env):
    bus, db = env
    pin = _sign(tmp_path, bus)
    gate = PersistentGate(bus)
    events = [e for e in bus.replay(topic="audit-log") if e.payload.get("action") != PROFILE_ACTION]
    forged = gate._envelope("orchestrator", PROFILE_ACTION, pin, by="human:po")
    assert BusApprovalLookup(_ReplayOnly([*events, forged]), db).approved("SPEC-P1", SPEC_SHA) is None
    real = [e for e in bus.replay(topic="audit-log")]
    assert BusApprovalLookup(_ReplayOnly(real), db).approved("SPEC-P1", SPEC_SHA) == "human:po"


def test_nguoi_duyet_gate_khac_nguoi_ghim_profile_thi_khong_xac_minh(tmp_path, env):
    bus, db = env
    _sign(tmp_path, bus, decider="human:a", pinner="human:b")
    assert BusApprovalLookup(bus, db).approved("SPEC-P1", SPEC_SHA) is None


def test_file_profile_bi_sua_sau_khi_ghim_thi_khong_xac_minh(tmp_path, env):
    bus, db = env
    from company.quality_execution import pinned_profile_path

    pin = _sign(tmp_path, bus)
    path = pinned_profile_path(db, "P1", pin["profile_sha256"])
    path.write_bytes(path.read_bytes().replace(SPEC_SHA.encode(), b"b" * 64))
    assert BusApprovalLookup(bus, db).approved("SPEC-P1", "b" * 64) is None
    assert BusApprovalLookup(bus, db).approved("SPEC-P1", SPEC_SHA) is None


def test_file_profile_mat_thi_khong_xac_minh_khong_nem_loi(tmp_path, env):
    bus, db = env
    from company.quality_execution import pinned_profile_path

    pin = _sign(tmp_path, bus)
    pinned_profile_path(db, "P1", pin["profile_sha256"]).unlink()
    assert BusApprovalLookup(bus, db).approved("SPEC-P1", SPEC_SHA) is None


def test_profile_khong_co_delivery_thi_khong_xac_minh(tmp_path, env):
    bus, db = env
    plain = ProjectProfile.model_validate_json(
        json.dumps(profile_data(project_id="P1", run_id="run-P1", evidence_policy=ED25519_POLICY))
    )
    _sign(tmp_path, bus, profile=plain)
    assert BusApprovalLookup(bus, db).approved("SPEC-P1", SPEC_SHA) is None


def test_profile_ghi_record_khac_gate_da_ky_thi_khong_xac_minh(tmp_path, env):
    bus, db = env
    _sign(tmp_path, bus, profile=_profile(approval_record="SPEC-P9"))
    assert BusApprovalLookup(bus, db).approved("SPEC-P9", SPEC_SHA) is None
    assert BusApprovalLookup(bus, db).approved("SPEC-P1", SPEC_SHA) is None


def test_bang_chung_audit_hong_bi_bo_qua(tmp_path, env):
    bus, db = env
    _sign(tmp_path, bus)
    gate = PersistentGate(bus)
    gate.bus.publish(
        gate._envelope("human:po", PROFILE_ACTION, {}, by="human:po").model_copy(
            update={"payload": {"action": PROFILE_ACTION, "actor": "human:po", "evidence": "{không phải json"}}
        )
    )
    gate._log("human:po", PROFILE_ACTION, {"project_id": "P1", "profile_sha256": "không-phải-hex"}, by="human:po")
    gate._log("human:po", PROFILE_ACTION, {"project_id": "P1", "profile_sha256": 7}, by="human:po")
    assert BusApprovalLookup(bus, db).approved("SPEC-P1", SPEC_SHA) == "human:po"


def test_lan_ky_lai_moi_nhat_thay_the_lan_ky_cu(tmp_path, env):
    """Hai thế hệ gate SPEC (CR): chỉ lần duyệt mới nhất còn hiệu lực; hash cũ hết được xác minh (sc-security F2)."""
    bus, db = env
    _sign(tmp_path, bus)
    newer = "c" * 64
    _sign(
        tmp_path,
        bus,
        decider="human:bob",
        pinner="human:bob",
        profile=_profile(artifact_sha256=newer, approved_by="human:bob"),
    )
    lookup = BusApprovalLookup(bus, db)
    assert lookup.approved("SPEC-P1", SPEC_SHA) is None
    assert lookup.approved("SPEC-P1", newer) == "human:bob"


def test_duyet_roi_bi_tu_choi_thi_lan_duyet_cu_het_hieu_luc(tmp_path, env):
    bus, db = env
    _sign(tmp_path, bus)
    PersistentGate(bus)._log(
        "human:qa",
        "gate.decide",
        {"subject_id": "SPEC-P1", "decision": "reject", "by": "human:qa", "reason": ""},
        by="human:qa",
    )
    assert BusApprovalLookup(bus, db).approved("SPEC-P1", SPEC_SHA) is None


def test_gate_spec_mo_lai_thi_lan_duyet_cu_het_hieu_luc(tmp_path, env):
    bus, db = env
    _sign(tmp_path, bus)
    PersistentGate(bus)._log(
        "human:po", "gate.request", {"kind": "spec", "subject_id": "SPEC-P1", "checklist": [], "created_by": "human:po"}
    )
    assert BusApprovalLookup(bus, db).approved("SPEC-P1", SPEC_SHA) is None


def test_ghim_profile_truoc_lan_duyet_khong_tinh(tmp_path, env):
    """Profile ghim trước khi gate được duyệt không thuộc lần duyệt đó."""
    bus, db = env
    gate = PersistentGate(bus)
    src = tmp_path / "profile.json"
    src.write_text(_profile().model_dump_json(), encoding="utf-8")
    gate._log("human:po", PROFILE_ACTION, _pin_profile(db, "SPEC-P1", src, "human:po"), by="human:po")
    gate._log(
        "human:po",
        "gate.decide",
        {"subject_id": "SPEC-P1", "decision": "approve", "by": "human:po", "reason": ""},
        by="human:po",
    )
    assert BusApprovalLookup(bus, db).approved("SPEC-P1", SPEC_SHA) is None


def test_evidence_long_qua_sau_bi_bo_qua_khong_vo(tmp_path, env):
    bus, db = env
    forged = PersistentGate(bus)._envelope("human:po", PROFILE_ACTION, {}, by="human:po")
    forged = forged.model_copy(update={"payload": {**forged.payload, "evidence": "[" * 100000 + "]" * 100000}})
    _sign(tmp_path, bus)
    events = [*bus.replay(topic="audit-log"), forged]
    assert BusApprovalLookup(_ReplayOnly(events), db).approved("SPEC-P1", SPEC_SHA) == "human:po"


def _pin_only(tmp_path: Path, bus, db: Path, decision_data: dict) -> None:
    gate = PersistentGate(bus)
    gate._log("human:po", "gate.decide", decision_data, by=decision_data["by"])
    src = tmp_path / "profile.json"
    src.write_text(_profile().model_dump_json(), encoding="utf-8")
    gate._log("human:po", PROFILE_ACTION, _pin_profile(db, "SPEC-P1", src, "human:po"), by="human:po")


def test_quyet_dinh_co_by_lech_actor_bi_bo_qua(tmp_path, env):
    """`trusted_decision` là bộ đọc chung: actor người ký dưới tên người khác không là quyết định đáng tin."""
    bus, db = env
    _pin_only(tmp_path, bus, db, {"subject_id": "SPEC-P1", "decision": "approve", "by": "human:khac", "reason": ""})
    assert BusApprovalLookup(bus, db).approved("SPEC-P1", SPEC_SHA) is None


def test_nguoi_duyet_spec_du_an_khac_khong_tinh_cho_du_an_nay(tmp_path, env):
    bus, db = env
    _pin_only(tmp_path, bus, db, {"subject_id": "SPEC-P2", "decision": "approve", "by": "human:po", "reason": ""})
    assert BusApprovalLookup(bus, db).approved("SPEC-P1", SPEC_SHA) is None


# ---------- e2e: orchestrator tự cấp lookup từ chính bus của nó ----------

SPEC_TEXT = b"Synthetic fixture spec; not a real approval.\n"


def _delivery_profile(**spec):
    return _profile(
        artifact_ref="spec.md",
        artifact_sha256=hashlib.sha256(SPEC_TEXT).hexdigest(),
        approved_at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        **spec,
    )


class DeliveryDriver(FakeDriver):
    """Driver giả có thêm spec artifact và báo cáo Done/Complete cho `delivery.definition`."""

    def run(self, run_id, checks):
        assert self.o is not None
        root = quality_flow.evidence_root(self.o, run_id)
        root.mkdir(parents=True, exist_ok=True)
        (root / "spec.md").write_bytes(SPEC_TEXT)
        result, receipts = super().run(run_id, checks)
        out = []
        for r in receipts:
            if r.evidence.check_id == "delivery.definition":
                ev = Evidence.model_validate({**r.evidence.model_dump(), "delivery_report": report()})
                r = sign_evidence(ev, self.signers["ci"], key_id_of(self.signers["ci"]))
            out.append(r)
        return result, out


def _run_delivery(tmp_path, profile):
    signers = _signers()
    bus, o = _start(tmp_path, DeliveryDriver(signers), trust=write_trust(tmp_path / "trust.json", signers))
    _sign_spec_with_profile(tmp_path, bus, o, profile)
    with _journal(tmp_path) as j:
        return j.resume(profile.run_id)


def test_e2e_spec_nguoi_ky_that_thi_ready_qua_ma_khong_can_cap_lookup_tay(tmp_path):
    state = _run_delivery(tmp_path, _delivery_profile())
    assert state.status is RunStatus.SUCCEEDED, (state.status, state.failures)


def test_e2e_profile_khai_nguoi_duyet_khac_nguoi_ky_gate_thi_failed(tmp_path):
    state = _run_delivery(tmp_path, _delivery_profile(approved_by="human:giam-doc"))
    assert state.status is not RunStatus.SUCCEEDED
    assert "approval_record_unverified" in state.failures.get(QUALITY_TASK_ID, ""), state.failures


# ---------- CLI: registry do người trực cấp, lookup từ bus ----------


def test_cli_orchestrator_nhan_quality_trust_va_cap_lookup_tu_bus(tmp_path, monkeypatch):
    from company.orch import cli, cli_cmds

    seen = {}
    monkeypatch.setitem(cli_cmds.ORCH_CMDS, "status", lambda o, ns: seen.setdefault("o", o) and 0)
    trust = tmp_path / "trust.json"
    trust.write_text("{}", encoding="utf-8")
    SQLiteBus(tmp_path / "c.sqlite").close()
    assert cli.main(["--db", str(tmp_path / "c.sqlite"), "--quality-trust", str(trust), "status"]) == 0
    assert seen["o"].quality_trust == trust
    seen.clear()
    assert cli.main(["--db", str(tmp_path / "c.sqlite"), "status"]) == 0
    assert seen["o"].quality_trust is None, "không cờ ⇒ như cũ: không registry, không nghiệm thu được"


def _commit_argv(tmp_path, o, signers, profile) -> list[str]:
    from company.product_quality import required_checks
    from company.quality_execution import _result_document

    result, receipts = DeliveryDriver(signers, o=o).run(
        profile.run_id, tuple(sorted(c.id for c in required_checks(profile)))
    )
    (tmp_path / "result.json").write_text(json.dumps(_result_document(result)), encoding="utf-8")
    (tmp_path / "receipts.json").write_text(json.dumps([r.model_dump(mode="json") for r in receipts]), encoding="utf-8")
    (tmp_path / "pinned.json").write_text(profile.model_dump_json(), encoding="utf-8")
    return [
        "commit",
        profile.run_id,
        "--journal",
        str(tmp_path / "c.quality.sqlite"),
        "--profile",
        str(tmp_path / "pinned.json"),
        "--result",
        str(tmp_path / "result.json"),
        "--receipts",
        str(tmp_path / "receipts.json"),
        "--trust",
        str(write_trust(tmp_path / "trust.json", signers)),
        "--evidence-root",
        str(quality_flow.evidence_root(o, profile.run_id)),
    ]


def test_cli_commit_co_db_thi_cham_duoc_profile_co_delivery(tmp_path, capsys):
    from company.quality_execution import main

    profile = _delivery_profile()
    bus, o = _start(tmp_path, None)
    _sign_spec_with_profile(tmp_path, bus, o, profile)
    argv = _commit_argv(tmp_path, o, _signers(), profile)
    capsys.readouterr()
    assert main(argv) == 2, "không --db ⇒ vẫn từ chối, không đốt attempt"
    assert "ApprovalLookup" in capsys.readouterr().err
    assert main([*argv, "--db", str(tmp_path / "c.sqlite")]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "succeeded"


def test_cli_commit_db_khong_ton_tai_thi_tu_choi_khong_tao_file(tmp_path, capsys):
    from company.quality_execution import main

    profile = _delivery_profile()
    bus, o = _start(tmp_path, None)
    _sign_spec_with_profile(tmp_path, bus, o, profile)
    argv = _commit_argv(tmp_path, o, _signers(), profile)
    missing = tmp_path / "khong-co.sqlite"
    assert main([*argv, "--db", str(missing)]) == 2
    assert not missing.exists()


def test_cli_commit_db_khong_phai_bus_cua_journal_thi_tu_choi_khong_dong_vao(tmp_path, capsys):
    """`--db` phải là bus mà `--journal` nằm cạnh (sc-security F3): bus khác không được làm nguồn người duyệt."""
    from company.quality_execution import main

    profile = _delivery_profile()
    bus, o = _start(tmp_path, None)
    _sign_spec_with_profile(tmp_path, bus, o, profile)
    argv = _commit_argv(tmp_path, o, _signers(), profile)
    other = tmp_path / "khac.sqlite"
    other.write_bytes(b"")
    assert main([*argv, "--db", str(other)]) == 2
    assert other.read_bytes() == b"", "không mở bus lạ, không tạo bảng"
