"""collect(): hợp đồng API.md trên DB thật (event publish qua bus của software-company)."""

from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from company import gate_reviewer as reviewer
from company.events import AuditLog as CompanyAudit
from company.events import Envelope as CompanyEnvelope
from company.events import PullRequest, Task
from company.gate_cli import PersistentGate as CompanyPersistentGate
from company.gates import GateRequest as CompanyGateRequest
from company.gates import HumanGate as CompanyHumanGate
from company.sqlite_bus import SQLiteBus as CompanySQLiteBus
from xagents_core.execution import ExecutionEvent, ExecutionEventKind, ExecutionJournal, RunSpec, TaskSpec
from xagents_core.llm import MAY_CONFIG_ENV

import console.collect as collect_mod
from conftest import _produced, gate_decide
from console.collect import COMPANY, collect

DEAD_GATEWAY = "http://127.0.0.1:9"  # cổng 9 (discard) không có ai nghe → luôn từ chối ngay


def state(company_db: Path | None) -> dict:
    return collect(company_db, gateway_url=DEAD_GATEWAY)


def _build_quality_journal(path: Path, run_id: str = "RUN-OK") -> None:
    """Journal `quality:accept` succeeded tối thiểu — ghi bằng chính `ExecutionJournal` như coordinator thật."""
    spec = RunSpec(run_id, "mục tiêu", (
        TaskSpec(task_id="T1", objective="làm T1"),
        TaskSpec(task_id="quality:accept", objective="nghiệm thu", dependencies=("T1",), acceptance=("tests",)),
    ))
    with ExecutionJournal(path) as journal:
        journal.register(spec)
        for kind, task_id in ((ExecutionEventKind.RUN_STARTED, None), (ExecutionEventKind.TASK_STARTED, "T1"),
                              (ExecutionEventKind.TASK_SUCCEEDED, "T1"),
                              (ExecutionEventKind.TASK_STARTED, "quality:accept"),
                              (ExecutionEventKind.TASK_SUCCEEDED, "quality:accept")):
            n = len(journal.events(run_id))
            journal.transition(ExecutionEvent(run_id, kind, task_id, payload={"result": {"findings": []}},
                                              event_id=f"{run_id}:{task_id}:{kind.value}:{n}"), expected_count=n)


def test_xuong_co_du_lieu(company_db: Path) -> None:
    s = state(company_db)
    assert s["sources"][COMPANY]["ok"]
    assert s["sources"][COMPANY]["events"] == 8
    assert s["tiles"]["events"] == 8
    assert [t["id"] for t in s["tickets"]] == ["TCK-112"]
    assert s["tickets"][0]["bud"] == 120_000 and s["tickets"][0]["used"] == 8_420
    assert s["prs"] == [
        {"id": "TCK-112", "br": "ticket/TCK-112", "s": "thêm login", "lint": "pass", "tests": "pass", "v": "workspace"}
    ]
    assert s["reviews"][0]["v"] == "block" and "thiếu authz" in s["reviews"][0]["f"]
    assert dict(s["agents"])["builder"] == 0.21
    assert {g["xuong"] for g in s["gates"]} == {COMPANY}
    assert [r["ac"] for r in s["log"]]  # audit `produced:*`, mới nhất trước
    assert len(s["cost_days"]["days"]) == len(s["cost_days"]["series"]) == 14
    assert s["cost_days"]["series"][-1][0] == 0.21  # backend = tier strong, hôm nay


def test_moi_khoa_luon_co_mat_va_khong_nem_khi_thieu_db(tmp_path: Path) -> None:
    s = state(tmp_path / "khong-co.sqlite")
    assert s["sources"][COMPANY] == {
        "ok": False,
        "db": None,
        "events": 0,
        "error": "chưa có file DB",
        "sandbox_available": s["sources"][COMPANY]["sandbox_available"],
    }
    # K2.7: cờ là của MÁY, không của xưởng — có mặt kể cả khi nguồn hỏng (ô cảnh báo cần biết "máy có docker
    # không" trước cả khi biết "công ty chạy gì"), và luôn là bool chứ không phải None.
    assert isinstance(s["sources"][COMPANY]["sandbox_available"], bool)
    assert s["tickets"] == [] and s["prs"] == [] and s["reviews"] == []
    assert s["gates"] == []
    assert s["tiles"]["events"] == 0
    for key in (
        "generated_at",
        "sources",
        "tiles",
        "gates",
        "tickets",
        "prs",
        "reviews",
        "cost_days",
        "agents",
        "backends",
        "supervisor",
        "log",
        "loops",
    ):
        assert key in s


