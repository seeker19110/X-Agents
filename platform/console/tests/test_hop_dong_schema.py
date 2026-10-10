"""K7.4 kịch bản B — hợp đồng giữa console và schema topic của software-company + keeper.

Console đọc THẲNG các trường trong payload của software-company (`collect.py`, `truth.py`).
Không có gì canh mối nối đó: đổi tên một trường trong `topics/schemas/*.json` thì test của công ty đó vẫn xanh,
còn console **vỡ âm thầm** — ô hiện rỗng hoặc sai chứ không báo lỗi. Đúng khuôn "số xanh vì rỗng" đã ghi trong
`console/TRAPS.md`, và là loại hỏng tệ nhất vì người trực vẫn thấy một trang bình thường.

Cách canh: **quét chính mã nguồn console** để lấy tên trường nó đọc, rồi khẳng định từng tên có mặt trong ít nhất
một schema. Quét thay vì chép tay danh sách vì một danh sách chép tay chỉ đúng tới lần sửa tiếp theo — nó sẽ
xanh vì rỗng, đúng cái bệnh test này sinh ra để chữa.

Hai chiều:
- công ty đổi/bỏ một trường console đang đọc → tên đó không còn trong schema nào → **đỏ**;
- console bắt đầu đọc một trường không tồn tại (gõ nhầm, hoặc nhớ nhầm tên) → cũng **đỏ**.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.cong_repo   # đọc file ngoài gói console → hook chạy cả ở chế độ nhanh (F6)
CONSOLE_SRC = [ROOT / "platform" / "console" / "src" / "console" / f for f in ("collect.py", "truth.py")]
# `keeper` có mặt vì `collect.py` đọc payload của công ty bảo trì (`maintenance-tickets`, `debt-ledger`,
# `release-notes`) — thiếu nó thì trường console đọc riêng của keeper không schema nào chứa và test đỏ.
PACKAGES = {"companies/software-company": "company", "companies/keeper": "keeper"}

# Đọc payload của envelope: `e.payload.get("x")`, `payload.get("x", …)`, `p.get("x")`, `p["x"]`.
# Biến `p` là quy ước dùng khắp `collect.py`/`truth.py` cho `e.payload` — bắt nó là bắt đúng chỗ console chạm
# vào hợp đồng, chứ không bắt mọi `.get(` trong file (nhiều cái đọc dict do chính console dựng ra).
DOC_PAYLOAD = re.compile(r'(?:(?:e|env|ev)\.payload|payload|p)\.get\("([a-z_]+)"(?:\s*,[^)]*)?\)'
                         r'|(?:payload|p)\["([a-z_]+)"\]')

# Tên KHÔNG phải trường payload, có lý do rõ — không phải chỗ giấu trường chưa kiểm:
KHONG_PHAI_TRUONG_PAYLOAD: set[str] = set()

# Trường LỒNG một tầng: `<topic>.<trường>.<khoá con>`. Quét regex chỉ thấy tầng ngoài, mà đây đúng là chỗ vừa
# thêm bằng chứng ở K2.5 (`sandbox`) — mất nó là console lại đọc ra `None` mà không ai biết.
HOP_DONG_LONG: dict[str, dict[str, set[str]]] = {
    "pull-requests": {"local_checks": {"lint", "tests", "verified_by", "sandbox"}},
    "release-events": {"smoke": {"ok", "unverified", "sandbox"}},
}


def _schema(pkg: str, topic: str) -> dict[str, Any]:
    return json.loads((ROOT / pkg / "topics" / "schemas" / f"{topic}.json").read_text(encoding="utf-8"))


def _payload_props(schema: dict[str, Any]) -> dict[str, Any]:
    return ((schema.get("properties") or {}).get("payload") or {}).get("properties") or {}


@pytest.fixture(scope="module")
def truong_console_doc() -> set[str]:
    ten: set[str] = set()
    for f in CONSOLE_SRC:
        for m in DOC_PAYLOAD.finditer(f.read_text(encoding="utf-8")):
            ten.add(m.group(1) or m.group(2))
    assert len(ten) >= 20, f"quét ra {len(ten)} tên — mẫu regex hỏng, test sẽ xanh vì rỗng"
    return ten


@pytest.fixture(scope="module")
def truong_trong_schema() -> dict[str, list[str]]:
    ra: dict[str, list[str]] = {}
    for pkg in PACKAGES:
        for f in sorted((ROOT / pkg / "topics" / "schemas").glob("*.json")):
            for k in _payload_props(json.loads(f.read_text(encoding="utf-8"))):
                ra.setdefault(k, []).append(f"{pkg}/{f.stem}")
    assert len(ra) > 50, "không nạp được schema của ba công ty"
    return ra


def thieu_trong_schema(doc: set[str], co_trong_schema: dict[str, list[str]]) -> list[str]:
    """Phép so của K7.4, tách thành hàm để chính nó kiểm được (xem test đo hai chiều cuối file)."""
    return sorted(n for n in doc if n not in co_trong_schema and n not in KHONG_PHAI_TRUONG_PAYLOAD)


def test_moi_truong_console_doc_deu_ton_tai_trong_schema(truong_console_doc, truong_trong_schema) -> None:
    """Cột chính của K7.4. Đỏ ở đây nghĩa là MỘT trong hai chuyện đã xảy ra, và cả hai đều cần người xử:
    công ty đổi/bỏ một trường console đang đọc, hoặc console đọc một tên không có thật."""
    thieu = thieu_trong_schema(truong_console_doc, truong_trong_schema)
    assert not thieu, (
        "console đọc trường không có trong schema nào của hai công ty:\n  " + "\n  ".join(thieu)
        + "\n\nHoặc công ty vừa đổi tên/bỏ trường (sửa console cho khớp), hoặc console gõ nhầm tên. "
          "Không phải trường payload thì thêm vào KHONG_PHAI_TRUONG_PAYLOAD kèm lý do.")


def test_danh_sach_mien_khong_phinh_len_thanh_cho_giau(truong_console_doc, truong_trong_schema) -> None:
    """Chiều ngược: mỗi mục trong danh sách miễn phải THẬT SỰ không phải trường schema và THẬT SỰ đang được đọc.
    Không có test này thì cách rẻ nhất để làm xanh test trên là ném tên vào danh sách miễn."""
    for n in sorted(KHONG_PHAI_TRUONG_PAYLOAD):
        assert n in truong_console_doc, f"{n!r} không còn được console đọc — bỏ khỏi danh sách miễn"
        assert n not in truong_trong_schema, f"{n!r} LÀ trường schema, không được miễn"


@pytest.mark.parametrize("topic", sorted(HOP_DONG_LONG))
def test_truong_long_mot_tang_van_con_trong_schema(topic: str) -> None:
    """`local_checks.sandbox` / `smoke.sandbox` (K2.5) là bằng chứng ô cảnh báo K2.7 đọc. Regex chỉ thấy tầng
    ngoài, nên tầng trong phải canh riêng — bỏ một khoá ở đây thì ô sandbox im lặng đọc ra `None` và người trực
    kết luận "không có lượt nào ngoài container", đúng chiều nguy hiểm."""
    props = _payload_props(_schema("companies/software-company", topic))
    for cha, con in HOP_DONG_LONG[topic].items():
        assert cha in props, f"{topic}.{cha} biến mất khỏi schema"
        co = set(props[cha].get("properties") or {})
        assert con <= co, f"{topic}.{cha} thiếu khoá console đang đọc: {sorted(con - co)}"


def test_do_hai_chieu_cong_ty_doi_ten_truong_thi_test_nay_do(truong_console_doc, truong_trong_schema) -> None:
    """Chứng minh phép đo có răng, không chỉ xanh vì mọi thứ đang tình cờ khớp.

    Dựng đúng kịch bản cần bắt — software-company đổi tên `ticket_id` thành thứ khác, nên nó biến mất khỏi MỌI
    schema — rồi chạy lại chính `thieu_trong_schema`. Nó phải chỉ đích danh trường đó."""
    assert not thieu_trong_schema(truong_console_doc, truong_trong_schema), "bản thật phải xanh trước đã"
    doi_ten = {k: v for k, v in truong_trong_schema.items() if k != "ticket_id"}
    assert thieu_trong_schema(truong_console_doc, doi_ten) == ["ticket_id"]


def test_do_hai_chieu_console_go_nham_ten_thi_test_nay_do(truong_trong_schema) -> None:
    """Chiều còn lại: console đọc một tên không có thật (gõ nhầm, hay nhớ nhầm tên trường của công ty kia)."""
    assert thieu_trong_schema({"ticket_id", "ticket_di"}, truong_trong_schema) == ["ticket_di"]
