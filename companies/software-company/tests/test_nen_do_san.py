"""ADR-0062: test đỏ sẵn trên nền (điểm rẽ nhánh) không tính là ticket trượt — ticket nằm chờ tới khi nền đổi.

Hub thật (QLKH-DD-CSV, 2026-10-16): DDCSV-110 merge làm 10 test `tests/dpia/` đỏ trên nhánh tích hợp. DDCSV-111 và
DDCSV-132 hết 3 lượt rồi bị REPLAN thay; DDCSV-138 (compose, không chạm `tests/dpia`) bị trả về vì đúng 10 test đó.

Hai chiều (luật bắt buộc 4), đo 2026-10-16: bỏ nhánh `base_red` khỏi `engineer` → ca engineer đỏ; bỏ điều kiện
"còn ticket khác đang chạy" → ca từ chối đỏ; bỏ `base_wait.clear()` ở `mark_integrated` → ca nhả đỏ; bỏ `catch_up`
khi giao lại → ca đầu-cuối đỏ; bỏ nhánh `ticket.base_red` ở `rehydrate` → ca mở lại bus đỏ. Bật lại: cả năm xanh.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from company.bus import InMemoryBus
from company.events import Envelope, Task
from company.llm import FakeClient
from company.orch.routes import Route
from company.orch.worktree_flow import engineer
from company.orchestrator import Orchestrator
from company.sqlite_bus import SQLiteBus
from company.stacks import failed_tests
from company.tools import ToolCall
from company.workspace import TicketWorkspace
from test_orchestrator import handler

CU = "test_cu.py::test_cu"


def _repo(path: Path) -> Path:
    """Repo khách mà nền đã có một test đỏ (`test_cu.py`), như `tests/dpia` sau DDCSV-110."""
    path.mkdir()

    def git(*a):
        subprocess.run(["git", "-C", str(path), *a], check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (path / "pyproject.toml").write_text('[project]\nname = "khach"\nversion = "0.1.0"\n', encoding="utf-8")
    (path / "test_cu.py").write_text("def test_cu():\n    x = 1\n    assert x == 2\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "init")
    return path


def _task(tid: str, **kw) -> Task:
    return Task(
        ticket_id=tid,
        project_id="P1",
        requirement_id="R1",
        assignee="builder",
        title=tid,
        acceptance=["a"],
        budget_tokens=6_000,
        **kw,
    )


def _orch(bus, repo=None, tool_handler=None) -> Orchestrator:
    return Orchestrator(bus, FakeClient(handler=handler, tool_handler=tool_handler), repo=repo, base="main")


def _hai_ticket(orch, a="A", b="B", sb="dispatched"):
    for tid, st in ((a, "dispatched"), (b, sb)):
        orch.lead.tickets[tid] = _task(tid)
        orch.lead.state[tid] = st


def _base_red(bus) -> list[dict]:
    return [
        json.loads(e.payload["evidence"])
        for e in bus.replay(topic="audit-log")
        if e.payload["action"] == "ticket.base_red"
    ]


# ---------- đọc tóm tắt pytest ----------


def test_doc_id_test_do_tu_tom_tat_pytest():
    out = (
        "..F\n=== short test summary info ===\nFAILED tests/a.py::test_x[V-18] - AssertionError\n"
        "ERROR tests/b.py::test_y\n1 failed, 3 passed, 1 error in 0.12s\n"
    )
    assert failed_tests(out) == ["tests/a.py::test_x[V-18]", "tests/b.py::test_y"]


def test_tom_tat_bi_cat_hoac_khong_phai_pytest_thi_khong_chung_minh_duoc():
    assert failed_tests("FAILED tests/a.py::test_x\n2 failed in 0.1s\n") is None, "thiếu id: output bị cắt"
    assert failed_tests("npm ERR! Test failed.\n") is None
    assert failed_tests("3 passed in 0.1s\n") is None, "không có test đỏ thì không có gì để chứng minh"


# ---------- chạy lại đúng test đỏ trên điểm rẽ nhánh ----------


def test_test_do_san_o_nen_va_test_moi_cua_ticket_duoc_tach_rieng(tmp_path):
    repo = _repo(tmp_path / "repo")
    ws = TicketWorkspace(repo, "A", base="main")
    ws.create()
    assert ws.inherited_failures([CU]) == {CU}
    (ws.path / "test_moi.py").write_text("def test_moi():\n    assert False\n", encoding="utf-8")
    ws.commit_all("ticket thêm test đỏ của chính nó")
    assert ws.inherited_failures([CU, "test_moi.py::test_moi"]) is None, (
        "test mới không có ở nền: không chứng minh được"
    )
    (repo / "test_cu.py").write_text("def test_cu():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "sửa nền"], check=True)
    assert ws.inherited_failures([CU]) == {CU}, "so với điểm rẽ nhánh, không phải đầu nhánh nền đã đi tiếp"
    assert not (repo / ".worktrees" / ".nen-A").exists(), "worktree tạm được dọn"
    assert ws.inherited_failures([]) is None


def test_test_xanh_o_nen_thi_khong_phai_do_san(tmp_path):
    repo = _repo(tmp_path / "repo")
    (repo / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "ok"], check=True)
    ws = TicketWorkspace(repo, "A", base="main")
    ws.create()
    assert ws.inherited_failures(["test_ok.py::test_ok"]) == set()


# ---------- DeliveryLead: chờ, nhả, trần ----------


def test_ticket_nam_cho_khong_dot_retry_va_duoc_giao_lai_khi_nen_doi():
    bus = InMemoryBus()
    orch = _orch(bus)
    _hai_ticket(orch)
    assert orch.lead.park_base_red("A", "đỏ sẵn: test_cu")
    assert orch.lead.state["A"] == "waiting" and orch.lead.tickets["A"].retry == 0
    assert orch.lead.stops["A"]["base_red"] == 1
    assert orch.lead._flush_waiting() == [], "nền chưa đổi: không giao lại"
    orch.lead.mark_integrated("B")
    assert orch.lead.state["A"] == "dispatched"
    t = [e.payload for e in bus.replay(topic="tasks") if e.key == "A"][-1]
    assert t["retry"] == 0 and "đỏ sẵn" in t["hint"]


def test_khong_con_ticket_nao_chay_thi_khong_cho():
    bus = InMemoryBus()
    orch = _orch(bus)
    _hai_ticket(orch, sb="waiting")
    assert not orch.lead.park_base_red("A", "đỏ sẵn"), "không ai đổi được nền: chờ là treo"
    assert orch.lead.state["A"] == "dispatched"


def test_qua_tran_ba_lan_thi_khong_cho_nua():
    bus = InMemoryBus()
    orch = _orch(bus)
    _hai_ticket(orch)
    for _ in range(3):
        assert orch.lead.park_base_red("A", "đỏ sẵn")
        orch.lead.base_wait.clear()
        orch.lead._flush_waiting()
    assert not orch.lead.park_base_red("A", "đỏ sẵn")


def test_ticket_cuoi_dang_chay_bi_chan_thi_nha_ticket_dang_cho():
    bus = InMemoryBus()
    orch = _orch(bus)
    _hai_ticket(orch)
    orch.lead.max_retries = 1
    assert orch.lead.park_base_red("A", "đỏ sẵn")
    orch.lead.rework("B", "đỏ thật")  # retry+1 chạm trần → blocked
    assert orch.lead.state["B"] == "blocked" and orch.lead.state["A"] == "dispatched"


# ---------- engineer: PR đỏ vì nền → chờ, không làm lại ----------


def _ghi_file_tot(msgs, tools):
    if "write_file" in {t.name for t in tools} and not any(m["role"] == "assistant" for m in msgs):
        return [ToolCall(id="c1", name="write_file", args={"path": "f_a.py", "content": "def a():\n    return 1\n"})]
    return []


def test_pr_do_chi_vi_nen_thi_ticket_nam_cho_va_co_bang_chung(tmp_path):
    repo = _repo(tmp_path / "repo")
    bus = InMemoryBus()
    orch = _orch(bus, repo, _ghi_file_tot)
    _hai_ticket(orch)
    TicketWorkspace(repo, "A", base="main").create()
    task = Envelope(topic="tasks", key="A", actor="delivery-lead", payload=orch.lead.tickets["A"].model_dump())
    assert engineer(orch, "builder", task, Route(topic_in="tasks", agent="builder", topic_out="pull-requests")) is None
    assert orch.lead.state["A"] == "waiting" and orch.lead.tickets["A"].retry == 0
    ev = _base_red(bus)
    assert ev and ev[0]["ticket_id"] == "A" and ev[0]["inherited"] == [CU] and ev[0]["verified_by"] == "workspace"
    assert not [e for e in bus.replay(topic="pull-requests")], "PR đỏ không publish"

    bus2 = InMemoryBus()  # dựng lại từ log: ticket vẫn chờ
    for e in bus.replay():
        bus2.publish(e)
    o2 = _orch(bus2)
    assert o2.lead.state.get("A") == "waiting" and "A" in o2.lead.base_wait


def test_mo_lai_bus_giu_trang_thai_cho(tmp_path):
    db = tmp_path / "c.sqlite"
    bus = SQLiteBus(db)
    orch = _orch(bus)
    _hai_ticket(orch)
    for tid in ("A", "B"):
        bus.publish(
            Envelope(topic="tasks", key=tid, actor="delivery-lead", payload=orch.lead.tickets[tid].model_dump())
        )
    orch.lead.park_base_red("A", "đỏ sẵn")
    orch._audit("ticket.base_red", {"ticket_id": "A", "hint": "đỏ sẵn"}, ticket_id="A")
    bus.close()
    o2 = _orch(SQLiteBus(db))
    assert o2.lead.state.get("A") == "waiting" and o2.lead.stops["A"]["base_red"] == 1


# ---------- nhả ra thì chạy trên nền MỚI ----------


def test_bat_kip_nen_moi_va_xung_dot_thi_huy(tmp_path):
    repo = _repo(tmp_path / "repo")
    ws = TicketWorkspace(repo, "A", base="main")
    ws.create()
    (ws.path / "f_a.py").write_text("x = 1\n", encoding="utf-8")
    ws.commit_all("việc của A")
    (repo / "test_cu.py").write_text("def test_cu():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "sửa nền"], check=True)
    assert ws.catch_up() and "assert True" in (ws.path / "test_cu.py").read_text(encoding="utf-8")
    assert ws.changed_files() == ["f_a.py"], "diff cho reviewer vẫn chỉ là việc của ticket"
    (ws.path / "f_a.py").write_text("x = 2\n", encoding="utf-8")
    assert not ws.catch_up(), "đang dở thì không merge"
    ws.commit_all("A sửa tiếp")
    (repo / "f_a.py").write_text("x = 3\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "nền đụng cùng file"], check=True)
    assert not ws.catch_up() and not ws.dirty(), "xung đột: huỷ merge, nhánh giữ nguyên"


def test_nen_duoc_sua_thi_ticket_nha_ra_bat_kip_va_ra_pr_xanh(tmp_path):
    repo = _repo(tmp_path / "repo")
    bus = InMemoryBus()
    n = [0]

    def th(msgs, tools):
        if "write_file" in {t.name for t in tools} and not any(m["role"] == "assistant" for m in msgs):
            n[0] += 1
            return [
                ToolCall(
                    id="c1", name="write_file", args={"path": "f_a.py", "content": f"def a():\n    return {n[0]}\n"}
                )
            ]
        return []

    orch = _orch(bus, repo, th)
    _hai_ticket(orch)
    route = Route(topic_in="tasks", agent="builder", topic_out="pull-requests")
    task = Envelope(topic="tasks", key="A", actor="delivery-lead", payload=orch.lead.tickets["A"].model_dump())
    assert engineer(orch, "builder", task, route) is None and orch.lead.state["A"] == "waiting"

    integ = repo / ".worktrees" / "_integration"  # ticket khác sửa nền và merge vào nhánh tích hợp
    (integ / "test_cu.py").write_text("def test_cu():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(integ), "commit", "-qam", "B sửa nền"], check=True)
    orch.lead.mark_integrated("B")
    assert orch.lead.state["A"] == "dispatched"

    task = [e for e in bus.replay(topic="tasks") if e.key == "A"][-1]
    pr = engineer(orch, "builder", task, route)
    assert pr is not None and pr.payload["local_checks"]["tests"] is True, "lượt sau chạy trên nền đã sửa"
    assert pr.payload["impact"]["files"] == ["f_a.py"] and orch.lead.tickets["A"].retry == 0


def test_khong_chung_minh_duoc_hoac_khong_duoc_cho_thi_lam_lai_nhu_cu(tmp_path):
    from company.orch.worktree_flow import base_red, workspace

    repo = _repo(tmp_path / "repo")
    bus = InMemoryBus()
    orch = _orch(bus, repo)
    _hai_ticket(orch, sb="waiting")
    ws = workspace(orch, "A")
    ws.create()
    do = {"test_output": f"FAILED {CU}\n1 failed in 0.1s\n"}
    assert not base_red(orch, ws, "A", {"test_output": "npm ERR! Test failed.\n"}), "không phải pytest"
    assert not base_red(orch, ws, "Z", do), "ticket lạ"
    assert not base_red(orch, ws, "A", do), "không còn ticket nào chạy"
    moi = {"test_output": "FAILED test_moi.py::test_moi\n1 failed in 0.1s\n"}
    assert not base_red(orch, ws, "A", moi), "test đỏ không có ở nền"
    assert orch.lead.state["A"] == "dispatched" and not _base_red(bus)
    ws.base = "khong-co-nhanh-nay"
    assert ws.inherited_failures([CU]) is None, "lỗi git: không chứng minh được"
