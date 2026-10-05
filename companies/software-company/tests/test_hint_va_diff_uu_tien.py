"""Hai thứ quan trọng nhất phải đến được nơi cần đến:

1. `Task.human_hint` — chẩn đoán của NGƯỜI không bị thông điệp máy ghi đè ở lượt retry sau. Đo được 2026-09-06
   (QLKH-012): hint chi tiết của người sống đúng MỘT lượt, lượt sau bị thay bằng "lần trước lỗi: backend: không sửa
   file nào…", hai lượt còn lại agent mò trong bóng tối.
2. `TicketWorkspace.diff` — mã nguồn đứng TRƯỚC file sinh tự động, và nói rõ file nào bị cắt. Đo được cùng ngày:
   QLKH-012 sinh lại `api/QLKH/openapi.yaml` 804 dòng, `git diff` xếp theo đường dẫn nên nó ăn hết hạn mức và đẩy
   `qlkh/application/erasure_*.py` ra ngoài; security kết luận "thiếu diff erasure_*.py" và chặn ticket oan.
"""
from __future__ import annotations

from company.bus import InMemoryBus
from company.delivery import DeliveryLead
from company.events import Envelope, PullRequest, ReviewResult, Task
from company.gate_cli import PersistentGate
from company.orch.routes import REVIEW_AGENT
from company.workspace import Integration, TicketWorkspace, is_generated
from test_tools_and_agentic import _init_repo


def _lead():
    bus = InMemoryBus(); gate = PersistentGate(bus); lead = DeliveryLead(bus, gate)
    lead.plans_ok.add("PLAN")   # ADR-0037: không còn gate plan
    return bus, lead


def _task(tid="T1", **kw):
    return Task(ticket_id=tid, project_id="P", requirement_id="R1", assignee="builder", title=tid,
                acceptance=["a"], **kw)


def test_hint_cua_nguoi_khong_bi_thong_diep_may_ghi_de(tmp_path):
    bus, lead = _lead()
    lead.dispatch(_task(), "PLAN")
    lead.human_hint("T1", "ĐỪNG sinh lại openapi.yaml; giữ code erasure đã viết")
    assert lead.tickets["T1"].human_hint == "ĐỪNG sinh lại openapi.yaml; giữ code erasure đã viết"

    lead.rework("T1", "lint fail: ruff E501")  # máy trả về vì lint đỏ → ghi `hint`, KHÔNG đụng `human_hint`
    t = lead.tickets["T1"]
    assert t.hint == "lint fail: ruff E501", "thông điệp máy vẫn vào `hint` như cũ"
    assert t.human_hint == "ĐỪNG sinh lại openapi.yaml; giữ code erasure đã viết", "chẩn đoán của người phải còn"

    tasks = [e.payload for e in bus.replay(topic="tasks") if e.key == "T1"]
    assert tasks[-1]["human_hint"] == t.human_hint, "và phải đi theo task tới agent"


def test_reopen_sau_escalation_cung_giu_hint_cua_nguoi(tmp_path):
    _bus, lead = _lead()
    lead.dispatch(_task(tid="T2"), "PLAN")
    lead.state["T2"] = "blocked"
    lead.reopen("T2", "code đã đúng, chỉ sửa tối thiểu openapi.yaml")
    assert lead.tickets["T2"].human_hint == "code đã đúng, chỉ sửa tối thiểu openapi.yaml"
    lead.rework("T2", "test fail")
    assert lead.tickets["T2"].human_hint == "code đã đúng, chỉ sửa tối thiểu openapi.yaml"
    assert lead.tickets["T2"].hint == "test fail"