def test_db_hong_bao_loi_chu_khong_nem(tmp_path: Path) -> None:
    bad = tmp_path / "hong.sqlite"
    bad.write_bytes(b"day khong phai sqlite")
    s = state(bad)
    assert s["sources"][COMPANY]["ok"] is False
    assert "không đọc được DB" in s["sources"][COMPANY]["error"]
    assert s["tickets"] == []


def test_khong_co_db_nao(tmp_path: Path) -> None:
    s = state(None)
    assert s["sources"][COMPANY]["error"] == "chưa cấu hình đường dẫn DB"
    assert s["tiles"]["events"] == 0 and s["gates"] == []


def test_tuoi_gate_va_nguong_sev_theo_hang_so_cua_cong_ty(company_db: Path) -> None:
    g = CompanyHumanGate()
    over_h = g.timeout.total_seconds() / 3600
    warn_h = g.remind_at.total_seconds() / 3600
    by_id = {x["id"]: x for x in state(company_db)["gates"]}
    assert by_id["REL-001"]["hours"] == 30 and by_id["REL-001"]["sev"] == "over"
    assert by_id["REL-001"]["hours"] >= over_h > warn_h
    assert math.floor(over_h) == 24 and math.floor(warn_h) == 12  # khớp GATE_TIMEOUT/REMIND của repo


def test_gate_da_quyet_khong_con_trong_danh_sach(company_db: Path) -> None:
    s = state(company_db)
    assert "SPEC-1" not in {g["id"] for g in s["gates"]}  # đã có gate.decide trong log
    assert {"REL-001"} == {g["id"] for g in s["gates"]}
    bus = CompanySQLiteBus(company_db)
    gate_decide(bus, CompanyEnvelope, CompanyAudit, subject_id="REL-001", decision="request_changes", by="human:owner")
    bus.close()
    assert "REL-001" not in {g["id"] for g in state(company_db)["gates"]}


def test_gate_reviewer_da_ky_khi_co_tat_duoc_hien_la_chua_ap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "company.sqlite"
    registry = tmp_path / "reviewers.json"
    monkeypatch.setenv(reviewer.FLAG_ENV, "1")
    monkeypatch.setenv(reviewer.REGISTRY_ENV, str(registry))
    key = reviewer.new_key("reviewer:doc-lap", registry, tmp_path / "keys")
    bus = CompanySQLiteBus(db)
    gate = CompanyPersistentGate(bus)
    gate.request(CompanyGateRequest(kind="escalation", subject_id="T1", created_by="supervisor",
                                   checklist=["root_cause", "decision:reopen|close", "hint"]))
    reason = "root_cause: lỗi; decision: reopen; hint: làm tiếp"
    signed = reviewer.sign_decision("T1", "approve", "reviewer:doc-lap", reason,
                                    reviewer.generation_of(gate.pending["T1"]), "0" * 64,
                                    reviewer.load_private_key(key))
    payload = {"subject_id": "T1", "decision": "approve", "by": "reviewer:doc-lap", "reason": reason, **signed}
    bus.publish(CompanyEnvelope(topic="audit-log", key="reviewer:doc-lap", actor="reviewer:doc-lap",
                                payload=CompanyAudit(actor="reviewer:doc-lap", action="gate.decide",
                                                     evidence=json.dumps(payload)).model_dump()))
    bus.close()
    monkeypatch.delenv(reviewer.FLAG_ENV)
    row = next(g for g in state(db)["gates"] if g["id"] == "T1")
    assert row["reviewer_signed"] == {"decision": "approve", "by": "reviewer:doc-lap"}
    assert row["sev"] == "signed" and row["decidable"] is False


@pytest.fixture()
def khong_co_llm_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    """Máy chạy test có thể có sẵn `llm.yaml` của công ty; khi đó collect() lấy backend từ đó và không bao giờ
    hỏi gateway. Ép nhánh gateway để test đúng thứ nó định test."""
    monkeypatch.setattr(collect_mod, "_routing_status", lambda: None)


