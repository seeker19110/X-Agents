"""`company.gate_brief` — hồ sơ bằng chứng cho nửa "người tự kiểm thêm" của gate (đặc tả §5, §8.2).

Bất biến kiểm ở đây: chỉ đọc (I3), kind suy từ replay chứ không tham số hoá, không có giá trị nào mang nghĩa
quyết định (I6: verdict ∈ {ok, gap, unknown}), trích tối đa 200 ký tự mỗi nguồn (§7), và schema JSON ổn định
(golden theo kind, cập nhật bằng UPDATE_GOLDEN=1).
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from company import gate_brief as GB
from company.events import Envelope
from company.llm import FakeClient, LLMError
from company.orchestrator import ENGINEERING, Orchestrator
from company.sqlite_bus import SQLiteBus
from test_orchestrator import _agent_of, _drive_to_plan, _product_phase, _pub, handler
from test_tools_and_agentic import _init_repo, _repo_tool_handler

GOLDEN = Path(__file__).parent / "golden" / "gate_brief"
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"

PRD = """# PRD P1
## Yêu cầu
- REQ-1 GET /orders trả danh sách đơn
- REQ-2 POST /payments nhận email và số điện thoại khách
## NFR
- p95 < 300 ms cho GET /orders
- sẵn sàng 99.9 %
- mô tả không có số
## Ngoài phạm vi
- Không làm app mobile
"""
C4 = "# C4\nThư viện: fastapi (MIT license), dịch vụ ngoài: cổng thanh toán VNPay\n"
CONTRACT = "openapi: 3.0.0\npaths:\n  /orders:\n    get: {}\n  /payments:\n    post: {}\n"
THREAT = "# Threat model\nPhân loại dữ liệu: PII mức 2; DPIA: cần\n"


def rich_handler(system: str, user: str) -> dict:
    """`handler` của test_orchestrator + TOÀN VĂN artifact để hồ sơ có gì mà rút."""
    out = handler(system, user); a = _agent_of(system)
    # ADR-0037 PR-5e: PRD và C4/contract nay do CÙNG một agent viết ở hai pha khác nhau — phân biệt bằng pha,
    # không bằng tên agent (nếu chỉ so tên thì nhánh thứ hai chết và hồ sơ gate mất `architecture`).
    if a == "product" and _product_phase(system) == "spec" and "context_writes" in out:
        out["context_writes"][0]["content"] = PRD
    elif a == "product" and _product_phase(system) == "plan" and "items" in out:
        out["context_writes"][0]["content"] = C4; out["context_writes"][1]["content"] = CONTRACT
    elif a == "security" and "context_writes" in out: out["context_writes"][0]["content"] = THREAT
    return out


def fail_handler(system: str, user: str) -> dict:
    """Khối kỹ thuật trả đầu ra sai schema mãi → retry tới blocked → gate escalation."""
    if _agent_of(system) in ENGINEERING: return {"ticket_id": "T1", "nonsense": True}
    return rich_handler(system, user)


def stall_handler(system: str, user: str) -> dict:
    if _agent_of(system) == "product" and _product_phase(system) == "intake": raise LLMError("product[intake] nổ")
    return rich_handler(system, user)


def _scenario(tmp_path: Path, h=rich_handler, *, to: str = "acceptance", repo: Path | None = None):
    db = tmp_path / "c.sqlite"; bus = SQLiteBus(db)
    client = FakeClient(handler=h, tool_handler=_repo_tool_handler if repo else None)
    orch = Orchestrator(bus, client, repo=repo, base="main" if repo else "HEAD")
    if to == "stalled":
        _pub(bus, "research-requests", "P1", "human:sales", {"project_id": "P1", "description": "app"}); orch.run()
        return db, bus, orch
    _drive_to_plan(bus, orch)
    if to == "plan": return db, bus, orch   # ADR-0037: mốc "vừa lập xong kế hoạch", không còn gate nào chờ
    orch.run()
    if to in {"release", "escalation"}: return db, bus, orch
    orch.gate.decide("REL-001", "approve", by="human:release-manager"); orch.run()
    return db, bus, orch


def _rows(db: Path) -> int:
    con = sqlite3.connect(db)
    try: return con.execute("SELECT count(*) FROM events").fetchone()[0]
    finally: con.close()


def _norm(b: dict) -> dict:
    """Bỏ phần phụ thuộc thời gian/đường dẫn/event_id ngẫu nhiên để so golden theo cấu trúc và sự việc."""
    b = json.loads(json.dumps(b, ensure_ascii=False))
    for k in ("created_at", "age_hours", "due"): b.pop(k)
    def walk(x):
        if isinstance(x, dict):
            for k in list(x):
                if k == "event_ids": x[k] = len(x[k])
                elif k in {"at", "path", "diff_stat"} and x[k] is not None: x[k] = "<…>"
                else: walk(x[k])
        elif isinstance(x, list):
            for i in x: walk(i)
    walk(b); return b


def _check_golden(kind: str, b: dict) -> None:
    got = json.dumps(_norm(b), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    f = GOLDEN / f"{kind}.json"
    if UPDATE: f.write_text(got, encoding="utf-8", newline="\n"); return
    assert f.exists(), f"thiếu golden {f}: chạy UPDATE_GOLDEN=1"
    assert f.read_text(encoding="utf-8") == got, f"schema/sự việc hồ sơ {kind} đổi — cố ý thì UPDATE_GOLDEN=1"


def _verdicts(b: dict) -> dict[str, str]:
    return {it["id"]: it["verdict"] for it in b["self_check"]}


# ---------- I3: chỉ đọc ----------

def test_chi_doc(tmp_path):
    db, bus, _orch = _scenario(tmp_path)
    n_rows, n_bus = _rows(db), len(bus)
    orch2 = GB.load_state(db)
    for sid in ("REL-002", "UAT-REL-001"):
        GB.build(orch2, sid)
    assert GB.main(["--all", "--db", str(db), "--out", str(tmp_path / "out")]) == 0
    assert _rows(db) == n_rows and len(orch2.bus) == n_bus and len(bus) == n_bus, "hồ sơ không được ghi bus"
    assert bus.poll() == [], "không có event nào do tiến trình khác ghi thêm"
    assert (tmp_path / "out" / "REL-002.json").exists() and (tmp_path / "out" / "UAT-REL-001.md").exists()


def test_khong_co_db_hoac_repo_sai(tmp_path, capsys):
    with pytest.raises(GB.BriefError):
        GB.open_read_only(tmp_path / "khong.sqlite")
    assert GB.main(["X", "--db", str(tmp_path / "khong.sqlite")]) == 3
    db, _, _ = _scenario(tmp_path, to="plan")
    assert GB.main(["SPEC-P1", "--db", str(db), "--repo", str(tmp_path / "khong-phai-repo")]) == 3
    assert GB.main(["--db", str(db)]) == 2, "cần subject hoặc --all"


# ---------- kind suy ra từ replay ----------

def test_kind_suy_ra_tu_replay(tmp_path):
    db, _, _ = _scenario(tmp_path)
    orch = GB.load_state(db)
    assert GB.build(orch, "REL-002")["kind"] == "release"
    assert GB.build(orch, "UAT-REL-001")["kind"] == "acceptance"
    spec = GB.build(orch, "SPEC-P1", closed=True)
    assert spec["kind"] == "spec" and spec["status"] == "approve" and spec["project_id"] == "P1"
    with pytest.raises(GB.NotPending):
        GB.build(orch, "PLAN-P1-1", closed=True)   # ADR-0037: không còn gate plan để dựng hồ sơ
    for b in (spec,):
        assert set(_verdicts(b).values()) <= {"ok", "gap", "unknown"}
        assert b["schema_version"] == 1 and {"self_check", "unavailable", "code_checklist", "extra"} <= set(b)


def test_subject_khong_ton_tai(tmp_path, capsys):
    db, _, _ = _scenario(tmp_path)
    assert GB.main(["KHONG-CO", "--db", str(db)]) == 2
    assert GB.main(["SPEC-P1", "--db", str(db), "--no-write"]) == 2, "gate đã đóng: cần --closed"
    assert GB.main(["KHONG-CO", "--db", str(db), "--closed"]) == 2
    assert "--closed" in capsys.readouterr().err


# ---------- spec ----------

def test_spec_rut_nfr_out_of_scope_pii_va_cau_hoi_mo(tmp_path):
    db, bus, _ = _scenario(tmp_path, to="plan")
    orch = GB.load_state(db)
    b = GB.build(orch, "SPEC-P1", closed=True); v = _verdicts(b); facts = {it["id"]: it["facts"] for it in b["self_check"]}
    assert v["spec.nfr-co-so-do"] == "ok" and "3 dòng, 2 dòng có ngưỡng" in facts["spec.nfr-co-so-do"][0]
    assert v["spec.out-of-scope"] == "ok" and "1 mục" in facts["spec.out-of-scope"][0]
    assert v["spec.pii"] == "unknown" and any("có nhắc phân loại" in f for f in facts["spec.pii"])
    assert v["spec.cau-hoi-mo"] == "ok"
    src = next(it for it in b["self_check"] if it["id"] == "spec.nfr-co-so-do")["sources"][0]
    # So bằng `Path.parts`, không phải `endswith("prd/latest.md")`: đường dẫn mirror do `pathlib` dựng nên trên
    # Windows là `prd\latest.md` — test cũ xanh trên Linux và đỏ trên Windows, đúng kiểu "test đúng-sai theo nền
    # tảng" mà repo đã gặp một lần ở `_bo_dau_thoi_gian` (tests/test_orchestrator.py).
    assert src["kind"] == "namespace" and src["ref"] == "prd"
    assert Path(src["path"]).parts[-2:] == ("prd", "latest.md")
    # thêm một vòng câu hỏi chưa ai trả lời → gap
    bus.publish(Envelope(topic="clarification-questions", key="P1", actor="product",
                         payload={"project_id": "P1", "round": 2, "questions": [{"id": "Q9", "text": "?", "options": ["a"], "default": "a"}]}))
    b2 = GB.build(GB.load_state(db), "SPEC-P1", closed=True)
    assert _verdicts(b2)["spec.cau-hoi-mo"] == "gap" and any("Q9" in f for f in next(it for it in b2["self_check"] if it["id"] == "spec.cau-hoi-mo")["facts"])
    _check_golden("spec", b)


def test_spec_khong_co_toan_van_thi_unknown_va_khong_neu_duong_dan(tmp_path):
    db, _, _ = _scenario(tmp_path, handler, to="plan")  # handler gốc: blackboard chỉ có con trỏ
    b = GB.build(GB.load_state(db), "SPEC-P1", closed=True)
    v = _verdicts(b)
    assert v["spec.nfr-co-so-do"] == "unknown" and v["spec.out-of-scope"] == "unknown"
    src = next(it for it in b["self_check"] if it["id"] == "spec.nfr-co-so-do")["sources"][0]
    assert src["path"] is None and src["content_ref"] == "docs/prd.md"
    assert "chỉ có con trỏ" in GB.render_md(b)


def test_pii_cat_200_ky_tu(tmp_path):
    long_line = "Email khách hàng: " + "a" * 900 + "@x.vn"
    def h(system, user):
        out = rich_handler(system, user)
        if _agent_of(system) == "product" and _product_phase(system) == "spec" and "context_writes" in out:
            out["context_writes"][0]["content"] = PRD + "\n" + long_line + "\n"
        return out
    db, _, _ = _scenario(tmp_path, h, to="plan")
    b = GB.build(GB.load_state(db), "SPEC-P1", closed=True)
    for it in b["self_check"]:
        for f in it["facts"]:
            assert len(f) <= GB.EXCERPT + 40, f"fact dài quá: {len(f)}"
    assert GB.excerpt("x" * 500) == "x" * 199 + "…" and GB.excerpt("  a   b ") == "a b" and GB.excerpt(None) == ""


# ---------- hai mục dời từ gate plan cũ, nay nằm ở gate release (ADR-0037) ----------

def test_release_uoc_luong_va_ngan_sach_doi_tu_gate_plan(tmp_path):
    """ADR-0037 bỏ gate plan; hai mục người-tự-kiểm của nó ("ước lượng có cơ sở", "ngân sách token") không mất
    mà dời sang gate release, giữ nguyên `id` cũ để hồ sơ đã ghi ra đĩa còn đọc được."""
    db, _, _ = _scenario(tmp_path, to="release")
    b = GB.build(GB.load_state(db), "REL-001")
    v = _verdicts(b); facts = {it["id"]: it["facts"] for it in b["self_check"]}
    assert v["plan.uoc-luong-co-so"] == "unknown" and "1/1 ticket có estimate_tokens" in facts["plan.uoc-luong-co-so"][0]
    assert any("dự án đầu" in f for f in facts["plan.uoc-luong-co-so"])
    assert v["plan.ngan-sach-token"] == "unknown" and "tổng estimate 4000" in facts["plan.ngan-sach-token"][0]
    src = next(it for it in b["self_check"] if it["id"] == "plan.ngan-sach-token")["sources"][0]
    assert src["ref"] == "audit-log" and src["key"] == "plan.proposed" and len(src["event_ids"]) == 1


def test_release_uoc_luong_unknown_khi_khong_con_ticket_nao(tmp_path):
    """`tids` của release còn đó nhưng ticket đã bị xoá khỏi `lead.tickets` (dọn dữ liệu/lỗi đồng bộ) →
    `rel_tickets` rỗng, mục ước lượng phải `unknown` ngay, không tính min/median/max trên danh sách rỗng."""
    _db, _, orch = _scenario(tmp_path, to="release")
    del orch.lead.tickets["T1"]
    b = GB.build(orch, "REL-001")
    it = next(x for x in b["self_check"] if x["id"] == "plan.uoc-luong-co-so")
    assert it["verdict"] == "unknown" and it["facts"][0] == "0/0 ticket có estimate_tokens"


def test_release_gap_khi_budget_vuot_tran_agent_hoac_duoi_estimate(tmp_path):
    def h(system, user):
        out = rich_handler(system, user)
        if _agent_of(system) == "product" and "items" in out:
            out["items"] = [{**out["items"][0], "budget_tokens": 10_000_000}, {**out["items"][1]}]
        return out
    db, _, _ = _scenario(tmp_path, h, to="release")
    b = GB.build(GB.load_state(db), "REL-001")
    it = next(x for x in b["self_check"] if x["id"] == "plan.ngan-sach-token")
    assert it["verdict"] == "gap" and any("vượt budget_tokens_per_task" in f for f in it["facts"])


def test_release_uoc_luong_ok_khi_co_bai_hoc_cho_moi_assignee(tmp_path):
    db, _, orch = _scenario(tmp_path)  # đã nghiệm thu? chưa — nghiệm thu là của khách
    _pub(orch.bus, "acceptance-results", "REL-001", "ops",
         {"release_id": "REL-001", "project_id": "P1", "verdict": "accepted", "signed_by": "customer:po"})
    orch.run()
    assert orch.supervisor.lessons(), "sau nghiệm thu có bài học estimate-vs-actual"
    b = GB.build(GB.load_state(db), "REL-001", closed=True)
    it = next(x for x in b["self_check"] if x["id"] == "plan.uoc-luong-co-so")
    assert it["verdict"] == "ok" and any("builder×" in f for f in it["facts"])


def test_release_uoc_luong_unknown_khi_thieu_hieu_chinh_cho_assignee(tmp_path, monkeypatch):
    """Có bài học rồi (không rơi vào nhánh "dự án đầu") nhưng assignee của ticket này chưa có hiệu chỉnh
    riêng (agent mới, hoặc bài học chỉ tích luỹ cho agent khác) → vẫn `unknown`, không tự nhận `ok`."""
    _db, _, orch = _scenario(tmp_path)
    _pub(orch.bus, "acceptance-results", "REL-001", "ops",
         {"release_id": "REL-001", "project_id": "P1", "verdict": "accepted", "signed_by": "customer:po"})
    orch.run()
    assert orch.supervisor.lessons()
    monkeypatch.setattr(orch.supervisor, "calibration", lambda: {})
    b = GB.build(orch, "REL-001", closed=True)
    it = next(x for x in b["self_check"] if x["id"] == "plan.uoc-luong-co-so")
    assert it["verdict"] == "unknown" and any("chưa có hiệu chỉnh" in f for f in it["facts"])


# ---------- release ----------

def test_release_khai_bao_tien_trinh_co_giao_hang_duoc_khong(tmp_path):
    """Sự cố 2026-09-10: gate release được ký, khách nghiệm thu, mà tag/nhánh release không bao giờ tới repo
    khách vì tiến trình chạy thiếu `--deliver`. Gate release ký TRƯỚC khi giao, nên thứ kiểm được ở đây là
    *có giao được không*, đọc từ trạng thái tiến trình thật — không phải lời khai của agent."""
    db, _, orch = _scenario(tmp_path, to="release")

    orch.deliver, orch.push_remote = False, None
    it = next(x for x in GB.build(GB.load_state(db), "REL-001")["self_check"]
              if x["id"] == "release.giao-hang-duoc")
    assert it["verdict"] == "gap"
    assert any("--deliver" in f for f in it["facts"])

    orch.deliver, orch.push_remote = True, "origin"
    st = GB.load_state(db)
    st.deliver, st.push_remote = True, "origin"
    it = next(x for x in GB.build(st, "REL-001")["self_check"] if x["id"] == "release.giao-hang-duoc")
    assert it["verdict"] == "ok" and any("origin" in f for f in it["facts"])


def test_release_dashboard_doi_chieu_contract_voi_infra(tmp_path):
    db, _, orch = _scenario(tmp_path, to="release")
    b = GB.build(GB.load_state(db), "REL-001")
    it = next(x for x in b["self_check"] if x["id"] == "release.dashboard-alert")
    assert it["verdict"] == "unknown" and "chưa có namespace infra" in it["facts"][0]
    orch.blackboard.write("builder", "infra", "infra/dash.md", content="Dashboard + alert cho /orders, runbook ở docs/", project_id="P1")
    b = GB.build(GB.load_state(db), "REL-001")
    it = next(x for x in b["self_check"] if x["id"] == "release.dashboard-alert")
    assert it["verdict"] == "gap" and any("/payments" in f for f in it["facts"])
    orch.blackboard.write("builder", "infra", "infra/dash.md", content="Dashboard + alert cho /orders và /payments", project_id="P1")
    b = GB.build(GB.load_state(db), "REL-001")
    assert _verdicts(b)["release.dashboard-alert"] == "ok" and _verdicts(b)["release.four-eyes"] == "ok"
    assert {u["id"] for u in b["unavailable"]} == {"release.changelog-docs-notice", "release.error-budget"}
    assert b["extra"]["version"] == "0.1.1" and b["extra"]["tickets"] == ["T1"]
    assert {r["source"] for r in b["extra"]["staging_reviews"]} == {"qa"}
    _check_golden("release", b)


def test_release_voi_repo_doc_diff_nhanh_tich_hop(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    db, _, orch = _scenario(tmp_path, to="release", repo=repo)
    assert "REL-001" in orch.gate.pending
    b = GB.build(GB.load_state(db, repo=repo), "REL-001")
    it = next(x for x in b["self_check"] if x["id"] == "release.changelog-docs-notice")
    assert it["verdict"] == "gap" and "CHANGELOG: không" in it["facts"][1] and it["sources"][0]["kind"] == "worktree"
    assert {u["id"] for u in b["unavailable"]} == {"release.error-budget"}
    assert "file đổi trên company/integration" in it["facts"][0]



def test_release_nhan_ra_docs_ten_tieng_viet(tmp_path):
    """`core.quotepath` mặc định: `docs/hướng-dẫn.md` ra `"docs/h\\341\\273\\260..."` — mở đầu bằng ngoặc kép nên
    `startswith("docs/")` sai, hồ sơ nói "docs/: không" cho một release CÓ tài liệu. Người ký đọc đúng bằng chứng
    hồ sơ đưa, nhưng bằng chứng đó sai. Đo hai chiều: bỏ `core.quotepath=false` khỏi `gate_brief._git` thì đỏ."""
    import subprocess
    repo = _init_repo(tmp_path / "repo")
    db, _, orch = _scenario(tmp_path, to="release", repo=repo)
    integ = orch.integration_for("P1"); integ.ensure()
    (integ.path / "docs").mkdir(exist_ok=True)
    (integ.path / "docs" / "hướng-dẫn.md").write_text("# Hướng dẫn\n", encoding="utf-8")
    for cmd in (["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "docs"]):
        subprocess.run(["git", "-C", str(integ.path), *cmd], check=True, capture_output=True)
    b = GB.build(GB.load_state(db, repo=repo), "REL-001")
    it = next(x for x in b["self_check"] if x["id"] == "release.changelog-docs-notice")
    assert "docs/: có" in it["facts"][1], it["facts"]

def test_endpoints_va_section():
    assert GB._endpoints(CONTRACT) == ["/orders", "/payments"]
    assert GB._endpoints("GET /a\nPOST /b\n/: x\n") == ["/a", "/b"]
    assert GB._section("# A\n## NFR\nx\n## Khác\ny\n", GB._NFR_HEAD) == "\nx\n"
    assert GB._section("# A\n## Khác\ny\n", GB._NFR_HEAD) is None


# ---------- acceptance ----------

def test_acceptance_pr_giao_hang_doc_tu_delivery_done(tmp_path):
    """ADR-0038: mục `acceptance.pr-giao-hang` lấy từ `delivery.done.pr` (bằng chứng máy ghi), không từ lời khai:
    chưa giao/chưa bật → unknown; có url → ok kèm số PR; skipped/error → gap kèm lý do."""
    db, _bus, orch = _scenario(tmp_path)
    it = next(x for x in GB.build(GB.load_state(db), "UAT-REL-001")["self_check"] if x["id"] == "acceptance.pr-giao-hang")
    assert it["verdict"] == "unknown" and "--deliver-pr" in it["facts"][0]
    orch._audit("delivery.done", {"release_id": "REL-001", "version": "0.1.1", "tag": "v0.1.1", "sha": "a" * 40,
                                  "pr": {"url": "https://github.com/acme/app/pull/7", "number": 7, "created": True,
                                         "slug": "acme/app", "base": "main", "head": "company/release"}}, project_id="P1")
    it = next(x for x in GB.build(GB.load_state(db), "UAT-REL-001")["self_check"] if x["id"] == "acceptance.pr-giao-hang")
    assert it["verdict"] == "ok" and "PR #7" in it["facts"][0] and "main ← company/release" in it["facts"][0] and "mới mở" in it["facts"][0]
    assert it["sources"][0]["url"].endswith("/pull/7")
    orch._audit("delivery.done", {"release_id": "REL-001", "version": "0.1.1", "tag": "v0.1.1", "sha": "a" * 40,
                                  "pr": {"skipped": "cần --push-remote: PR chỉ mở được trên nhánh đã push"}}, project_id="P1")
    it = next(x for x in GB.build(GB.load_state(db), "UAT-REL-001")["self_check"] if x["id"] == "acceptance.pr-giao-hang")
    assert it["verdict"] == "gap" and "cần --push-remote" in it["facts"][0]
    orch._audit("delivery.done", {"release_id": "REL-001", "version": "0.1.1", "tag": "v0.1.1", "sha": "a" * 40,
                                  "pr": {"url": "u", "number": 3, "created": False, "slug": "s", "base": "main", "head": "h"}}, project_id="P1")
    it = next(x for x in GB.build(GB.load_state(db), "UAT-REL-001")["self_check"] if x["id"] == "acceptance.pr-giao-hang")
    assert "dùng lại" in it["facts"][0]


def test_acceptance_moi_truong_va_truy_vet(tmp_path):
    db, bus, orch = _scenario(tmp_path)
    b = GB.build(GB.load_state(db), "UAT-REL-001")
    v = _verdicts(b)
    assert v["acceptance.moi-truong"] == "ok" and v["acceptance.truy-vet"] == "unknown"
    _check_golden("acceptance", b)
    orch.blackboard.write("ops", "contract", "sow.md", content="UAT chạy trên production với dữ liệu ẩn danh", project_id="P1")
    _pub(bus, "acceptance-results", "REL-001", "ops",
         {"release_id": "REL-001", "project_id": "P1", "verdict": "conditional", "signed_by": "customer:po",
          "findings": [{"level": "warn", "text": "thiếu trang tin", "location": None},
                       {"level": "nit", "text": "REQ-9 sai màu", "location": "REQ-9"}]})
    orch.run()
    b = GB.build(GB.load_state(db), "UAT-REL-001", closed=True)
    it = next(x for x in b["self_check"] if x["id"] == "acceptance.truy-vet")
    assert it["verdict"] == "gap" and any("1 không truy vết" in f for f in it["facts"]) and any("REQ-9" in f for f in it["facts"])
    assert any("contract: 1 dòng" in f for f in next(x for x in b["self_check"] if x["id"] == "acceptance.moi-truong")["facts"])


def test_acceptance_gap_khi_chua_len_production(tmp_path):
    db, _, orch = _scenario(tmp_path, to="release")
    # gate nghiệm thu chưa mở (chưa production): dựng thử hồ sơ giả định qua build với --closed không có → NotPending
    with pytest.raises(GB.NotPending):
        GB.build(GB.load_state(db), "UAT-REL-001")
    # ép một gate acceptance khi release mới ở staging (người mở tay) → mục môi trường là gap
    from company.gates import GateRequest
    orch.gate.request(GateRequest(kind="acceptance", subject_id="UAT-REL-001", created_by="ops", checklist=["uat-script"]))
    b = GB.build(GB.load_state(db), "UAT-REL-001")
    assert _verdicts(b)["acceptance.moi-truong"] == "gap"


def test_acceptance_moi_truong_chua_co_release_events_nao(tmp_path, monkeypatch):
    """`_brief_acceptance` đọc `release-events` theo `rid` suy từ subject: rid chưa từng có sự kiện nào (khác
    trường hợp "chưa lên production" — ở đây chưa lên MÔI TRƯỜNG nào) → nói thẳng "chưa có release-events",
    nhánh `last is None` chưa test tới ở bất kỳ test nào khác (mọi kịch bản khác đều đã qua staging)."""
    _db, bus, orch = _scenario(tmp_path)
    orig_replay = bus.replay
    monkeypatch.setattr(bus, "replay", lambda *a, **kw:
                         iter(()) if kw.get("topic") == "release-events" else orig_replay(*a, **kw))
    b = GB.build(orch, "UAT-REL-001", closed=True)
    it = next(x for x in b["self_check"] if x["id"] == "acceptance.moi-truong")
    assert "chưa có release-events cho release này" in it["facts"]


def test_acceptance_unknown_khi_contract_noi_staging_va_moi_o_staging(tmp_path, monkeypatch):
    """Contract có nhắc "staging" (đúng ý định UAT chạy trên staging) nhưng release-event mới nhất chỉ mới tới
    staging (chưa production) → verdict `unknown` (chờ lên production hay UAT thật chạy trên staging), khác
    `gap` (không nhắc "staging" ở contract) đã test ở case trên. Pipeline giả (FakeClient) đi thẳng một lượt từ
    plan tới production nên không có mốc "đã có contract nhưng còn ở staging" tự nhiên — giả lập bằng cách lọc
    bớt release-event production khỏi thứ `_brief_acceptance` nhìn thấy, contract thật vẫn đọc từ blackboard."""
    _db, bus, orch = _scenario(tmp_path)   # tới acceptance: contract đã có, đã lên production
    orch.blackboard.write("ops", "contract", "openapi.yaml",
                          content=CONTRACT + "# UAT chạy trên staging\n", project_id="P1")
    orig_replay = bus.replay
    def only_staging(*a, **kw):
        if kw.get("topic") == "release-events":
            return iter([e for e in orig_replay(*a, **kw) if e.payload.get("env") == "staging"])
        return orig_replay(*a, **kw)
    monkeypatch.setattr(bus, "replay", only_staging)
    b = GB.build(orch, "UAT-REL-001", closed=True)
    assert _verdicts(b)["acceptance.moi-truong"] == "unknown"


# ---------- acceptance tự chạy sản phẩm (B4, ADR-0029) ----------

SERVER_OK = "import http.server,sys;http.server.test(http.server.SimpleHTTPRequestHandler,port=int(sys.argv[1]),bind='127.0.0.1')"
SERVER_DIE = "import sys;sys.stderr.write('config thiếu DATABASE_URL\\n');sys.exit(3)"


def _runtime_handler(system, user):
    """`product` pha `spec` khai `runtime` là một http.server thật (fake runtime, không cần file trong repo)."""
    out = rich_handler(system, user)
    if _agent_of(system) == "product" and "payload" in out:
        out["payload"]["runtime"] = {"command": ["python", "-c", SERVER_OK, "{port}"], "health": "/", "timeout_s": 20}
    return out


def _smoke_item(b: dict) -> dict:
    return next(x for x in b["self_check"] if x["id"] == "acceptance.da-chay")


def test_acceptance_tu_chay_san_pham_co_ma_http_that(tmp_path):
    """Có `runtime` + `--repo`: hồ sơ khởi động sản phẩm trong worktree tích hợp, mục "Đã chạy" mang mã HTTP 200 thật,
    `verified_by=orchestrator`; verdict `moi-truong` lấy từ máy chứ không từ lời khai `deployed`."""
    repo = _init_repo(tmp_path / "repo")
    db, _bus, _orch = _scenario(tmp_path, _runtime_handler, repo=repo)
    b = GB.build(GB.load_state(db, repo=repo), "UAT-REL-001")
    it = _smoke_item(b); sm = b["extra"]["smoke"]
    assert it["verdict"] == "ok" and sm["ok"] is True and sm["http_status"] == 200 and sm["verified_by"] == "orchestrator"
    assert sm["cwd"].endswith("_integration") and sm["release_id"] == "REL-001" and sm["ref"]
    assert any("mã HTTP: 200" in f for f in it["facts"]) and it["sources"][0]["kind"] == "smoke"
    assert _verdicts(b)["acceptance.moi-truong"] == "ok" and not b["unavailable"]
    md = GB.render_md(b)
    assert "## Đã chạy" in md and "mã HTTP: 200" in md and "verified_by=orchestrator" in md and "kết luận máy: ok" in md


def test_acceptance_khong_co_runtime_thi_noi_khong_the_chay(tmp_path, monkeypatch):
    """Không `runtime` → mục nói thẳng "không thể chạy" (unknown + unavailable), không im lặng; hồ sơ vẫn sinh."""
    db, _, _ = _scenario(tmp_path)
    b = GB.build(GB.load_state(db), "UAT-REL-001")
    it = _smoke_item(b)
    assert it["verdict"] == "unknown" and any("không thể chạy" in f.lower() for f in it["facts"])
    assert [u["id"] for u in b["unavailable"]] == ["acceptance.da-chay"] and "runtime" in b["unavailable"][0]["reason"]
    assert "KHÔNG THỂ CHẠY" in GB.render_md(b) and "chạy cho tôi xem" in GB.render_md(b)
    # có runtime nhưng không có --repo: cũng nói rõ, lý do là thiếu worktree
    from company.smoke import Runtime
    monkeypatch.setattr(GB, "parse_runtime", lambda _p: Runtime(("python", "-c", "x")))
    b = GB.build(GB.load_state(db), "UAT-REL-001")
    assert "worktree" in _smoke_item(b)["facts"][0] and _smoke_item(b)["verdict"] == "unknown"


def test_acceptance_smoke_fail_van_ra_ho_so_va_verdict_gap(tmp_path, monkeypatch):
    """Sản phẩm chết lúc khởi động → hồ sơ vẫn sinh, mục `da-chay` gap với mã thoát + stderr, và `moi-truong` KHÔNG còn
    `ok` dù release-events khai production deployed — chiều đo quan trọng nhất."""
    repo = _init_repo(tmp_path / "repo")
    db, _, _ = _scenario(tmp_path, _runtime_handler, repo=repo)
    from company.smoke import Runtime
    monkeypatch.setattr(GB, "parse_runtime", lambda _p: Runtime(("python", "-c", SERVER_DIE), timeout_s=10))
    b = GB.build(GB.load_state(db, repo=repo), "UAT-REL-001")
    it = _smoke_item(b); sm = b["extra"]["smoke"]
    assert it["verdict"] == "gap" and sm["ok"] is False and sm["exit_code"] == 3 and sm["http_status"] is None
    assert any("DATABASE_URL" in f for f in it["facts"])
    assert _verdicts(b)["acceptance.moi-truong"] == "gap", "lời khai deployed không được che sản phẩm không chạy"
    md = GB.render_md(b)
    assert "KHÔNG ĐẠT" in md and "mã thoát: 3" in md


# ---------- escalation (§5.6) ----------

def test_escalation_gom_hint_cu_va_lich_su(tmp_path):
    db, _bus, orch = _scenario(tmp_path, fail_handler, to="escalation")
    assert orch.gate.pending["T1"].kind == "escalation" and orch.lead.state["T1"] == "blocked"
    b = GB.build(GB.load_state(db), "T1")
    assert b["kind"] == "escalation" and b["project_id"] == "P1" and b["extra"]["scope"] == "ticket"
    assert b["extra"]["hints_used"] == [] and b["extra"]["ticket"]["retry"] == 2
    acts = [h["action"] for h in b["extra"]["history"]]
    assert acts.count("tasks retry=0") == 1 and "tasks retry=2" in acts and any("invalid_output" in a for a in acts)
    assert any("ticket.blocked" in a for a in acts), "lead chặn ticket: dấu vết bền phải có trong lịch sử"
    ns = next(x for x in b["self_check"] if x["id"] == "escalation.ngan-sach")
    assert ns["verdict"] == "ok" and "đầu ra" in ns["facts"][0] and b["extra"]["budget"]["state"] == "blocked"
    assert b["extra"]["diagnose"]["blocked"] == 1
    assert {u["id"] for u in b["unavailable"]} == {"escalation.worktree"}
    _check_golden("escalation", b)

    # người mở lại hai lần với CÙNG một hint → hồ sơ liệt kê cả hai và nêu hint lặp
    orch.gate.decide("T1", "approve", by="human:lead", reason="thử lại"); orch.run()
    assert orch.lead.state["T1"] == "blocked" and "T1" in orch.gate.pending
    orch.gate.decide("T1", "approve", by="human:lead", reason="thử lại"); orch.run()
    b2 = GB.build(GB.load_state(db), "T1")
    hints = b2["extra"]["hints_used"]
    assert [h["reason"] for h in hints] == ["thử lại", "thử lại"] and b2["extra"]["duplicate_hints"] == ["thử lại"]
    md = GB.render_md(b2)
    assert "hint lặp lại y hệt: thử lại" in md and "## Lịch sử thất bại" in md and "không phải khuyến nghị" in md
    assert "gate_cli" not in md.split("## Nửa của người")[1], "phần hồ sơ không nhắc lệnh ký"


def test_escalation_voi_repo_thay_worktree(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    db, _, orch = _scenario(tmp_path, fail_handler, to="escalation", repo=repo)
    assert orch.lead.state["T1"] == "blocked"
    b = GB.build(GB.load_state(db, repo=repo), "T1")
    assert b["extra"]["worktree"]["branch"] == "ticket/T1" and b["extra"]["worktree"]["path"].endswith("T1")
    assert "escalation.worktree" not in {u["id"] for u in b["unavailable"]}
    assert "## Worktree" in GB.render_md(b)


def test_escalation_cap_du_an(tmp_path):
    db, _, orch = _scenario(tmp_path, stall_handler, to="stalled")
    assert orch.gate.pending["P1"].kind == "escalation" and "P1" in orch.stalled
    b = GB.build(GB.load_state(db), "P1")
    assert b["extra"]["scope"] == "project" and b["extra"]["stalled"]["agent"] == "product" and b["project_id"] == "P1"
    assert any("project.stalled" in h["action"] for h in b["extra"]["history"])
    ns = b["self_check"][0]
    assert ns["id"] == "escalation.ngan-sach" and ns["verdict"] == "unknown" and "chưa đặt" in ns["facts"][0]
    assert "## Dự án kẹt" in GB.render_md(b)


def test_escalation_ngan_sach_gap_khi_can(tmp_path):
    _db, _, orch = _scenario(tmp_path, fail_handler, to="escalation")
    orch.supervisor.budgets["T1"].output_used = orch.supervisor.budgets["T1"].limit + 1
    b = GB.build(orch, "T1")  # cùng orchestrator (trạng thái sửa tay) — build không phụ thuộc DB
    assert _verdicts(b)["escalation.ngan-sach"] == "gap"


# ---------- CLI ----------

def test_cli_all_json_va_out(tmp_path, capsys):
    db, _, _ = _scenario(tmp_path)
    assert GB.main(["--all", "--db", str(db), "--format", "json", "--no-write"]) == 0
    out = capsys.readouterr().out
    assert out.count('"schema_version": 1') == 2 and '"kind": "release"' in out and '"kind": "acceptance"' in out
    assert GB.main(["REL-002", "--db", str(db)]) == 0
    default = GB.artifact_store(db) / "P1" / "gate-brief"
    assert (default / "REL-002.json").exists() and (default / "REL-002.md").exists()
    assert "hồ sơ bằng chứng, không phải khuyến nghị" in capsys.readouterr().out


def test_cli_all_khong_co_gate(tmp_path, capsys):
    db2 = tmp_path / "e.sqlite"; SQLiteBus(db2).close()
    assert GB.main(["--all", "--db", str(db2)]) == 0 and "không có gate chờ" in capsys.readouterr().out


def test_history_thu_tu_theo_bus_khi_trung_dau_thoi_gian(tmp_path):
    """Hai event ghi trong cùng một lượt có thể trùng `ts` tới micro giây. Khi ấy xếp lịch sử theo `ts` không phải
    thứ tự toàn phần: nó lật giữa hai cách sắp xếp tuỳ đồng hồ có nhích hay không (hồ sơ escalation từng chập chờn
    ~1/6 lần), và người đọc thấy `tasks retry=N` TRƯỚC lỗi gây ra nó. Thứ tự ghi vào bus mới là thứ tự nhân quả."""
    from datetime import UTC, datetime

    fixed = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    db, _bus, _orch = _scenario(tmp_path, fail_handler, to="escalation")
    st = GB.load_state(db)
    for e in st.bus.replay():          # mọi event CÙNG một ts → chỉ còn thứ tự bus phân biệt được
        e.ts = fixed
    b = GB.build(st, "T1")
    h = b["extra"]["history"]
    acts = [x["action"] for x in h]
    assert all(x["at"] == fixed.isoformat() for x in h), "phép thử vô nghĩa nếu ts không trùng"
    assert "_seq" not in h[0], "khoá phụ trợ không được lọt ra hồ sơ"
    assert acts[0] == "tasks retry=0", "event ghi sớm nhất phải đứng đầu dù trùng ts"
    inval = [i for i, a in enumerate(acts) if "invalid_output" in a]
    assert inval and inval[0] < acts.index("tasks retry=2"), "lỗi phải đứng TRƯỚC lần retry mà nó gây ra"
    assert acts[-1].endswith("ticket.blocked"), "event ghi muộn nhất phải đứng cuối"
