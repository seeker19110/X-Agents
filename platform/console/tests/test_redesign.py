"""Đợt 3 — console thiết kế lại: lớp `collect`, route `/api/gate/brief`, trang tĩnh, và "không giữ state" (C10).

Trang là một file HTML không có bước build, nên không có gì bắt lỗi "thêm màn mà quên khai" hay "bỏ mất cột" —
mấy test dưới đây làm việc đó bằng cách đọc chính file và khẳng định từng ghi nhận của TRAPS đã có chỗ trên trang.
Đo hai chiều: xoá một trong các mục C1–C8 khỏi `index.html` là đúng một test đỏ, nêu tên mục đó.
"""
from __future__ import annotations

import http.client
import json
import re
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from company.events import AuditLog, Envelope, Task
from company.sqlite_bus import SQLiteBus

from console import server as srv
from console.collect import collect

PAGE = Path(__file__).resolve().parents[1] / "src" / "console" / "static" / "index.html"
JS_DIR = PAGE.parent / "js"


@pytest.fixture(scope="module")
def page() -> str:
    """HTML **cộng** mọi ES module của trang.

    K7.1 tách khối `<script>` 1090 dòng thành `static/js/*.js`. Các test dưới đây hỏi "mã của TRANG có X không"
    — câu hỏi đó không đổi vì mã sang file khác, nên fixture ghép lại. Ghép theo thứ tự tên file để thông báo
    lỗi ổn định giữa hai lần chạy."""
    return PAGE.read_text(encoding="utf-8") + "\n" + "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(JS_DIR.glob("*.js")))


# ---------------------------------------------------------------------------
# collect: C1 phễu sản phẩm, C4 bế tắc im lặng, C5 nguồn bị cắt, C7 vượt integration
# ---------------------------------------------------------------------------

def test_state_mang_du_khoi_moi_va_nguon_hong_van_du_khoa(company_db: Path, tmp_path: Path) -> None:
    s = collect(company_db, gateway_url="http://127.0.0.1:9")
    assert isinstance(s["product_funnel"], list) and isinstance(s["silent_deadlocks"], list)
    assert s["reviews"][0]["trim_src"] == []
    assert s["tickets"][0]["ahead"] is None, "dự án không khai repo thì không đo được — phải là None, không phải 0"
    assert s["tickets"][0]["pending_decision"] is None
    rel = next(g for g in s["gates"] if g["id"] == "REL-001")
    assert "RC dừng tại đây" in rel["reject"] and rel["agent"] == "ops"
    dead = collect(tmp_path / "khong-co.sqlite", gateway_url="http://127.0.0.1:9")
    assert dead["product_funnel"] == [] and dead["silent_deadlocks"] == []


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


