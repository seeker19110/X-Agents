"""K7.1/K7.2 kịch bản B — trang tĩnh tách thành ES module, và bootstrap inline có nonce + CSP.

Trang là một file HTML **không có bước build**, nên không có gì bắt lỗi "tách module mà quên nhập một file".
Sai kiểu đó im lặng: trình duyệt nạp `main.js`, không có lỗi cú pháp, chỉ là một mảng tương tác không bao giờ
được gắn sự kiện — người dùng bấm nút mà không có gì xảy ra.
"""
from __future__ import annotations

import io
import re
from http import HTTPStatus
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "console" / "static"
JS_DIR = STATIC / "js"
MAX_DONG_MODULE = 400


@pytest.fixture(scope="module")
def html() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def modules() -> dict[str, str]:
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(JS_DIR.glob("*.js"))}


def test_k71_index_chi_con_html_css_va_mot_the_module(html: str) -> None:
    """`index.html` 1850 → 759 dòng. Khối `<script>` inline duy nhất còn lại là bootstrap do SERVER chèn lúc
    chạy (K7.2), không nằm trong file."""
    assert '<script type="module" src="/static/js/main.js"></script>' in html
    assert not re.search(r"<script>\s*\n", html), "không còn khối <script> inline trong file tĩnh"
    assert "cdn" not in html.lower() or "fonts.googleapis.com" in html, "không CDN (trừ Google Fonts đã có từ trước)"


def test_k71_du_module_va_khong_module_nao_qua_dai(modules: dict[str, str]) -> None:
    """≥ 7 file, không file nào > 400 dòng — cùng ngưỡng với `orch/` của software-company (K1.8): mục tiêu là
    chia nhỏ, một module phình lại thành `index.html` thứ hai là dấu hiệu cần tách tiếp."""
    assert len(modules) >= 7, f"chỉ có {len(modules)} module"
    qua_dai = {n: s.count("\n") + 1 for n, s in modules.items() if s.count("\n") + 1 > MAX_DONG_MODULE}
    assert not qua_dai, f"module vượt {MAX_DONG_MODULE} dòng: {qua_dai}"


def test_k71_main_nap_moi_module(modules: dict[str, str]) -> None:
    """Lỗi im lặng nguy hiểm nhất của bước tách: `main.js` chỉ nhập những module nó GỌI TÊN, còn module chỉ có
    `addEventListener` ở top-level (router, drawer, submit, settings…) thì không được nạp — trang mất hẳn một
    mảng tương tác mà không báo lỗi. Nên `main.js` phải nhập ĐỦ, kể cả nhập rỗng cho side-effect."""
    nhap = set(re.findall(r'from "\./(\w+)\.js"', modules["main"])) | set(
        re.findall(r'import "\./(\w+)\.js"', modules["main"]))
    thieu = set(modules) - nhap - {"main"}
    assert not thieu, f"main.js không nhập: {sorted(thieu)} — các module đó sẽ không bao giờ chạy"


def test_k71_moi_ten_nhap_deu_duoc_export(modules: dict[str, str]) -> None:
    """ESM không báo lỗi khi nhập một tên không tồn tại ở bản dựng nào cũ; trình duyệt thì báo, nhưng chỉ khi
    người ta mở trang. Kiểm ở đây để CI bắt trước."""
    decl = re.compile(r"^export (?:async )?(function|const|let|var|class) ([A-Za-z_$][A-Za-z0-9_$]*)")
    ten_phu = re.compile(r"(?:^|,)\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*=")
    exp: dict[str, set[str]] = {}
    for n, s in modules.items():
        ra: set[str] = set()
        for ln in s.splitlines():
            d = decl.match(ln)
            if not d:
                continue
            ra.add(d.group(2))
            than = ln.split("//")[0]
            if d.group(1) in ("const", "let", "var") and not any(x in than for x in ("=>", "{", "/")):
                ra |= {m.group(1) for m in ten_phu.finditer(than[d.start(2):])}
        exp[n] = ra
    exp["util"].add("$$")   # `export const $=(…)=>…, $$=(…)=>…;` — export cả hai, mẫu trên chỉ bắt tên đầu
    loi = [f"{n}.js nhập `{t}` từ {m.group(2)}.js mà ở đó không export"
           for n, s in modules.items()
           for m in re.finditer(r'import \{([^}]*)\} from "\./(\w+)\.js"', s)
           for t in (x.strip() for x in m.group(1).split(",") if x.strip())
           if t not in exp[m.group(2)]]
    assert not loi, "\n".join(loi)