def test_diff_dat_ma_nguon_truoc_file_sinh_tu_dong_va_noi_ro_cho_bi_cat(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    ws = TicketWorkspace(repo, "T1", base="main"); ws.create()
    # `api/...` xếp trước `qlkh/...` theo đường dẫn — đúng thứ tự đã hại QLKH-012
    (ws.path / "api").mkdir(exist_ok=True)
    (ws.path / "api" / "openapi.yaml").write_text("openapi: 3.1.0\n" + "".join(f"  line{i}: x\n" for i in range(400)),
                                                  encoding="utf-8")
    (ws.path / "qlkh").mkdir(exist_ok=True)
    (ws.path / "qlkh" / "erasure_service.py").write_text("def erase():\n    return 'that su quan trong'\n",
                                                         encoding="utf-8")
    ws.commit_all("feat(T1): erasure + contract")

    d = ws.diff(max_chars=900)   # hạn mức nhỏ: chỉ đủ cho MỘT file
    assert "erasure_service.py" in d and "that su quan trong" in d, "mã nguồn phải sống sót khi cắt"
    assert "KHÔNG có diff của" in d and "openapi.yaml" in d, "phải nói rõ file nào bị bỏ, không im lặng"

    full = ws.diff(max_chars=100_000)
    assert "erasure_service.py" in full and "openapi.yaml" in full and "KHÔNG có diff của" not in full


def test_diff_rong_va_file_khong_co_thay_doi(tmp_path):
    """Hai đường biên: worktree sạch → chuỗi rỗng; file có tên trong `--name-only` nhưng `git diff -- <file>` rỗng
    (đổi quyền/mode) → bỏ qua, không chèn khối rỗng vào diff."""
    repo = _init_repo(tmp_path / "repo")
    ws = TicketWorkspace(repo, "T9", base="main"); ws.create()
    assert ws.diff() == "", "worktree chưa có gì thì diff rỗng, không phải chuỗi rác"

    (ws.path / "m.py").write_text("x = 1\n", encoding="utf-8"); ws.commit_all("feat(T9): m")
    real = ws.diff()
    assert "m.py" in real

    import company.workspace as W
    that = W._git

    def gia(path, *a, **k):
        if "--name-only" in a:
            return "m.py\nkhong-ton-tai.py"          # git kể tên file...
        if "khong-ton-tai.py" in a:
            return ""                                # ...nhưng diff của nó rỗng (đổi mode chẳng hạn)
        return that(path, *a, **k)

    W._git = gia
    try:
        d = ws.diff()
    finally:
        W._git = that
    assert "khong-ton-tai" not in d, "file không có nội dung diff thì bỏ qua, không ghi khối rỗng"


def test_nhan_dien_file_sinh_tu_dong():
    assert is_generated("api/QLKH/openapi.yaml") and is_generated("requirements.lock")
    assert is_generated("web/package-lock.json") and is_generated("THIRD-PARTY.md")
    assert not is_generated("qlkh/application/erasure_service.py") and not is_generated("tests/test_x.py")


def test_review_van_chay_binh_thuong_voi_task_co_human_hint(tmp_path):
    """Chốt chặn: thêm trường mới không phá vòng review (schema `tasks` cho phép trường phụ)."""
    bus, lead = _lead()
    lead.dispatch(_task(tid="T3"), "PLAN")
    lead.human_hint("T3", "gợi ý của người")
    bus.publish(Envelope(topic="pull-requests", key="T3", actor="builder",
                         payload=PullRequest(ticket_id="T3", branch="b", pr_ref="#1",
                                             local_checks={"lint": True}).model_dump()))
    for src in ("reviewer", "qa"):   # hai NHÃN chấm, cùng một agent phát (ADR-0037)
        bus.publish(Envelope(topic="review-results", key="T3", actor=REVIEW_AGENT[src],
                             payload=ReviewResult(ticket_id="T3", source=src, verdict="pass").model_dump()))
    assert lead.state["T3"] == "approved"


def test_ten_file_tieng_viet_khong_bi_bo_khoi_diff_va_danh_sach_file(tmp_path):
    """`core.quotepath` mặc định bật: `--name-only`/`ls-tree` in tên non-ASCII thành `"qlkh/kh\\303\\241ch.py"` (có
    ngoặc kép, byte escape bát phân). Tên đó không phải đường dẫn thật: `git diff -- "<tên escape>"` rỗng nên `diff()`
    bỏ qua file IM LẶNG — reviewer không thấy code, cũng không thấy dòng "KHÔNG có diff của". Đo hai chiều: bỏ
    `core.quotepath=false` khỏi `_git` thì cả ba assert dưới đỏ."""
    repo = _init_repo(tmp_path / "repo")
    ws = TicketWorkspace(repo, "T7", base="main"); ws.create()
    (ws.path / "qlkh").mkdir(exist_ok=True)
    (ws.path / "qlkh" / "khách_hàng.py").write_text("def xoa():\n    return 'ma that'\n", encoding="utf-8")
    ws.commit_all("feat(T7): khách hàng")

    assert "qlkh/khách_hàng.py" in ws.changed_files()
    assert "ma that" in ws.diff(), "file tên tiếng Việt phải có mặt trong diff gửi reviewer"
    integ = Integration(repo, base="main")
    assert integ.merge(ws.branch, "merge T7").ok
    assert "qlkh/khách_hàng.py" in integ.files(), "danh sách file của nhánh tích hợp cũng phải là đường dẫn thật"