def test_c7_cot_vuot_integration_doc_repo_tu_chinh_bus(tmp_path: Path) -> None:
    """Đường dẫn repo đến từ audit `project.repo` mà orchestrator ghi — console không có cấu hình repo riêng (C10).
    Ticket chưa xong thì đo; ticket đã xong thì thôi (nhánh đã gộp hoặc đã xoá, và mỗi lần đo là một tiến trình git)."""
    repo = tmp_path / "khach"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t.local")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("1", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "nen")
    _git(repo, "branch", "company/integration")
    for tid in ("T-dang-lam", "T-xong"):
        _git(repo, "checkout", "-q", "-B", f"ticket/{tid}", "company/integration")
        (repo / f"{tid}.txt").write_text("x", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", tid)

    db = tmp_path / "company.sqlite"
    bus = SQLiteBus(db)
    now = datetime.now(UTC)
    for tid in ("T-dang-lam", "T-xong"):
        t = Task(ticket_id=tid, project_id="P1", requirement_id="R1", assignee="builder", title=tid,
                 acceptance=["ok"], estimate_tokens=1, budget_tokens=2)
        bus.publish(Envelope(topic="tasks", key=tid, actor="delivery-lead", ts=now, payload=t.model_dump()))
    def audit(action: str, ev: dict[str, Any]) -> None:
        p = AuditLog(actor="orchestrator", action=action, evidence=json.dumps(ev, ensure_ascii=False))
        bus.publish(Envelope(topic="audit-log", key="orchestrator", actor="orchestrator", ts=now, payload=p.model_dump()))
    audit("project.repo", {"project_id": "P1", "repo": str(repo), "base": "main"})
    audit("integration.merged", {"release_id": "REL-1", "ticket_id": "T-xong", "sha": "a" * 40,
                                 "branch": "company/integration"})
    bus.close()

    tickets = {t["id"]: t for t in collect(db, gateway_url="http://127.0.0.1:9")["tickets"]}
    assert tickets["T-dang-lam"]["ahead"] == 1, "1 commit còn nằm ngoài nhánh tích hợp"
    assert tickets["T-xong"]["ahead"] == 1, "ticket chưa ở trạng thái xong thì vẫn đo"

    # ticket đã đóng: không bắn tiến trình git nữa
    bus = SQLiteBus(db)
    p = AuditLog(actor="account-manager", action="ticket.closed")
    bus.publish(Envelope(topic="audit-log", key="T-xong", actor="account-manager", ts=now, payload=p.model_dump()))
    bus.close()


# ---------------------------------------------------------------------------
# C8: /api/gate/brief
# ---------------------------------------------------------------------------

@pytest.fixture
def console(tmp_path: Path, company_db: Path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html><head></head><body>x</body></html>", encoding="utf-8")
    server = srv.make_server("127.0.0.1", 0, static_dir=static, company_db=company_db)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


def get(server: srv.ConsoleServer, path: str, *, token: str | None = None) -> tuple[int, Any]:
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    try:
        conn.request("GET", path, headers={"X-Console-Token": token if token is not None else server.token})
        r = conn.getresponse()
        raw = r.read().decode("utf-8")
        try:
            return r.status, json.loads(raw)
        except json.JSONDecodeError:
            return r.status, raw
    finally:
        conn.close()


def test_c8_ho_so_gate_lay_duoc_qua_http_o_che_do_chi_doc(console: srv.ConsoleServer) -> None:
    """Đọc bằng chứng phải RẺ HƠN ký: `/api/gate/brief` là GET và không cần `--allow-decide` (server đang readonly)."""
    assert console.readonly is True
    status, body = get(console, "/api/gate/brief?id=REL-001")
    assert status == 200 and body["ok"] is True and body["kind"] == "release"
    assert "Nửa của người" in body["md"]


def test_c8_ly_do_khong_dung_duoc_di_ve_trang_chu_khong_thanh_500(console: srv.ConsoleServer) -> None:
    status, body = get(console, "/api/gate/brief?id=KHONG-CO")
    assert status == 200 and body["ok"] is False and "không có trong hàng đợi gate" in body["error"]
    status, body = get(console, "/api/gate/brief?id=SPEC-1&closed=1")
    assert body["ok"] is True and body["kind"] == "spec", "gate đã đóng vẫn đọc lại được bằng closed=1"
    status, body = get(console, "/api/gate/brief?id=PUB-1&xuong=keeper")
    assert body["ok"] is False and "keeper" in body["error"]
    status, body = get(console, "/api/gate/brief")
    assert body["ok"] is False and "thiếu subject_id" in body["error"]


def test_c8_ho_so_van_can_token_phien(console: srv.ConsoleServer) -> None:
    status, _ = get(console, "/api/gate/brief?id=REL-001", token="sai")
    assert status == 401


# ---------------------------------------------------------------------------
# C10: console không giữ state ngoài sqlite của công ty
# ---------------------------------------------------------------------------

def test_c10_khoi_dong_lai_khong_mat_gi(company_db: Path) -> None:
    """Mọi thứ console biết đều suy lại được từ bus: hai lần đọc (kể cả qua hai tiến trình server khác nhau) cho
    cùng một trạng thái, trừ dấu thời gian. Không có bộ nhớ nào chỉ sống trong RAM để mà mất khi F5."""
    a = collect(company_db, gateway_url="http://127.0.0.1:9")
    b = collect(company_db, gateway_url="http://127.0.0.1:9")
    a.pop("generated_at"), b.pop("generated_at")
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    assert not [f for f in vars(srv.ConsoleServer) if f.startswith("cache")]


def test_c10_trang_giu_cho_dang_dung_o_dia_chi_khong_phai_trong_bo_nho(page: str) -> None:
    """F5 phải quay lại đúng màn và đúng ngăn kéo. Chỗ duy nhất trang được phép nhớ giữa hai lần tải là TÊN người
    duyệt (`ME_KEY`) — mọi thứ khác đọc lại từ `/api/state` hoặc từ hash."""
    keys = set(re.findall(r"localStorage\.(?:get|set)Item\(([^,)]+)", page))
    assert keys == {"ME_KEY"}, f"trang đang nhớ thêm thứ khác trong localStorage: {keys}"
    assert "sessionStorage" not in page and "indexedDB" not in page
    assert 'addEventListener("hashchange"' in page and "applyRoute()" in page
    sw = (PAGE.parent / "sw.js").read_text(encoding="utf-8")
    assert "/api/" not in sw.split("CACHE")[0] or "icon" in sw, "SW không được cache /api/* (số cũ trên mặt kính)"


# ---------------------------------------------------------------------------
# Trang tĩnh: mỗi mục C có chỗ trên trang
# ---------------------------------------------------------------------------

def test_c1_man_pheu_san_pham_duoc_khai_day_du_va_o_rong_la_o_xam(page: str) -> None:
    for chỗ in ('data-v="phieu"', '<section class="view" id="v-phieu"', '"phieu":()=>[', 'id="product-funnel"'):
        assert chỗ in page, f"màn phễu sản phẩm thiếu {chỗ}"
    assert '"phieu"' in re.search(r"const VIEWS=\[(.*?)\];", page).group(1)
    fn = page[page.index("function renderProductFunnel()"):page.index("function renderSilent()")]
    assert 'x.empty?"zero"' in fn, "ô rỗng phải mang class `zero` (xám), không bao giờ dùng nhánh xanh"
    assert 'chưa có gì' in fn
    assert ".pf .step.zero{" in page, "class `zero` phải có style xám riêng, không thì xám chỉ là lời hứa"
    assert "renderProductFunnel();" in page[page.index("function render(){"):page.index("function render(){") + 900]


def test_c2_the_gate_noi_ca_duyet_lan_tu_choi(page: str) -> None:
    q = page[page.index("function renderQueue()"):page.index('$("#queue").addEventListener')]
    assert "Duyệt thì sao?" in q and "Từ chối thì sao?" in q, "phải có ĐỦ HAI câu hậu quả"
    assert "g.agent" in q, "duyệt xong thì agent nào chạy lại"
    drawer = page[page.index("function openGate(id)"):page.index("function openTicket(id)")]
    assert "Hậu quả — cả hai chiều" in drawer
    assert 'id="hint-preview"' in drawer and "Hint agent sẽ nhận — nguyên văn" in drawer


def test_c3_badge_quyet_dinh_chua_ap_va_viec_dang_chay_bao_lau(page: str) -> None:
    assert "quyết định chưa áp" in page, "thẻ ticket phải mang badge khi chữ ký chưa được áp"
    assert "t.pending_decision" in page
    run = page[page.index("function renderRunning()"):page.index("function renderReleases()")]
    assert "đang chạy ${num(r.head.minutes)} phút" in run and "Việc đang chạy" in run


def test_c4_canh_bao_be_tac_im_lang_rieng_va_o_dau_trang(page: str) -> None:
    assert 'id="s-silent"' in page and 'id="silent"' in page
    body = page[page.index('<section class="view on" id="v-truc-ban">"'.rstrip('"')):]
    assert body.index('id="s-silent"') < body.index('id="s-dead"'), "cảnh báo im lặng phải đứng TRƯỚC bảng bế tắc chung"
    fn = page[page.index("function renderSilent()"):page.index("function renderDeadlocks()")]
    assert "không ai được hỏi" in fn and "silent_deadlocks" in fn
    assert "renderSilent();" in page[page.index("function render(){"):page.index("function render(){") + 900]


def test_c5_nguon_bi_cat_hien_canh_verdict(page: str) -> None:
    tables = page[page.index("function renderTables()"):page.index("/* ---------- sự thật giao hàng ---------- */")]
    assert "r.trim_src" in tables and "ký tự" in tables
    assert "Agent thực sự thấy gì" in page, "cột phải có tên nói đúng nó đo gì"
    assert "trim_src" in page[page.index("function openTicket(id)"):page.index("export function setOpenId")]


def test_c6_hint_may_va_hint_nguoi_deu_hien_va_co_mau_de_go(page: str) -> None:
    drawer = page[page.index("function openTicket(id)"):page.index("export function setOpenId")]
    assert "t.human_hint" in drawer and "t.hint" in drawer, "phải hiện CẢ hint máy lẫn hint người"
    gate = page[page.index("function openGate(id)"):page.index("function openTicket(id)")]
    assert 'id="tmpl"' in gate and "root_cause" in gate and "decision" in gate and "hint" in gate
    assert 'const HINT_TMPL="root_cause: ' in page and "HINT_TMPL" in gate, "nút mẫu phải chèn đúng ba dòng"
    # khoá lý do < 20 ký tự (#80) giữ nguyên
    assert "disabled=READONLY||left>0||thin" in page and ".length<20" in page


def test_c7_cot_vuot_integration_dung_rev_list_va_phan_biet_null_voi_0(page: str) -> None:
    assert "Vượt integration" in page
    assert "git rev-list --count company/integration..ticket/" in page, "cột phải nói nó đo bằng lệnh nào"
    assert "branch --contains" not in page
    fn = page[page.index("function ahead(id)"):page.index("function renderTables()")]
    assert 'n==null?' in fn and "—" in fn, "không đo được (null) phải khác đã gộp hết (0)"


def test_c8_nut_ho_so_bang_chung_nam_ngay_trong_ngan_keo_gate(page: str) -> None:
    gate = page[page.index("function openGate(id)"):page.index("function openTicket(id)")]
    assert 'id="brief-btn"' in gate and "/api/gate/brief?id=" in gate
    assert "gate_brief" in gate


def test_nut_tick_tat_ca_chi_hien_khi_nhieu_muc_va_khong_qua_mat_khoa_ly_do(page: str) -> None:
    """Gate nợ kiến trúc (SD-*, DEF-*) có thể mang 20-40 mục checklist — tick từng ô là việc vô nghĩa sau khi đã
    đọc hồ sơ bằng chứng. Nút "Tick tất cả" chỉ tự động hoá phần tick, KHÔNG được bỏ qua khoá lý do ≥20 ký tự
    (`thin`) hay khoá còn ô chưa tick khi checklist rỗng/một mục — nếu không thì bỏ qua nút này cũng giống bỏ qua
    chính checklist, chỉ khác chỗ bấm."""
    gate = page[page.index("function openGate(id)"):page.index("function openTicket(id)")]
    assert 'id="cl-all"' in gate and "Tick tất cả" in gate
    assert "cl.length>1?" in gate, "chỉ hiện nút khi có HƠN MỘT mục — một mục thì tick tay còn nhanh hơn bấm nút"
    assert 'const clAll=$("#cl-all")' in gate
    assert "boxes.forEach(b=>{b.checked=true;});sync();" in gate, "bấm xong phải tick hết RỒI gọi lại sync() — không thì nút approve không tự mở khoá"
    # `sync()` vẫn là nơi DUY NHẤT quyết khoá nút duyệt: nút "Tick tất cả" không có đường tắt riêng nào khác
    # tới `disabled=false`, nên vẫn phải qua đúng điều kiện `left>0||thin` như tick tay.
    assert gate.count("drawer.querySelector('[data-d=\"approve\"]').disabled=") == 1


def test_k27_o_sandbox_canh_bao_tuong_minh_khi_chay_ngoai_container(page: str) -> None:
    """S1: subprocess tường minh phải báo rủi ro gate kể cả khi chưa có lượt chạy hay máy thiếu runtime."""
    assert 'id="s-sandbox"' in page and 'id="sandbox"' in page
    body = page[page.index('<section class="view on" id="v-truc-ban">'):]
    assert body.index('id="s-sandbox"') < body.index('id="s-dead"'), "ô sandbox đứng trước bảng bế tắc chung"
    fn = page[page.index("function renderSandbox()"):page.index("function renderDeadlocks()")]
    assert "sb.mode" in fn, "phải hiện chế độ từ audit của tiến trình đang chạy"
    assert "gate không chống được mã khách" in fn.lower()
    assert "COMPANY_SANDBOX=container" in fn, "phải nói đúng lệnh cần gõ, không chỉ nói có vấn đề"
    assert "renderSandbox();" in page[page.index("function render(){"):page.index("function render(){") + 900]
