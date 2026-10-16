"""Bản mẫu làm ĐÚNG đề bài DHCB-B1 v1 (`docs/do-hai-khung/DE-BAI.md`) — chỉ để test chính bộ nghiệm thu ẩn.

`MAU_LOI` (danh sách cách nhau bởi dấu phẩy) cài lỗi có chủ đích, mỗi lỗi phá đúng một Must, để đo hai chiều: bản
đúng phải đạt 12/12, bản cài lỗi phải trượt đúng Must đó và không kéo Must khác trượt theo.
"""

from __future__ import annotations

import base64
import csv
import html
import io
import os
import re
import sqlite3
import sys
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

LOI = set(filter(None, os.environ.get("MAU_LOI", "").split(",")))
KHU_VUC = {"ha-noi": "Hà Nội", "tp-hcm": "TP. Hồ Chí Minh", "da-nang": "Đà Nẵng", "khac": "Khác"}
SDT = re.compile(r"^(?:0|\+84)([35789]\d{8})$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TRUONG = ("ho_ten", "so_dien_thoai", "email", "khu_vuc", "ly_do")
e = (lambda s: s) if "xss" in LOI else html.escape

MAT_KHAU = os.environ.get("ADMIN_PASSWORD") or ("admin" if "mat_khau_mac_dinh" in LOI else "")
if not MAT_KHAU:
    print("thiếu ADMIN_PASSWORD — không chạy", file=sys.stderr)
    raise SystemExit(1)

if "khong_luu" in LOI:
    DB = sqlite3.connect(":memory:", check_same_thread=False)
else:
    thu_muc = Path(os.environ.get("DATA_DIR", "./data"))
    thu_muc.mkdir(parents=True, exist_ok=True)
    DB = sqlite3.connect(thu_muc / "dhcb.sqlite", check_same_thread=False)
DB.execute("CREATE TABLE IF NOT EXISTS dk (ho_ten, so_dien_thoai UNIQUE, email, khu_vuc, ly_do, thoi_diem)")
KHOA = threading.Lock()


def trang(tieu_de: str, than: str) -> str:
    return (f'<!doctype html><html lang="vi"><head><meta charset="utf-8"><title>{tieu_de}</title></head><body>'
            '<nav><a href="/">Trang chủ</a> <a href="/gioi-thieu">Giới thiệu</a> <a href="/dang-ky">Đăng ký</a></nav>'
            f"{than}</body></html>")


def form(gia_tri: dict[str, str], loi: list[str]) -> str:
    g = {k: e(gia_tri.get(k, "")) for k in TRUONG}
    chon = "".join(f'<option value="{k}"{" selected" if gia_tri.get("khu_vuc") == k else ""}>{v}</option>'
                   for k, v in KHU_VUC.items())
    bao = "".join(f'<p class="loi">{x}</p>' for x in loi)
    return (f'<h1>Đăng ký tình nguyện viên</h1>{bao}<form method="post" action="/dang-ky">'
            f'<label for="ho_ten">Họ tên</label><input id="ho_ten" name="ho_ten" value="{g["ho_ten"]}" required>'
            f'<label for="sdt">Số điện thoại</label><input id="sdt" name="so_dien_thoai" '
            f'value="{g["so_dien_thoai"]}" required>'
            f'<label for="email">Email</label><input id="email" name="email" type="email" value="{g["email"]}">'
            f'<label for="khu_vuc">Khu vực</label><select id="khu_vuc" name="khu_vuc" required>{chon}</select>'
            f'<label for="ly_do">Lý do</label><textarea id="ly_do" name="ly_do" maxlength="500">{g["ly_do"]}</textarea>'
            '<input id="dong_y" name="dong_y" type="checkbox" required><label for="dong_y">Tôi đồng ý</label>'
            "<button>Gửi</button></form>")


def kiem(d: dict[str, str]) -> tuple[list[str], str]:
    loi = []
    if not 2 <= len(d.get("ho_ten", "").strip()) <= 100:
        loi.append("Họ tên phải dài 2–100 ký tự")
    m = SDT.match(re.sub(r"[\s.\-]", "", d.get("so_dien_thoai", "")))
    if not m:
        loi.append("Số điện thoại không hợp lệ")
    if d.get("email") and not EMAIL.match(d["email"]):
        loi.append("Email không hợp lệ")
    if d.get("khu_vuc") not in KHU_VUC:
        loi.append("Khu vực không hợp lệ")
    if len(d.get("ly_do", "")) > 500:
        loi.append("Lý do tối đa 500 ký tự")
    if "dong_y" not in d:
        loi.append("Cần đồng ý cho tổ chức lưu thông tin")
    return loi, ("0" + m.group(1)) if m else ""


def o_csv(v: str) -> str:
    return v if "csv_cong_thuc" in LOI or v[:1] not in "=+-@" else "'" + v


class XuLy(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        """Không ghi dòng truy cập mặc định."""

    def gui(self, ma: int, than: str, loai: str = "text/html; charset=utf-8") -> None:
        b = than.encode("utf-8")
        self.send_response(ma)
        self.send_header("Content-Type", loai)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Content-Security-Policy", "default-src 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(b)

    def la_quan_tri(self) -> bool:
        mong = "Basic " + base64.b64encode(f"admin:{MAT_KHAU}".encode()).decode()
        if self.headers.get("Authorization") == mong:
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="quan-tri"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def do_GET(self) -> None:
        if self.path == "/":
            self.gui(200, trang("Đồng Hành Cùng Bạn", '<h1>Đồng Hành Cùng Bạn</h1><p>Kết nối tình nguyện viên.</p>'
                                '<a href="/dang-ky">Đăng ký tình nguyện viên</a>'))
        elif self.path == "/gioi-thieu":
            self.gui(200, trang("Giới thiệu", "<h1>Giới thiệu</h1><h2>Về tổ chức</h2><p>…</p>"
                                "<h2>Hoạt động chính</h2><p>…</p>"))
        elif self.path == "/dang-ky":
            self.gui(200, trang("Đăng ký", form({}, [])))
        elif self.path in ("/quan-tri/dang-ky", "/quan-tri/dang-ky.csv"):
            if not self.la_quan_tri():
                return
            with KHOA:
                hang = DB.execute("SELECT * FROM dk ORDER BY rowid").fetchall()
            if self.path.endswith(".csv"):
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(["ho_ten", "so_dien_thoai", "email", "khu_vuc", "ly_do", "thoi_diem"])
                w.writerows([o_csv(str(x)) for x in h] for h in hang)
                self.gui(200, buf.getvalue(), "text/csv; charset=utf-8")
            else:
                dong = "".join(f"<tr><td>{e(h[0])}</td><td>{e(h[1])}</td><td>{e(KHU_VUC[h[3]])}</td>"
                               f"<td>{e(h[5])}</td></tr>" for h in hang)
                self.gui(200, trang("Quản trị", f"<table>{dong}</table>"))
        else:
            self.gui(404, trang("Không tìm thấy", "<h1>Không tìm thấy trang</h1>"))

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length") or 0)
        if self.path != "/dang-ky":
            self.gui(404, trang("Không tìm thấy", "<h1>Không tìm thấy trang</h1>"))
            return
        if n > 10 * 1024 and "khong_413" not in LOI:
            self.gui(413, trang("Quá lớn", "<h1>Dữ liệu quá lớn</h1>"))
            return
        d = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True).items()}
        loi, sdt = kiem(d)
        if loi:
            self.gui(422, trang("Đăng ký", form(d, loi)))
            return
        if "log_pii" in LOI:
            print(f"đăng ký: {d['ho_ten']} {sdt} {d.get('email', '')}", flush=True)
        else:
            print("đăng ký mới", flush=True)
        with KHOA:
            if "trung_sdt" not in LOI and DB.execute("SELECT 1 FROM dk WHERE so_dien_thoai = ?", (sdt,)).fetchone():
                self.gui(409, trang("Đã đăng ký", form(d, ["Số điện thoại này đã đăng ký"])))
                return
            if "trung_sdt" in LOI:  # bảng có UNIQUE: lỗi này ghi đè bản cũ thay vì báo trùng
                DB.execute("DELETE FROM dk WHERE so_dien_thoai = ?", (sdt,))
            DB.execute("INSERT INTO dk VALUES (?,?,?,?,?,?)", (d["ho_ten"].strip(), sdt, d.get("email", ""),
                                                               d["khu_vuc"], d.get("ly_do", ""),
                                                               datetime.now(UTC).isoformat(timespec="seconds")))
            DB.commit()
        self.gui(201, trang("Cảm ơn", "<h1>Cảm ơn bạn đã đăng ký!</h1>"))


ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "8000"))), XuLy).serve_forever()