def test_k71_khong_gan_vao_binding_nhap_tu_module_khac(modules: dict[str, str]) -> None:
    """Binding nhập về trong ESM là **chỉ đọc**: `paused = !paused` với `paused` nhập từ `state.js` ném
    `TypeError: Assignment to constant variable` — lúc CHẠY, không lúc parse. Đúng lỗi đã gặp khi tách (bốn
    biến nằm sau dấu phẩy trong `let firstLoad=true, paused=false, …`); `node --check` và đồ thị import đều
    xanh, chỉ mở trang mới thấy. Phải là một cổng, không phải một lần may."""
    loi: list[str] = []
    for n, s in modules.items():
        nhap: dict[str, str] = {}
        for m in re.finditer(r'import \{([^}]*)\} from "\./(\w+)\.js"', s):
            for t in (x.strip() for x in m.group(1).split(",") if x.strip()):
                nhap[t] = m.group(2)
        than = s[s.rfind('from "./'):]
        for t, nguon in sorted(nhap.items()):
            if re.search(rf"(?<![\w$.]){re.escape(t)}\s*(?:=(?!=)|\+\+|--|\+=|-=)", than):
                loi.append(f"{n}.js gán vào `{t}` nhập từ {nguon}.js — dùng setter của module đó")
    assert not loi, "\n".join(loi)


# ---------- K7.2: bootstrap inline có nonce, CSP chặn mọi inline khác ----------

def test_k72_bootstrap_co_nonce_va_csp_khop(tmp_path, monkeypatch) -> None:
    """Đặc tả cho hai phương án; chọn **nonce** thay vì `GET /api/boot`. Lý do: phương án kia đưa token phiên
    vào query string ở lần tải đầu, mà token đó là thứ DUY NHẤT chặn một trang web khác trên cùng máy gọi vào
    console — đưa nó vào URL là đưa vào lịch sử trình duyệt và `Referer`. Đổi rủi ro nhỏ lấy rủi ro lớn hơn."""
    from console import server as srv

    class Ghi:
        """Đủ bề mặt để `_send` chạy: ghi header, nuốt thân. Không dựng server thật vì test này hỏi về HEADER,
        không về mạng."""

        def __init__(self) -> None:
            self.headers: dict[str, str] = {}
            self.command = "GET"
            self.close_connection = False  # `_send` đọc nó để kèm `Connection: close` (audit 2026-10-10)
            self.wfile = io.BytesIO()

        def send_response(self, *a: object) -> None: ...
        def send_header(self, k: str, v: str) -> None: self.headers[k] = v
        def end_headers(self) -> None: ...

    h = Ghi()
    srv.ConsoleHandler._send(h, HTTPStatus.OK, b"x", "text/html", csp_nonce="ABC123")  # type: ignore[arg-type]
    csp = h.headers["Content-Security-Policy"]
    assert "'nonce-ABC123'" in csp and "script-src 'self'" in csp
    assert "unsafe-inline" not in csp.split("script-src")[1].split(";")[0], \
        "script-src không được có unsafe-inline — nonce mất nghĩa"
    assert "https://fonts.googleapis.com" in csp and "https://fonts.gstatic.com" in csp, \
        "trang nạp font từ Google Fonts (index.html:8-10); siết CSP mà quên là mất phông chữ"
    assert "frame-ancestors 'none'" in csp

    # Không truyền nonce (file tĩnh, JSON) thì không gắn CSP: header chỉ có nghĩa cho tài liệu HTML.
    h2 = Ghi()
    srv.ConsoleHandler._send(h2, HTTPStatus.OK, b"{}", "application/json")  # type: ignore[arg-type]
    assert "Content-Security-Policy" not in h2.headers


def test_k71_js_duoc_phuc_vu_dung_content_type() -> None:
    """`text/javascript` + `nosniff`: sai kiểu là trình duyệt từ chối nạp module và trang trắng."""
    from console import server as srv

    assert srv._CONTENT_TYPES[".js"].startswith("text/javascript")
