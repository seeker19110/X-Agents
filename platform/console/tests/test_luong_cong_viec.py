"""Ô "Luồng công việc" ở đầu màn Trực ban (2026-10-13): một sơ đồ ngang yêu cầu → đặc tả → ticket → RC → staging →
production → nghiệm thu, mỗi bậc một con số thật, và các điểm dừng chờ người (gate) đứng ĐÚNG giữa hai bậc mà nó
chặn — người trực nhìn một dải là biết việc đang dồn ở đâu và chỗ nào đang chờ mình.

Không thêm dữ liệu backend: số bậc cộng từ `product_funnel` (truth.py, ADR-0003 — bậc rỗng mang `empty=True`), số
gate đếm từ `gates`. Hai bảng của ô (bậc, chỗ đặt gate) phải khớp hợp đồng Python — lệch là một bậc biến mất hay
một loại gate không bao giờ hiện, im lặng.
"""

from __future__ import annotations

import re
import typing
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "console" / "static"
JS = STATIC / "js" / "flow.js"
pytestmark = pytest.mark.cong_repo


@pytest.fixture(scope="module")
def html() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def flow() -> str:
    assert JS.exists(), "thiếu static/js/flow.js"
    return JS.read_text(encoding="utf-8")


def test_o_luong_dung_dau_truc_ban_sau_canh_bao_truoc_luoi(html: str) -> None:
    truc_ban = html.split('id="v-truc-ban"', 1)[1].split('<section class="view', 1)[0]
    assert 'id="flow"' in truc_ban, "ô Luồng công việc phải nằm trong màn Trực ban"
    assert truc_ban.index('id="s-dead"') < truc_ban.index('id="flow"') < truc_ban.index('<div class="desk">'), (
        "thứ tự: cảnh báo → Luồng công việc → lưới việc của bạn"
    )


def test_bac_cua_luong_khop_product_stages(flow: str) -> None:
    from console.truth import PRODUCT_STAGES

    m = re.search(r"export const STAGES=\[(.*?)\];", flow, re.S)
    assert m, "flow.js phải khai `export const STAGES=[...]`"
    assert re.findall(r'\["(\w+)"', m.group(1)) == [k for k, _ in PRODUCT_STAGES], (
        "bậc của ô Luồng phải đúng thứ tự PRODUCT_STAGES của truth.py"
    )


def test_moi_loai_gate_cong_ty_co_cho_tren_luong(flow: str) -> None:
    """Gate nào chặn bậc nào thì đứng trước bậc đó. `escalation` mở ra ở bất kỳ bậc nào nên có ô riêng."""
    from company.gates import GateKind

    m = re.search(r"export const GATE_AT=\{(.*?)\};", flow, re.S)
    assert m, 'flow.js phải khai `export const GATE_AT={kind:"bậc sau gate"}`'
    at = dict(re.findall(r'(\w+):"(\w+)"', m.group(1)))
    kinds = set(typing.get_args(GateKind)) | {"clarification"}
    assert set(at) | {"escalation"} == kinds, f"GATE_AT {sorted(at)} + escalation phải phủ đúng {sorted(kinds)}"
    stages = re.findall(r'\["(\w+)"', re.search(r"export const STAGES=\[(.*?)\];", flow, re.S).group(1))
    assert set(at.values()) <= set(stages), "gate phải trỏ tới một bậc có thật"
    assert '"escalation"' in flow, "gate leo thang phải có ô riêng"


def test_bac_rong_la_o_xam_doc_tu_du_lieu(flow: str, html: str) -> None:
    """ADR-0003: bậc không có gì là XÁM — đọc `empty` của truth.py, không tự suy từ số."""
    assert ".empty" in flow and '"zero"' in flow
    css = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    m = re.search(r"\.flow \.node\.zero\{([^}]*)\}", css)
    assert m and "dashed" in m.group(1), "bậc rỗng phải có style xám viền gạch đứt riêng"


def test_luong_duoc_ve_moi_khung_va_bam_gate_mo_ngan_keo(flow: str) -> None:
    main = (STATIC / "js" / "main.js").read_text(encoding="utf-8")
    assert "renderFlow();" in main.split("export function render()", 1)[1].split("\n}\n", 1)[0]
    assert re.search(r'import \{[^}]*openGate[^}]*\} from "\./drawer\.js"', flow)
    assert '$("#flow").addEventListener("click"' in flow
