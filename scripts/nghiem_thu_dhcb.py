#!/usr/bin/env python3
"""Nghiệm thu ẩn của đề bài DHCB-B1 v1 (`docs/do-hai-khung/DE-BAI.md`): chấm hộp đen một repo do khung làm ra.

Chỉ dùng hợp đồng chạy của đề bài (`setup.sh`, `run.sh`, `test.sh`, `PORT`, `DATA_DIR`, `ADMIN_PASSWORD`) và HTTP,
không đọc mã nguồn, nên chấm được mọi ngôn ngữ/framework mà hai khung chọn. Mỗi Must đạt khi MỌI ca của nó đạt.

**Ẩn**: không cho khung nào thấy file này trước khi lượt chạy kết thúc (`docs/do-hai-khung/README.md` §4). Nó chạy
mã do model viết → chạy trong máy ảo hay container dùng một lần, không chạy trên máy có khoá thật.
Chỉ thư viện chuẩn; tự kiểm bằng bản mẫu `platform/console/tests/fixtures/dhcb_mau/` (`test_nghiem_thu_dhcb.py`).
"""

from __future__ import annotations

import argparse
import base64
import csv
import http.client
import io
import json
import os
import random
import secrets
import signal
import socket
import string
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

DE_BAI = "DHCB-B1 v1"
MUST = tuple(f"M-{i:02d}" for i in range(1, 13))
KHU_VUC = {"ha-noi", "tp-hcm", "da-nang", "khac"}


class Truot(Exception):
    """Ca trượt; thông điệp là ghi chú cho người đọc báo cáo."""


# ---------- HTTP và HTML ----------


@dataclass
class Dap:
    ma: int
    header: dict[str, str]
    than: str


def goi(port: int, phuong: str, duong: str, du_lieu: dict[str, str] | bytes | None = None,
        header: dict[str, str] | None = None) -> Dap:
    h = dict(header or {})
    body: bytes | None = None
    if isinstance(du_lieu, dict):
        body = urlencode(du_lieu).encode("utf-8")
    elif isinstance(du_lieu, bytes):
        body = du_lieu
    if body is not None:
        h.setdefault("Content-Type", "application/x-www-form-urlencoded")
    cx = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        cx.request(phuong, duong, body=body, headers=h)
        r = cx.getresponse()
        return Dap(r.status, {k.lower(): v for k, v in r.getheaders()}, r.read().decode("utf-8", "replace"))
    finally:
        cx.close()


