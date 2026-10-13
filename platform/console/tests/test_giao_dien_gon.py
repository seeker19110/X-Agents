"""Console thiết kế lại cho gọn (2026-10-13): một trang cuộn của ADR-0011 giữ nguyên, nhưng trang không được
dài tới mức người trực phải cuộn qua 28 000 px mới tới mục cuối.

Đo trước khi sửa (dữ liệu thật `companies/software-company/company.sqlite`, khung 1440×900): trang cao
28 411 px — "Pull request chờ review" 4 043 px, "Can thiệp của supervisor" 5 441 px, "Chờ bạn duyệt" 2 656 px
cho 14 gate, Hướng dẫn 3 000 px luôn mở. Thêm hai lỗi nhìn thấy được: hai khung đỏ RỖNG ở đầu trang vì
`.sect{display:flex}` đè thuộc tính `hidden` (khối sandbox/bế tắc im lặng đã tắt mà vẫn vẽ viền), và thẻ gate
"reviewer đã ký" dùng `pill ok` — class không có style nào.

Mấy test dưới đây canh các bất biến đó trên chính file tĩnh (không có bước build nên không gì khác bắt được).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "console" / "static"
JS_DIR = STATIC / "js"
pytestmark = pytest.mark.cong_repo


@pytest.fixture(scope="module")
def html() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css(html: str) -> str:
    m = re.search(r"<style>(.*?)</style>", html, re.S)
    assert m, "index.html phải có khối <style>"
    return m.group(1)


@pytest.fixture(scope="module")
def js() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(JS_DIR.glob("*.js")))


def _rule(css: str, selector: str) -> str:
    """Thân của khối CSS có đúng bộ chọn `selector` (khối đầu tiên khớp, ngoài mọi @media)."""
    m = re.search(r"(?:^|[}\s])" + re.escape(selector) + r"\{([^}]*)\}", css)
    assert m, f"không tìm thấy khối CSS `{selector}{{...}}`"
    return m.group(1)


def _section(html: str, view: str) -> str:
    return html.split(f'id="v-{view}"', 1)[1].split('<section class="view', 1)[0]


def test_thuoc_tinh_hidden_luon_thang_moi_display(css: str) -> None:
    """`hidden` là cách JS tắt khối cảnh báo (`$("#s-silent").hidden=!list.length`). Khối đó mang class `.sect`
    có `display:flex`, mà CSS tác giả thắng CSS mặc định của trình duyệt — nên `hidden` vô hiệu và trang vẽ
    khung đỏ rỗng. Một luật `!important` chung là đủ cho mọi khối hiện có và mọi khối thêm sau."""
    assert re.search(r"\[hidden\]\{display:none\s*!important;?\}", css), (
        "thiếu `[hidden]{display:none!important}` — khối đã tắt vẫn hiện khung"
    )


@pytest.mark.parametrize("selector", [".tablewrap", ".stream", ".queue", ".board .col", "#budgets"])
def test_danh_sach_dai_cuon_trong_khung_khong_keo_dai_trang(css: str, selector: str) -> None:
    """Mọi danh sách tăng theo dữ liệu đều có trần chiều cao và cuộn bên trong. Số liệu vẫn đủ (không cắt bớt
    dòng nào — ô tìm và sắp xếp vẫn chạy trên toàn bộ), chỉ là không đẩy các mục bên dưới đi xa hàng nghìn px."""
    body = _rule(css, selector)
    assert "max-height:" in body, f"`{selector}` phải có max-height"
    assert re.search(r"overflow(?:-y)?:auto", body), f"`{selector}` phải cuộn bên trong (overflow:auto)"


def test_tieu_de_bang_dinh_khi_cuon_trong_khung(css: str) -> None:
    """Bảng cuộn trong khung mà tiêu đề trôi mất thì người đọc dòng 30 không biết cột nào là `lint`."""
    body = _rule(css, "th")
    assert "position:sticky" in body and "top:0" in body


def test_truc_ban_xep_luoi_viec_cua_ban_canh_suc_khoe_may(html: str, css: str) -> None:
    """Câu hỏi đầu tiên của người trực là "có gì chờ tôi không", câu thứ hai là "máy có chạy không". Hai câu đứng
    cạnh nhau trong MỘT lưới: hàng đợi gate là cột chính, Động cơ / Thông báo / Máy đang làm gì là cột phụ.
    Thứ tự DOM Động cơ → Thông báo → Chờ duyệt (test_static_ui) giữ nguyên; vị trí do `grid-template-areas`."""
    truc_ban = _section(html, "truc-ban")
    m = re.search(r'<div class="desk">(.*?)\n      </div><!-- /desk -->', truc_ban, re.S)
    assert m, 'màn Trực ban phải có khối `<div class="desk">…</div><!-- /desk -->`'
    for box in ('id="engine"', 'id="notify"', 'id="queue"', 'id="running"'):
        assert box in m.group(1), f"{box} phải nằm trong lưới desk"
    desk = _rule(css, ".desk")
    assert "display:grid" in desk and "grid-template-areas:" in desk
    for area in ("q", "eng", "ntf", "run"):
        assert re.search(r"grid-area:\s*" + area + r"\b", css), f"thiếu ô lưới `{area}`"


def test_moi_man_thong_tin_co_tieu_de_rieng(html: str) -> None:
    """Một trang cuộn dài thì người đọc phải biết mình đang ở màn nào mà không cần nhìn lên thanh bên."""
    for view in ("truc-ban", "phieu", "phan-mem", "bao-tri", "chi-phi", "nhat-ky", "cai-dat", "huong-dan"):
        assert re.search(r'<header class="vh">\s*<h2>[^<]+</h2>', _section(html, view)), (
            f'màn {view} thiếu tiêu đề `<header class="vh"><h2>…</h2>`'
        )


def test_huong_dan_va_form_giao_viec_gap_lai_mac_dinh(html: str) -> None:
    """Tài liệu tĩnh (3 000 px) và form dài không phải thứ người trực đọc mỗi lần mở trang — gập lại, bấm tiêu
    đề là mở. Nội dung giữ nguyên chữ (test_static_ui canh), chỉ đổi vỏ."""
    guide = _section(html, "huong-dan")
    assert not re.search(r'<div class="sect">', guide), (
        'mọi mục Hướng dẫn phải là <details>, không còn <div class="sect">'
    )
    assert guide.count('<details class="sect fold">') >= 9
    assert guide.count('<summary class="sect-head">') == guide.count('<details class="sect fold">')
    assert re.search(r'<details class="sect submit fold" data-xuong="software-company">', _section(html, "phan-mem"))


def test_nav_sang_theo_vi_tri_cuon(js: str) -> None:
    """Nav là mục lục của một trang cuộn (ADR-0011): cuộn tới đâu, mục đó sáng và tiêu đề thanh trên đổi theo —
    nếu không, tiêu đề ghi "Trực ban" trong khi người đọc đang ở bảng chi phí. Chỉ đổi đánh dấu, không cuộn lại
    (không gọi `showView` từ observer, kẻo vòng lặp cuộn)."""
    router = (JS_DIR / "router.js").read_text(encoding="utf-8")
    assert "IntersectionObserver" in router
    spy = router.split("export function spy(", 1)
    assert len(spy) == 2, "router.js phải có `export function spy(v)`"
    body = spy[1].split("\n}\n", 1)[0]
    assert "aria-current" in body and "titles()" in body
    assert "scrollIntoView" not in body and "showView" not in body


#: Mọi thẻ HTML thật mà file tĩnh dùng. Thứ gì khác trông như thẻ (`<xưởng>`, `<tên>`) là chữ quên thoát.
THE_HTML = (
    "a b i p br code pre div span section aside main header details summary table thead tbody tr th td "
    "ol ul li h1 h2 h3 svg path rect circle button input kbd dl dt dd style script title link meta label "
    "textarea select option small em strong mark u s"
).split()


def test_chu_trong_trang_khong_bi_hieu_thanh_the(html: str) -> None:
    """Đo 2026-10-13 ở màn 375 px: Hướng dẫn ghi `console/.engine/<xưởng>.log` trần trong `<pre>`, trình duyệt dựng
    phần tử `<xưởng>` và chữ biến mất — người đọc thấy `console/.engine/.log`. Chữ có `<` phải viết `&lt;`."""
    gia = [m.group(0) for m in re.finditer(r"</?([^\s>/!]+)[^>]*>", html) if m.group(1).lower() not in THE_HTML]
    assert not gia, f"chữ trông như thẻ HTML, cần thoát thành &lt;…&gt;: {gia}"


def test_moi_class_pill_va_tag_dung_trong_js_deu_co_style(css: str, js: str) -> None:
    """`pill ok` từng được vẽ mà không có `.pill.ok` → chữ "reviewer đã ký" hiện như chữ thường. Rà cả họ: mọi
    biến thể `pill X` / `tag X` viết cứng trong JS hoặc HTML (dạng `class="pill X"`, hoặc nhánh đầu của
    `class="pill ${cond?"X":…}"`) phải có khối CSS tương ứng. Biến thể tính từ biến (`pill ${cls}`) thì bảng
    nguồn của nó (PILL ở engine.js/notify.js) đã có test riêng."""
    src = js + "\n" + (STATIC / "index.html").read_text(encoding="utf-8")
    used: set[tuple[str, str]] = set()
    for base in ("pill", "tag"):
        used |= {(base, c) for c in re.findall(r'class="' + base + r" ([a-z]+)[\"$ ]", src)}
        used |= {(base, c) for c in re.findall(r'class="' + base + r' \$\{[^}]*?\?"([a-z]+)"', src)}
    thieu = sorted(f".{b}.{c}" for b, c in used if f".{b}.{c}" not in css)
    assert not thieu, f"class dùng trong JS/HTML mà không có style: {thieu}"