def test_gateway_chet_khong_lam_hong_trang(company_db: Path, khong_co_llm_yaml: None) -> None:
    start = datetime.now(UTC)
    s = collect(company_db, gateway_url=DEAD_GATEWAY)
    assert s["backends"] == []
    assert s["sources"]["gateway"]["ok"] is False
    assert "gateway" in s["sources"]["gateway"]["error"]
    assert (datetime.now(UTC) - start).total_seconds() < 5  # timeout ngắn, không treo trang
    assert s["tickets"]  # phần còn lại vẫn đầy đủ


def test_doc_khong_ghi_vao_db(company_db: Path) -> None:
    before = company_db.read_bytes()
    state(company_db)
    assert company_db.read_bytes() == before


@pytest.mark.parametrize("token", [None])
def test_token_gateway_khong_bat_buoc(company_db: Path, token: Path | None, khong_co_llm_yaml: None) -> None:
    s = collect(company_db, gateway_token_file=token, gateway_url=DEAD_GATEWAY)
    assert s["backends"] == []


# ---------- các nhánh nhỏ khó chạm tới qua collect() nguyên khối: test trực tiếp hàm/lớp nội bộ ----------


def test_envelope_hong_bao_loi_ro_thay_vi_nem_nua_voi(tmp_path: Path) -> None:
    """Một hàng trong `events` mà body không parse được thành envelope model -> _SourceError rõ ràng."""
    db = tmp_path / "hong-envelope.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE events (seq INTEGER PRIMARY KEY, body TEXT)")
    con.execute("INSERT INTO events (body) VALUES (?)", ("khong-phai-json-envelope-hop-le",))
    con.commit()
    con.close()
    s = collect(db, gateway_url=DEAD_GATEWAY)
    assert s["sources"][COMPANY]["ok"] is False
    assert "log hỏng" in s["sources"][COMPANY]["error"]


def test_evidence_don_bien_dang_loi() -> None:
    assert collect_mod._evidence({"evidence": "khong-phai-json"}) == {}
    assert collect_mod._evidence({"evidence": json.dumps([1, 2])}) == {}
    assert collect_mod._evidence({"evidence": None}) == {}
    assert collect_mod._evidence({"evidence": json.dumps({"event_id": "e1"})}) == {"event_id": "e1"}


def test_view_read_replay_khong_override_nem_notimplemented() -> None:
    with pytest.raises(NotImplementedError):
        collect_mod._View("x", None)

    class _ChiCoRead(collect_mod._View):
        def _read(self):
            return []

    with pytest.raises(NotImplementedError):
        _ChiCoRead("x", None)


def test_view_mac_dinh_gate_title_facts_review_note_tiers() -> None:
    """`_View` cơ sở (không override) dùng cho các test kiểm nhánh mặc định không lớp con nào chạm tới."""
    v = object.__new__(collect_mod._View)
    v.name = "x"
    v.envelopes = []
    assert v.tiers() == {}
    assert v.review_note("S1", "src") == ""

    r = SimpleNamespace(kind="plan", subject_id="S1", created_by="u")
    assert v.gate_title(r) == "plan · S1"
    assert v.gate_facts(r) == [["kind", "plan"], ["subject_id", "S1"], ["created_by", "u"]]


def test_review_note_noi_finding_khi_khong_co_root_cause() -> None:
    v = object.__new__(collect_mod._View)
    v.envelopes = [
        SimpleNamespace(
            topic="review-results",
            payload={
                "ticket_id": "T1",
                "source": "revr",
                "verdict": "block",
                "findings": [{"text": "a"}, {"text": "b"}],
            },
        ),
    ]
    assert v._review_note("ticket_id", "T1", "revr") == "block · a; b"
    # không khớp nguồn/subject -> rỗng
    assert v._review_note("ticket_id", "T1", "khac") == ""


def test_company_tiers_loi_load_agents_tra_rong(company_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collect_mod, "load_company_agents", lambda **k: (_ for _ in ()).throw(RuntimeError("hong")))
    s = collect(company_db, gateway_url=DEAD_GATEWAY)
    # tiers() rỗng -> cost_days vẫn chạy được (dùng tier mặc định "standard"), không nổ.
    assert len(s["cost_days"]["series"]) == 14