class _Html(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.the: list[tuple[str, dict[str, str]]] = []
        self.nhan: set[str] = set()
        self.lua_chon: dict[str, list[str]] = {}
        self._select: str | None = None
        self.h2 = 0
        self.lang: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        self.the.append((tag, a))
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "h2":
            self.h2 += 1
        elif tag == "label" and a.get("for"):
            self.nhan.add(a["for"])
        elif tag == "select":
            self._select = a.get("name", "")
            self.lua_chon.setdefault(self._select, [])
        elif tag == "option" and self._select is not None and a.get("value"):
            self.lua_chon[self._select].append(a["value"])

    def handle_endtag(self, tag: str) -> None:
        if tag == "select":
            self._select = None


def html(than: str) -> _Html:
    p = _Html()
    p.feed(than)
    return p


def can(dk: bool, ghi_chu: str) -> None:
    if not dk:
        raise Truot(ghi_chu)


def can_ma(d: Dap, ma: int, viec: str) -> None:
    can(d.ma == ma, f"{viec}: mong {ma}, nhận {d.ma}")


# ---------- máy chủ ----------


@dataclass
class May:
    repo: Path
    port: int
    mat_khau: str
    data: Path
    log: Path
    canh_bao: list[str]
    cho: float = 60
    tien_trinh: subprocess.Popen[bytes] | None = None
    da_luu: dict[str, str] = field(default_factory=dict)   # tên dữ liệu thử → giá trị đã gửi
    bi_mat: list[str] = field(default_factory=list)       # chuỗi PII không được lọt vào log

    def lenh(self, ten: str) -> list[str]:
        f = self.repo / ten
        if not os.access(f, os.X_OK):
            ghi = f"hợp đồng: {ten} thiếu quyền thực thi — chạy bằng sh"
            if ghi not in self.canh_bao:
                self.canh_bao.append(ghi)
            return ["sh", str(f)]
        return [str(f)]

    def bat(self, mat_khau: bool = True) -> subprocess.Popen[bytes]:
        env = {**os.environ, "PORT": str(self.port), "DATA_DIR": str(self.data)}
        env.pop("ADMIN_PASSWORD", None)
        if mat_khau:
            env["ADMIN_PASSWORD"] = self.mat_khau
        with self.log.open("ab") as log:
            return subprocess.Popen(self.lenh("run.sh"), cwd=self.repo, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, start_new_session=True)

    def len(self, cho: float) -> bool:
        self.tien_trinh = self.bat()
        het = time.monotonic() + cho
        while time.monotonic() < het:
            if self.tien_trinh.poll() is not None:
                return False
            try:
                goi(self.port, "GET", "/")
                return True
            except OSError:
                time.sleep(0.2)
        return False

    def dung(self, p: subprocess.Popen[bytes] | None = None) -> None:
        p = p or self.tien_trinh
        if p is None or p.poll() is not None:
            return
        try:
            os.killpg(p.pid, signal.SIGTERM)
            p.wait(10)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait(10)
        except ProcessLookupError:  # nhóm tiến trình đã tự thoát giữa poll và killpg
            p.wait(10)

    def quan_tri(self, duong: str = "/quan-tri/dang-ky", mat_khau: str | None = None) -> Dap:
        tin = base64.b64encode(f"admin:{self.mat_khau if mat_khau is None else mat_khau}".encode()).decode()
        return goi(self.port, "GET", duong, header={"Authorization": f"Basic {tin}"})

    def bang_quan_tri(self) -> str:
        d = self.quan_tri()
        can_ma(d, 200, "trang quản trị (cần cho ca này)")
        return d.than


def _ten() -> str:
    return "Nguyễn Thị Kiểm " + "".join(random.choices(string.ascii_uppercase, k=6))


def _sdt() -> str:
    return "09" + "".join(random.choices(string.digits, k=8))


def hop_le(**doi: str | None) -> dict[str, str]:
    d: dict[str, str | None] = {"ho_ten": _ten(), "so_dien_thoai": _sdt(), "email": f"kt{secrets.token_hex(4)}@vidu.vn",
         "khu_vuc": "da-nang", "ly_do": "Muốn giúp đỡ cộng đồng", "dong_y": "on"}
    d.update(doi)
    return {k: v for k, v in d.items() if v is not None}


# ---------- các ca ----------


def c01(m: May) -> None:
    d = goi(m.port, "GET", "/")
    can_ma(d, 200, "GET /")
    p = html(d.than)
    can(p.lang == "vi", f'thiếu lang="vi" (thấy {p.lang!r})')
    can("Đồng Hành Cùng Bạn" in d.than, 'thiếu chữ "Đồng Hành Cùng Bạn"')
    can(any(t == "a" and a.get("href", "").rstrip("/").endswith("/dang-ky") for t, a in p.the),
        "không có liên kết tới /dang-ky")


def c02(m: May) -> None:
    d = goi(m.port, "GET", "/gioi-thieu")
    can_ma(d, 200, "GET /gioi-thieu")
    can(html(d.than).h2 >= 2, "ít hơn hai tiêu đề <h2>")


def c03(m: May) -> None:
    d = goi(m.port, "GET", "/dang-ky")
    can_ma(d, 200, "GET /dang-ky")
    p = html(d.than)
    can(any(t == "form" and a.get("method", "").lower() == "post" and a.get("action", "").endswith("/dang-ky")
            for t, a in p.the), 'không có <form method="post" action="/dang-ky">')
    o = {a["name"]: (t, a) for t, a in p.the if t in ("input", "select", "textarea") and a.get("name")}
    thieu = [n for n in ("ho_ten", "so_dien_thoai", "email", "khu_vuc", "ly_do", "dong_y") if n not in o]
    can(not thieu, f"thiếu trường: {', '.join(thieu)}")
    can(o["khu_vuc"][0] == "select" and set(p.lua_chon.get("khu_vuc", [])) == KHU_VUC
        and len(p.lua_chon["khu_vuc"]) == 4, f"khu_vuc phải là <select> đúng 4 giá trị, thấy {p.lua_chon.get('khu_vuc')}")
    can(o["dong_y"][1].get("type", "").lower() == "checkbox", "dong_y không phải checkbox")
    khong_nhan = [n for n, (_, a) in o.items() if a.get("type", "").lower() != "hidden"
                  and (not a.get("id") or a["id"] not in p.nhan)]
    can(not khong_nhan, f'ô thiếu <label for> trỏ đúng id: {", ".join(sorted(khong_nhan))}')


def c04(m: May) -> None:
    d = hop_le()
    r = goi(m.port, "POST", "/dang-ky", d)
    can_ma(r, 201, "đăng ký hợp lệ")
    can("Cảm ơn" in r.than, 'thiếu chữ "Cảm ơn"')
    m.da_luu.update(ten=d["ho_ten"], sdt=d["so_dien_thoai"])
    m.bi_mat += [d["ho_ten"], d["so_dien_thoai"][-9:], d["email"]]   # 9 số cuối: khớp cả dạng 0… lẫn +84…


def _422(m: May, ten_ca: str, **doi: str) -> Dap:
    d = hop_le(**doi)
    # Chỉ ghi tên thử DUY NHẤT do bộ chấm sinh: tên ca tự đặt (vd `A` ở C05) khớp chuỗi con với mọi thứ khác.
    if "ho_ten" not in doi:
        m.da_luu["bi_tu_choi"] = m.da_luu.get("bi_tu_choi", "") + d["ho_ten"] + "\n"
    r = goi(m.port, "POST", "/dang-ky", d)
    can_ma(r, 422, ten_ca)
    return r


def c05(m: May) -> None:
    sdt = _sdt()
    r = _422(m, "họ tên một ký tự", ho_ten=" A ", so_dien_thoai=sdt)
    can('name="ho_ten"' in r.than or "name='ho_ten'" in r.than, "không hiện lại form")
    can(sdt in r.than, "không giữ lại số điện thoại đã nhập")


def c06(m: May) -> None:
    _422(m, "số điện thoại 12345", so_dien_thoai="12345")


def c07(m: May) -> None:
    _422(m, "email sai", email="khong-phai-email")


def c08(m: May) -> None:
    _422(m, "khu vực lạ", khu_vuc="sao-hoa")


def c09(m: May) -> None:
    _422(m, "lý do 501 ký tự", ly_do="a" * 501)


def c10(m: May) -> None:
    so = _sdt()
    d = hop_le(ly_do="b" * 500, so_dien_thoai=f"{so[:3]}.{so[3:6]} {so[6:]}")
    can_ma(goi(m.port, "POST", "/dang-ky", d), 201, "lý do đúng 500 ký tự, số có dấu chấm/khoảng trắng")
    m.bi_mat += [d["ho_ten"], so[-9:]]


def c11(m: May) -> None:
    d = hop_le(dong_y=None)
    can_ma(goi(m.port, "POST", "/dang-ky", d), 422, "thiếu dong_y")
    can(d["ho_ten"] not in m.bang_quan_tri(), "thiếu dong_y mà vẫn lưu")


def c12(m: May) -> None:
    bang = m.bang_quan_tri()
    lot = [t for t in m.da_luu.get("bi_tu_choi", "").split("\n") if t.strip() and t.strip() in bang]
    can(not lot, f"dữ liệu sai vẫn được lưu: {lot}")


def c13(m: May) -> None:
    can("sdt" in m.da_luu, "không có bản ghi gốc (ca đăng ký hợp lệ đã trượt)")
    d = hop_le(so_dien_thoai="+84" + m.da_luu["sdt"][1:])
    r = goi(m.port, "POST", "/dang-ky", d)
    can_ma(r, 409, "cùng số viết dạng +84")
    can(d["ho_ten"] not in m.bang_quan_tri(), "trùng số mà vẫn lưu bản thứ hai")


XSS_FORM = "<script>alert('dhcb')</script>"
XSS_BANG = "<img src=x onerror=alert(1)>"


def c14(m: May) -> None:
    r = goi(m.port, "POST", "/dang-ky", hop_le(ho_ten=XSS_FORM, so_dien_thoai="123"))
    can(XSS_FORM not in r.than, "form báo lỗi in lại <script> không escape")


def c15(m: May) -> None:
    # Từ chối họ tên có ký tự HTML (422) cũng an toàn: ca chỉ đòi bảng quản trị không chứa thẻ thô.
    goi(m.port, "POST", "/dang-ky", hop_le(ho_ten=XSS_BANG))
    can(XSS_BANG not in m.bang_quan_tri(), "trang quản trị in họ tên không escape")


def c16(m: May) -> None:
    can_ma(goi(m.port, "GET", "/quan-tri/dang-ky"), 401, "quản trị không xác thực")
    can_ma(m.quan_tri(mat_khau="sai-" + m.mat_khau), 401, "quản trị sai mật khẩu")
    can(m.da_luu.get("ten", "\0") in m.bang_quan_tri(), "bảng quản trị không có bản ghi vừa đăng ký")


CONG_THUC = "=HYPERLINK(\"http://vidu.invalid\")"


def c17(m: May) -> None:
    goi(m.port, "POST", "/dang-ky", hop_le(ly_do=CONG_THUC))
    goi(m.port, "POST", "/dang-ky", hop_le(ho_ten="-Kiểm Thử Công Thức", ly_do="@SUM(1+1)"))
    d = m.quan_tri("/quan-tri/dang-ky.csv")
    can_ma(d, 200, "CSV")
    can(d.header.get("content-type", "").startswith("text/csv"), f"Content-Type {d.header.get('content-type')!r}")
    hang = list(csv.reader(io.StringIO(d.than.lstrip("﻿"))))
    can(len(hang) >= 2, "CSV không có dòng tiêu đề + bản ghi")
    can(m.da_luu.get("ten", "\0") in d.than, "CSV thiếu bản ghi hoặc hỏng dấu tiếng Việt")
    nguy = [o for h in hang[1:] for o in h if o[:1] in ("=", "+", "-", "@")]
    can(not nguy, f"ô CSV có thể thành công thức trong Excel: {nguy[:3]}")


def c18(m: May) -> None:
    d = goi(m.port, "GET", "/khong-co-trang-nay-" + secrets.token_hex(3))
    can_ma(d, 404, "đường lạ")
    can(html(d.than).lang == "vi", '404 không phải trang HTML lang="vi"')


def c19(m: May) -> None:
    try:
        d = goi(m.port, "POST", "/dang-ky", urlencode(hop_le(ly_do="x" * 11 * 1024)).encode())
    except OSError as e:
        raise Truot(f"thân 11 KB làm đứt kết nối thay vì trả 413: {e}") from e
    can_ma(d, 413, "thân POST 11 KB")


def c20(m: May) -> None:
    thieu = []
    for duong in ("/", "/gioi-thieu", "/dang-ky", "/khong-co-" + secrets.token_hex(3)):
        h = goi(m.port, "GET", duong).header
        if "content-security-policy" not in h:
            thieu.append(f"{duong}: Content-Security-Policy")
        if h.get("x-content-type-options", "").lower() != "nosniff":
            thieu.append(f"{duong}: X-Content-Type-Options")
    can(not thieu, "thiếu header: " + "; ".join(thieu))


def c21(m: May) -> None:
    m.dung()
    can(m.len(m.cho), "chạy lại run.sh với cùng DATA_DIR thì máy chủ không lên")
    can(m.da_luu.get("ten", "\0") in m.bang_quan_tri(), "chạy lại thì mất bản ghi — không lưu bền")


def c22(m: May) -> None:
    m.dung()
    log = m.log.read_text(encoding="utf-8", errors="replace")
    lot = [s for s in m.bi_mat if s and s in log]
    can(not lot, f"log chứa dữ liệu cá nhân ({len(lot)} chuỗi)")


def c23(m: May) -> None:
    p = m.bat(mat_khau=False)
    try:
        p.wait(15)
    except subprocess.TimeoutExpired:
        try:
            goi(m.port, "GET", "/")
            raise Truot("không có ADMIN_PASSWORD mà vẫn chạy máy chủ") from None
        except OSError:
            raise Truot("không có ADMIN_PASSWORD: run.sh không thoát sau 15 s") from None
    finally:
        m.dung(p)
    can(p.returncode != 0, "không có ADMIN_PASSWORD mà run.sh thoát 0")


@dataclass(frozen=True)
class Ca:
    id: str
    must: str
    mo_ta: str
    chay: Callable[[May], None]


CA = (
    Ca("C01", "M-01", "trang chủ: lang vi, tên tổ chức, liên kết đăng ký", c01),
    Ca("C02", "M-02", "giới thiệu có ≥ 2 <h2>", c02),
    Ca("C03", "M-03", "form đủ trường, select 4 giá trị, checkbox, label for", c03),
    Ca("C04", "M-04", "đăng ký hợp lệ → 201 Cảm ơn", c04),
    Ca("C05", "M-05", "họ tên 1 ký tự → 422, hiện lại form, giữ giá trị", c05),
    Ca("C06", "M-05", "số điện thoại sai → 422", c06),
    Ca("C07", "M-05", "email sai → 422", c07),
    Ca("C08", "M-05", "khu vực lạ → 422", c08),
    Ca("C09", "M-05", "lý do 501 ký tự → 422", c09),
    Ca("C10", "M-05", "biên: lý do 500 ký tự + số có dấu chấm/khoảng trắng → 201", c10),
    Ca("C11", "M-06", "thiếu dong_y → 422, không lưu", c11),
    Ca("C12", "M-05", "dữ liệu sai không được lưu", c12),
    Ca("C13", "M-07", "trùng số (dạng +84) → 409, không lưu bản thứ hai", c13),
    Ca("C14", "M-08", "form báo lỗi escape HTML", c14),
    Ca("C15", "M-08", "trang quản trị escape HTML", c15),
    Ca("C16", "M-10", "quản trị: 401 khi thiếu/sai mật khẩu, 200 khi đúng", c16),
    Ca("C17", "M-11", "CSV: text/csv, UTF-8, chống chèn công thức", c17),
    Ca("C18", "M-12", "404 là trang HTML lang vi", c18),
    Ca("C19", "M-12", "POST > 10 KB → 413", c19),
    Ca("C20", "M-12", "header CSP + nosniff trên mọi trang HTML", c20),
    Ca("C21", "M-04", "lưu bền qua lần chạy lại", c21),
    Ca("C22", "M-09", "log không có dữ liệu cá nhân", c22),
    Ca("C23", "M-10", "thiếu ADMIN_PASSWORD thì run.sh không chạy", c23),
)


# ---------- chấm ----------


def _cong_trong() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _chay(repo: Path, lenh: list[str], gioi_han: float) -> dict[str, Any]:
    t = time.monotonic()
    try:
        r = subprocess.run(lenh, cwd=repo, capture_output=True, timeout=gioi_han, check=False)
        ma: int | None = r.returncode
    except subprocess.TimeoutExpired:
        ma = None
    return {"exit": ma, "giay": round(time.monotonic() - t, 1)}


def _commit(repo: Path) -> str | None:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=False)
    return r.stdout.strip() or None


def cham(repo: Path, *, port: int | None = None, cho: float = 60, setup: bool = True,
         gioi_han: float = 900) -> dict[str, Any]:
    """Chấm `repo` theo đề bài; trả kết quả cho `do_hai_khung.py bao-cao` (trường `nghiem_thu` của file lượt)."""
    canh_bao: list[str] = []
    tam = Path(tempfile.mkdtemp(prefix="nghiem-thu-"))
    m = May(repo=repo, port=port or _cong_trong(), mat_khau=secrets.token_urlsafe(12), data=tam / "data",
            log=tam / "run.log", canh_bao=canh_bao, cho=cho)
    kq_setup = None
    if (repo / "setup.sh").is_file():
        kq_setup = _chay(repo, m.lenh("setup.sh"), gioi_han) if setup else None
    else:
        canh_bao.append("hợp đồng: thiếu setup.sh")
    ca: list[dict[str, Any]] = []
    khoi_dong = (repo / "run.sh").is_file() and m.len(cho)
    for c in CA:
        dat, ghi = False, "máy chủ không lên (run.sh thiếu, thoát, hoặc không nghe cổng)"
        if khoi_dong:
            try:
                c.chay(m)
                dat, ghi = True, ""
            except Truot as e:
                ghi = str(e)
            except (OSError, http.client.HTTPException, KeyError, ValueError) as e:
                ghi = f"{type(e).__name__}: {e}"
        ca.append({"id": c.id, "must": c.must, "mo_ta": c.mo_ta, "dat": dat, "ghi_chu": ghi})
    m.dung()
    if (repo / "test.sh").is_file():
        test_sh = _chay(repo, m.lenh("test.sh"), gioi_han)
    else:
        test_sh = {"exit": None, "giay": 0}
        canh_bao.append("hợp đồng: thiếu test.sh")
    must = {k: all(c["dat"] for c in ca if c["must"] == k) for k in MUST}
    return {"de_bai": DE_BAI, "repo": str(repo), "commit": _commit(repo), "setup": kq_setup,
            "khoi_dong": khoi_dong, "ca": ca, "must": must, "must_dat": sum(must.values()), "must_tong": len(MUST),
            "ca_dat": sum(c["dat"] for c in ca), "ca_tong": len(ca), "test_sh": test_sh, "log": str(m.log),
            "canh_bao": canh_bao}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="nghiem_thu_dhcb", description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True, help="repo khung làm ra, đã checkout đúng commit cần chấm")
    ap.add_argument("--port", type=int, help="mặc định: một cổng trống")
    ap.add_argument("--cho", type=float, default=60, help="giây chờ máy chủ lên (mặc định 60)")
    ap.add_argument("--khong-setup", action="store_true", help="bỏ qua setup.sh (đã cài rồi)")
    ap.add_argument("--out", help="ghi JSON ra file thay vì stdout")
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()
    if not repo.is_dir():
        print(f"nghiem_thu_dhcb: {repo}: không phải thư mục", file=sys.stderr)
        return 2
    kq = cham(repo, port=a.port, cho=a.cho, setup=not a.khong_setup)
    s = json.dumps(kq, ensure_ascii=False, indent=2) + "\n"
    if a.out:
        Path(a.out).write_text(s, encoding="utf-8")
    else:
        sys.stdout.write(s)
    print(f"{kq['must_dat']}/{kq['must_tong']} Must, {kq['ca_dat']}/{kq['ca_tong']} ca", file=sys.stderr)
    return 0 if kq["must_dat"] == kq["must_tong"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