def test_routing_status_config_loi_bo_qua_va_thu_gateway(company_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`llm.yaml` có tồn tại (giả) nhưng load_config ném lỗi -> _routing_status() bỏ qua, coi như không có, đi hỏi gateway."""
    import console.collect as cmod

    monkeypatch.setattr(cmod.company_llm, "CONFIG_FILE", "gia-lap.yaml")
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(cmod.company_llm, "load_config", lambda p: (_ for _ in ()).throw(RuntimeError("hong config")))
    s = collect(company_db, gateway_url=DEAD_GATEWAY)
    assert s["backends"] == []
    assert s["sources"]["gateway"]["ok"] is False


def test_routing_status_tu_llm_yaml_that_khong_hoi_gateway(
    tmp_path: Path, company_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`llm.yaml` có `backends:` -> backends lấy từ routing.status() thật, gateway KHÔNG được hỏi (sources.gateway ok, error None).

    Trước đây nhánh này chỉ được phủ nhờ máy dev tình cờ có sẵn `software-company/llm.yaml` (bị gitignore) — trên CI
    không có file nên collect.py 395-408 và 527 chưa bao giờ chạy ở đó. Test tự tạo file để không phụ thuộc máy."""
    import console.collect as cmod

    llm_yaml = tmp_path / "llm.yaml"
    llm_yaml.write_text(
        "backends:\n"
        "  - name: antigravity\n"
        "    provider: openai\n"
        "    base_url: http://127.0.0.1:1123/v1\n"
        "    api_key: gateway-local\n"
        "    models: {strong: claude-sonnet-4-6, standard: gemini-3.7-flash, light: gemini-3.7-flash-low}\n"
        "  - name: local\n"
        "    provider: openai\n"
        "    base_url: http://localhost:11434/v1\n"
        "    models: {strong: qwen3:32b, standard: qwen3:8b}\n"
        "routing:\n"
        "  cooldown_s: 120\n"
        "  transient_cooldown_s: 5\n"
        "  prefer: {light: antigravity, strong: local}\n",
        encoding="utf-8",
    )
    # load_config ưu tiên biến môi trường: có COMPANY_LLM_PROVIDER thì backends bị xoá, COMPANY_LLM_BACKENDS thì bị lọc.
    monkeypatch.delenv("COMPANY_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("COMPANY_LLM_BACKENDS", raising=False)
    monkeypatch.setattr(cmod.company_llm, "CONFIG_FILE", llm_yaml)

    s = collect(company_db, gateway_url=DEAD_GATEWAY)

    assert [b["n"] for b in s["backends"]] == ["antigravity", "local"]
    assert all(b["ok"] and b["st"] == "Sẵn sàng" and b["tools"] == "có" for b in s["backends"])
    assert "strong" in s["backends"][0]["tiers"] and "light" in s["backends"][0]["tiers"]
    assert s["sources"]["gateway"] == {"ok": True, "url": DEAD_GATEWAY, "error": None}  # không hỏi gateway (đã chết)


def test_gateway_status_doc_token_that_bai_van_hoi_duoc(
    tmp_path: Path, company_db: Path, khong_co_llm_yaml: None
) -> None:
    """token_file trỏ tới đường dẫn không đọc được (thư mục) -> OSError bị nuốt, request vẫn không kèm token."""
    bad_token = tmp_path  # là thư mục, đọc như file sẽ ném OSError
    s = collect(company_db, gateway_token_file=bad_token, gateway_url=DEAD_GATEWAY)
    assert s["backends"] == []
    assert s["sources"]["gateway"]["ok"] is False


def test_gateway_status_thanh_cong_tra_danh_sach_account(
    tmp_path: Path, company_db: Path, khong_co_llm_yaml: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`GET /auth/status` thành công, kèm token file hợp lệ -> parse ra danh sách account đúng hình dạng."""
    import io
    import urllib.request

    token_file = tmp_path / "tok"
    token_file.write_text("abc123", encoding="utf-8")

    payload = json.dumps(
        {
            "accounts": [
                {
                    "email": "a@x.com",
                    "cooldown_remaining": 0,
                    "is_expired": False,
                    "last_failure_status": 0,
                    "source": "s1",
                },
                {
                    "email": "b@x.com",
                    "cooldown_remaining": 30,
                    "is_expired": False,
                    "last_failure_status": 429,
                    "source": "s2",
                },
                {"email": "c@x.com", "cooldown_remaining": 0, "is_expired": True, "source": "s3"},
            ]
        }
    ).encode("utf-8")

    class FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    captured_headers: dict[str, str] = {}

    def fake_urlopen(req, timeout=None):
        captured_headers.update(req.headers)
        return FakeResp(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    s = collect(company_db, gateway_token_file=token_file, gateway_url="http://gia-lap")
    assert s["sources"]["gateway"]["ok"] is True
    names = {b["n"] for b in s["backends"]}
    assert names == {"a@x.com", "b@x.com", "c@x.com"}
    by_name = {b["n"]: b for b in s["backends"]}
    assert by_name["a@x.com"]["ok"] is True and by_name["a@x.com"]["st"] == "Sẵn sàng"
    assert by_name["b@x.com"]["ok"] is False and "Nghỉ 30s" in by_name["b@x.com"]["st"]
    assert by_name["c@x.com"]["ok"] is False and by_name["c@x.com"]["st"] == "Hết hạn token"
    assert "Authorization" in captured_headers


def test_replay_ticket_cu_assignee_stack_khong_lam_chet_collect(company_db: Path) -> None:
    """Bus có ticket lập trước PR-5d (`assignee` là một stack) vẫn đọc lại được.

    Bản ghi được ghi THẲNG vào bảng `events` chứ không qua `bus.publish`: publish hôm nay validate
    theo schema mới nên không dựng nổi một bản ghi lịch sử: thứ phải mô phỏng là byte đã nằm trên
    đĩa từ trước, không phải một lần ghi mới.

    Chiều ngược đo được: đổi `Task.tu_log` ở `collect._replay()` về `Task.model_validate` thì
    `ValidationError: assignee Input should be 'builder'` ném thẳng ra khỏi `collect()` (đo được:
    FAILED ... src/console/collect.py:288: ValidationError) — đúng lỗi đã làm chết mặt kính trực ban
    trên DB thật của QLKH, nơi /api/stream trả lỗi thay vì dữ liệu.
    """
    body = json.loads(
        json.dumps(
            {
                "event_id": "ev-cu-999",
                "topic": "tasks",
                "key": "TCK-999",
                "actor": "delivery-lead",
                "ts": datetime.now(UTC).isoformat(),
                "payload": {
                    "ticket_id": "TCK-999",
                    "project_id": "P1",
                    "requirement_id": "R1",
                    # bản ghi lịch sử: `assignee` mang một trong sáu stack cũ, chưa có trường `stack`
                    "assignee": "platform",
                    "title": "ticket cu",
                    "acceptance": ["ok"],
                    "estimate_tokens": 1000,
                    "budget_tokens": 2000,
                },
            }
        )
    )
    # `with sqlite3.connect(...)` chỉ commit chứ không đóng kết nối — thiếu `closing()` là ResourceWarning nổ ở
    # một test khác lúc GC chạy (B7 của audit 2026-09-27; cùng họ với `test_review_fixes_2026_09.py` của company).
    with closing(sqlite3.connect(company_db)) as db, db:
        db.execute(
            "INSERT INTO events(event_id, topic, key, actor, ts, body) VALUES (?,?,?,?,?,?)",
            ("ev-cu-999", "tasks", "TCK-999", "delivery-lead", body["ts"], json.dumps(body)),
        )

    s = state(company_db)

    assert s["sources"][COMPANY]["ok"], s["sources"][COMPANY]
    assert "TCK-999" in [t["id"] for t in s["tickets"]]


def test_ticket_blocked_roi_merge_qua_already_integrated_khong_bao_bloc_gia(company_db: Path) -> None:
    """Đo được 2026-09-10 (QLKH, TCK-CR-STAGE-001-02): ticket hết retry → `blocked`; người duyệt escalation approve,
    orchestrator thấy code đã nằm trên nhánh tích hợp nên gọi `DeliveryLead.mark_done_already_integrated` — đưa
    thẳng ticket về `merged` và ghi audit `ticket.already_integrated` (evidence mang `state` cuối). `status` của
    orchestrator dựng lại đúng vì `orch/rehydrate.py` áp lại `ticket.blocked`/`ticket.already_integrated` từ
    audit-log khi mở lại tiến trình (xem chú thích ở `DeliveryLead._retry`).

    `DeliveryLead.replay()` (`console/collect.py::CompanyView._replay`) không có handler cho topic `audit-log`
    (xem `DeliveryLead.handlers`), nên khi console tự dựng lại toàn bộ trạng thái từ đầu bus mỗi lần đọc, hai hành
    động trên KHÔNG được áp lại: ticket coi như còn `blocked` mãi mãi, và mặt kính Trực ban tự sinh cảnh báo
    "bế tắc im lặng" cho một ticket đã xong từ lâu. Tắt nhánh `audit-log` mới thêm ở `_replay()` thì test này đỏ:
    `st` quay về `blocked` và ticket lọt vào `silent_deadlocks`."""
    tid = "TCK-DA-XONG-1"
    bus = CompanySQLiteBus(company_db)
    task = Task(
        ticket_id=tid,
        project_id="P1",
        requirement_id="R1",
        assignee="builder",
        title="việc bị chặn rồi được đánh dấu đã tích hợp",
        acceptance=["ok"],
        estimate_tokens=1_000,
        budget_tokens=2_000,
    )
    bus.publish(CompanyEnvelope(topic="tasks", key=tid, actor="delivery-lead", payload=task.model_dump()))
    bus.publish(
        CompanyEnvelope(
            topic="audit-log",
            key="delivery-lead",
            actor="delivery-lead",
            payload=CompanyAudit(
                actor="delivery-lead",
                action="ticket.blocked",
                ticket_id=tid,
                evidence=json.dumps({"ticket_id": tid, "retry": 3, "max_retries": 3}, ensure_ascii=False),
            ).model_dump(),
        )
    )
    bus.publish(
        CompanyEnvelope(
            topic="audit-log",
            key="delivery-lead",
            actor="delivery-lead",
            payload=CompanyAudit(
                actor="delivery-lead",
                action="ticket.already_integrated",
                ticket_id=tid,
                evidence=json.dumps({"ticket_id": tid, "state": "merged"}, ensure_ascii=False),
            ).model_dump(),
        )
    )
    bus.close()

    s = state(company_db)

    by_id = {t["id"]: t["st"] for t in s["tickets"]}
    assert by_id[tid] == "merged", by_id
    assert tid not in {d["id"] for d in s["silent_deadlocks"]}


def _hoi_lam_ro(company_db: Path, answers: list[dict] | None = None) -> None:
    bus = CompanySQLiteBus(company_db)
    if answers is None:
        bus.publish(
            CompanyEnvelope(
                topic="clarification-questions",
                key="P1",
                actor="product",
                payload={
                    "project_id": "P1",
                    "round": 1,
                    "questions": [{"id": "Q-01", "req_id": "FR-1", "text": "A hay B?", "options": ["A", "B"], "default": "A"}],
                },
            )
        )
    else:
        bus.publish(
            CompanyEnvelope(
                topic="clarification-answers",
                key="P1",
                actor="human:owner",
                payload={"project_id": "P1", "answers": answers},
            )
        )
    bus.close()


def test_cau_hoi_lam_ro_dang_cho_hien_trong_hang_doi_gate(company_db: Path) -> None:
    """Đo 2026-09-22 (CAMPUS-UNI): `product` đăng `clarification-questions`, chưa ai trả lời; console chỉ có form
    trả lời, không có chỗ nào NÓI rằng đang có câu hỏi chờ. Người trực nhìn "Sạch hàng đợi" trong khi dự án đứng
    im. Câu hỏi chờ đi CHUNG hàng đợi gate (một chỗ duy nhất để người trực nhìn), kind `clarification`, không
    duyệt được (không phải HumanGate) — chỉ trỏ tới form trả lời."""
    _hoi_lam_ro(company_db)
    s = state(company_db)
    g = next((g for g in s["gates"] if g["id"] == "CLARIFY-P1"), None)
    assert g is not None, f"câu hỏi chờ phải hiện trong hàng đợi, có: {[x['id'] for x in s['gates']]}"
    assert g["kind"] == "clarification" and g["xuong"] == COMPANY and g["by"] == "product"
    assert g["decidable"] is False, "không phải HumanGate — nút duyệt phải tắt"
    assert any("Q-01" in c[0] for c in g["cl"]), "checklist là chính các câu hỏi, để người trực đọc tại chỗ"
    assert g["hours"] >= 0 and g["sev"] in {"calm", "warn", "over"}
    assert all(x["decidable"] is True for x in s["gates"] if x["id"] != "CLARIFY-P1"), "gate thật vẫn duyệt được"
    _hoi_lam_ro(company_db, answers=[{"question_id": "Q-01", "answer": "A"}])  # trả lời đủ → biến mất
    assert "CLARIFY-P1" not in {g["id"] for g in state(company_db)["gates"]}


def test_khong_co_quality_journal_thi_khong_co_profile(company_db: Path) -> None:
    """ADR-0021 §f: chưa ai ký profile ⇒ không có `<db>.quality.sqlite` ⇒ trang hiện "không có profile" (`None`),
    và console tuyệt đối không tự tạo file để trả lời câu hỏi này."""
    journal = company_db.with_suffix(".quality.sqlite")
    assert not journal.exists()
    s = state(company_db)
    assert s["quality"] is None
    assert not journal.exists(), "console chỉ đọc — không được tạo journal"


def test_co_quality_journal_thi_hien_run_va_check(company_db: Path) -> None:
    """Có journal cạnh bus ⇒ `state["quality"]` liệt kê run kèm trạng thái `quality:accept` và check đã pass."""
    journal = company_db.with_suffix(".quality.sqlite")
    _build_quality_journal(journal)
    s = state(company_db)
    assert s["quality"] == [{"run_id": "RUN-OK", "status": "succeeded",
                             "checks_total": ["tests"], "checks_passed": ["tests"], "blocker": ""}]


def test_khong_doc_duoc_bus_van_doc_duoc_quality(tmp_path: Path) -> None:
    """Journal là nguồn riêng của nó (cạnh bus, không phụ thuộc bus replay được hay không, §f)."""
    db = tmp_path / "khong-ton-tai.sqlite"
    _build_quality_journal(db.with_suffix(".quality.sqlite"))
    s = state(db)
    assert s["sources"][COMPANY]["ok"] is False
    assert s["quality"] == [{"run_id": "RUN-OK", "status": "succeeded",
                             "checks_total": ["tests"], "checks_passed": ["tests"], "blocker": ""}]


# ---------- phủ nhánh (branch = true, audit 2026-09-28, #366) ----------

def _ticket(bus: CompanySQLiteBus, tid: str, **extra: object) -> None:
    task = Task(ticket_id=tid, project_id="P1", requirement_id="R1", assignee="builder", title="t", acceptance=["ok"],
                budget_tokens=1_000, **extra)
    bus.publish(CompanyEnvelope(topic="tasks", key=tid, actor="delivery-lead", payload=task.model_dump()))


def _pr(bus: CompanySQLiteBus, tid: str, local_checks: dict) -> None:
    pr = PullRequest(ticket_id=tid, branch=f"ticket/{tid}", pr_ref="PR-1", local_checks=local_checks)
    bus.publish(CompanyEnvelope(topic="pull-requests", key=tid, actor="builder", payload=pr.model_dump()))


def test_pr_chua_chay_kiem_cuc_bo_hien_dau_hoi_khong_phai_fail(tmp_path: Path) -> None:
    """`local_checks` thiếu `lint`/`tests` là CHƯA CHẠY — hiện "?", không được gộp với chạy mà đỏ ("fail")."""
    db = tmp_path / "company.sqlite"
    bus = CompanySQLiteBus(db)
    _ticket(bus, "TCK-1")
    _pr(bus, "TCK-1", {"lint": False})
    bus.close()
    row = next(p for p in state(db)["prs"] if p["id"] == "TCK-1")
    assert (row["lint"], row["tests"], row["v"]) == ("fail", "?", "unverified")


def test_checklist_note_lay_ket_luan_review_that_va_cat_theo_note_width() -> None:
    v = object.__new__(collect_mod.CompanyView)
    goc = "thiếu kiểm tra quyền ở mọi route quản trị " * 5
    v.envelopes = [SimpleNamespace(topic="review-results", payload={
        "ticket_id": "TCK-1", "source": "reviewer", "verdict": "block", "root_cause": goc})]
    r = SimpleNamespace(subject_id="TCK-1")
    assert len(f"block · {goc}") > collect_mod.NOTE_WIDTH
    assert v.checklist_note(r, "review:reviewer:block") == f"block · {goc}"[: collect_mod.NOTE_WIDTH]
    assert v.checklist_note(r, "review:security:pass") == ""   # nguồn chưa có review → không bịa
    assert v.checklist_note(r, "tests") == ""                  # mục không phải review


def test_log_moi_xuong_dung_o_log_limit_ban_ghi_moi_nhat() -> None:
    """`log()` dừng ở LOG_LIMIT dòng MỚI NHẤT — không dựng hàng nghìn dòng mỗi lượt poll rồi mới cắt ở `collect()`."""
    v = object.__new__(collect_mod._View)
    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    v.envelopes = [SimpleNamespace(topic="audit-log", key=f"k{i}", ts=t0 + timedelta(minutes=i),
                                   payload={"action": "produced:tasks", "actor": "builder", "tokens": i})
                   for i in range(collect_mod.LOG_LIMIT + 1)]
    rows = v.log()
    assert len(rows) == collect_mod.LOG_LIMIT
    assert rows[0][1]["tok"] == collect_mod.LOG_LIMIT   # mới nhất đứng đầu
    assert rows[-1][1]["tok"] == 1                      # bản cũ nhất (0) bị cắt


def test_task_phat_lai_cua_ticket_da_biet_khong_dang_ky_lai(tmp_path: Path) -> None:
    """Replay gặp `tasks` của ticket đã biết: console không đăng ký lại (đè trạng thái về `dispatched`), để
    `DeliveryLead.replay` quyết — bản trùng bị bỏ qua, bản rework (retry tăng) mới kéo ticket về `dispatched`."""
    db = tmp_path / "company.sqlite"
    bus = CompanySQLiteBus(db)
    _ticket(bus, "TCK-1")
    _pr(bus, "TCK-1", {"lint": True, "tests": True, "verified_by": "workspace"})
    _ticket(bus, "TCK-1")                                   # phát lại y hệt
    bus.close()
    truoc = next(t for t in state(db)["tickets"] if t["id"] == "TCK-1")
    assert truoc["st"] == "in_review" and truoc["retry"] == 0

    bus = CompanySQLiteBus(db)
    _ticket(bus, "TCK-1", retry=1, hint="sửa theo review")  # rework thật
    bus.close()
    sau = next(t for t in state(db)["tickets"] if t["id"] == "TCK-1")
    assert sau["st"] == "dispatched" and sau["retry"] == 1


def test_routing_status_llm_yaml_khong_co_backend_thi_hoi_gateway(
    tmp_path: Path, company_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`llm.yaml` có mà không khai `backends:` → không có gì để hỏi `routing.status()`; phải rơi về gateway
    (ở đây đã chết → `sources.gateway.ok = False`), không trả danh sách rỗng giả làm "không có backend nào"."""
    llm_yaml = tmp_path / "llm.yaml"
    llm_yaml.write_text("provider: fake\n", encoding="utf-8")
    may = tmp_path / "may.yaml"
    may.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv(MAY_CONFIG_ENV, str(may))   # tầng máy rỗng: llm.yaml tầng máy của người chạy test không lọt vào
    monkeypatch.delenv("COMPANY_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("COMPANY_LLM_BACKENDS", raising=False)
    monkeypatch.setattr(collect_mod.company_llm, "CONFIG_FILE", llm_yaml)

    assert collect_mod._routing_status() is None
    s = collect(company_db, gateway_url=DEAD_GATEWAY)
    assert s["backends"] == [] and s["sources"]["gateway"]["ok"] is False


def test_chi_phi_ngoai_cua_so_khong_don_vao_ngay_nao(tmp_path: Path) -> None:
    db = tmp_path / "company.sqlite"
    bus = CompanySQLiteBus(db)
    _produced(bus, CompanyEnvelope, CompanyAudit, actor="builder", topic_out="pull-requests", tokens=10, cost=5.0,
              age_days=collect_mod.COST_WINDOW_DAYS + 6)
    _produced(bus, CompanyEnvelope, CompanyAudit, actor="builder", topic_out="pull-requests", tokens=10, cost=0.25)
    bus.close()
    series = state(db)["cost_days"]["series"]
    assert len(series) == collect_mod.COST_WINDOW_DAYS
    assert sum(sum(day) for day in series) == pytest.approx(0.25)
