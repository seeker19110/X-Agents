#!/usr/bin/env python3
"""Gom token của một lượt đo hai khung về MỘT khuôn, rồi dựng báo cáo so sánh (`docs/do-hai-khung/README.md`).

Hai nguồn, hai cách ghi khác nhau, nên mới cần lớp quy đổi này:

- X-Templates chạy trong một phiên Claude Code: transcript JSONL dưới `~/.claude/projects/<thư mục>/`, cả subagent ở
  `<phiên>/subagents/*.jsonl`. Một tin nhắn ghi thành nhiều dòng cùng `message.id`, `output_tokens` tăng dần qua các
  dòng (đo trên phiên thật 2026-10-16) → lấy LỚN NHẤT mỗi trường theo `message.id`, không cộng dòng.
  `input_tokens` ở đây KHÔNG gồm phần cache.
- X-Agents gọi `claude -p --no-session-persistence` nên không để lại transcript; số đo nằm trong `audit-log` của bus
  SQLite. `tokens` = input (ĐÃ gồm đọc + ghi cache) + output; phần cache chỉ tách được ở `produced:*` (R1, audit
  token 2026-10-10). Lượt lỗi chỉ có tổng → `khong_tach`. Reviewer tự động ghi token khi `hold`, KHÔNG ghi khi
  `approve`/`reject` → đếm thành `luot_khong_do` và báo số chưa đủ, không lặng lẽ thiếu.

Thiếu giá thì không in 0 USD: QLKH từng ghi 137 318 818 token với "0,0000 USD" vì không có bảng giá (`TRAPS.md`).
Chỉ thư viện chuẩn — chạy được trên máy đo không có `uv`.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

LOAI = ("input", "cache_ghi_5m", "cache_ghi_1h", "cache_ghi", "cache_doc", "output", "khong_tach")
KHUNG = ("x-agents", "x-templates")
HOLD = ("reviewer.hold", "reviewer.cr_hold")
MUST = tuple(f"M-{i:02d}" for i in range(1, 13))


def _o() -> dict[str, int]:
    return {**dict.fromkeys(LOAI, 0), "luot": 0}


def _cong(mo_hinh: dict[str, dict[str, int]]) -> dict[str, int]:
    tong = _o()
    for o in mo_hinh.values():
        for k in tong:
            tong[k] += o[k]
    return tong


def _thoi_diem(s: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _khoang_giay(moc: list[datetime]) -> int | None:
    return round((max(moc) - min(moc)).total_seconds()) if moc else None


# ---------- X-Templates: transcript Claude Code ----------


def doc_claude_jsonl(goc: Path) -> dict[str, Any]:
    """Cộng usage mọi tin nhắn model trong `goc` (đệ quy, gồm subagent). Không có transcript nào là lỗi, không phải 0."""
    tep = sorted(goc.rglob("*.jsonl"))
    if not tep:
        raise ValueError(f"{goc}: không có transcript *.jsonl nào — sai thư mục dự án, hoặc phiên đã xoá")
    tin: dict[tuple[str, str], dict[str, int]] = {}   # (model, id) → giá trị lớn nhất mỗi trường
    moc: list[datetime] = []
    canh_bao: list[str] = []
    for f in tep:
        for so, dong in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not dong.strip():
                continue
            try:
                d = json.loads(dong)
            except json.JSONDecodeError:
                canh_bao.append(f"{f.name}:{so}: dòng không phải JSON — bỏ qua")
                continue
            if (t := _thoi_diem(d.get("timestamp"))) is not None:
                moc.append(t)
            m = d.get("message") if d.get("type") == "assistant" else None
            if not isinstance(m, dict) or m.get("model") == "<synthetic>" or not isinstance(m.get("usage"), dict):
                continue
            u = m["usage"]
            ttl = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
            ghi = int(u.get("cache_creation_input_tokens") or 0)
            g5, g1 = int(ttl.get("ephemeral_5m_input_tokens") or 0), int(ttl.get("ephemeral_1h_input_tokens") or 0)
            v = {"input": int(u.get("input_tokens") or 0), "cache_ghi_5m": g5, "cache_ghi_1h": g1,
                 "cache_ghi": max(0, ghi - g5 - g1), "cache_doc": int(u.get("cache_read_input_tokens") or 0),
                 "output": int(u.get("output_tokens") or 0)}
            khoa = (str(m.get("model") or "?"), str(m.get("id") or d.get("requestId") or f"{f}:{so}"))
            cu = tin.setdefault(khoa, dict.fromkeys(v, 0))
            for k, x in v.items():
                cu[k] = max(cu[k], x)
    mo_hinh: dict[str, dict[str, int]] = defaultdict(_o)
    for (model, _), v in tin.items():
        o = mo_hinh[model]
        for k, x in v.items():
            o[k] += x
        o["luot"] += 1
    sub = sum(1 for f in tep if "subagents" in f.parts)
    return {"nguon": "claude-jsonl", "goc": str(goc), "mo_hinh": dict(sorted(mo_hinh.items())),
            "tong": _cong(mo_hinh), "tep": {"phien": len(tep) - sub, "subagent": sub},
            "thoi_gian_giay": _khoang_giay(moc), "canh_bao": canh_bao}


# ---------- X-Agents: audit-log của bus SQLite ----------


def _ev(s: Any) -> dict[str, Any]:
    try:
        d = json.loads(s or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return d if isinstance(d, dict) else {}


def doc_xagents(db: Path, du_an: str | None = None) -> dict[str, Any]:
    """Cộng token mọi bản ghi `audit-log` (cùng sổ với `company.metrics`), tách cache ở `produced:*`.

    Mở chỉ đọc qua URI `mode=ro`: đường dẫn sai thì lỗi, không tạo sổ rỗng rồi in toàn số 0 (`TRAPS.md` §4)."""
    if not db.is_file():
        raise FileNotFoundError(f"{db}: không có file bus")
    mo_hinh: dict[str, dict[str, int]] = defaultdict(_o)
    nguoi: Counter[str] = Counter()
    moc: list[datetime] = []
    canh_bao: list[str] = []
    khong_do = khong_gan = 0
    with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)) as cx:
        for topic, actor, body in cx.execute("SELECT topic, actor, body FROM events ORDER BY seq"):
            env = _ev(body)
            a: dict[str, Any] = env["payload"] if isinstance(env.get("payload"), dict) else {}
            if (t := _thoi_diem(env.get("ts"))) is not None:
                moc.append(t)
            act = str(a.get("action") or "") if topic == "audit-log" else ""
            if actor.startswith("human:"):
                nguoi[f"{topic}:{act}" if act else topic] += 1
            if actor.startswith("reviewer:") and act not in HOLD and (act == "gate.decide" or topic != "audit-log"):
                khong_do += 1
            if topic != "audit-log":
                continue
            d = _ev(a.get("evidence"))
            tokens = int(a.get("tokens") or 0) or (int(d.get("tokens") or 0) if act in HOLD else 0)
            if not tokens:
                continue
            if du_an is not None and a.get("project_id") != du_an:
                khong_gan += tokens if a.get("project_id") is None else 0
                continue
            o = mo_hinh[str(d.get("model") or "?")]
            o["luot"] += 1
            out, doc, ghi = int(a.get("output_tokens") or 0), int(d.get("cached_input_tokens") or 0), \
                int(d.get("cache_write_tokens") or 0)
            if not act.startswith("produced:") or tokens - out - doc - ghi < 0:
                o["khong_tach"] += tokens
                continue
            o["input"] += tokens - out - doc - ghi
            o["output"] += out
            o["cache_doc"] += doc
            o["cache_ghi"] += ghi
    if khong_gan:
        canh_bao.append(f"{khong_gan} token không gắn dự án nào — đã loại khỏi số của {du_an}; sổ riêng mỗi lượt thì "
                        "bỏ --du-an")
    if khong_do:
        canh_bao.append(f"{khong_do} lượt reviewer tự động không ghi token — tổng THIẾU phần đó")
    return {"nguon": "x-agents", "db": str(db), "du_an": du_an, "mo_hinh": dict(sorted(mo_hinh.items())),
            "tong": _cong(mo_hinh), "nguoi": dict(nguoi), "luot_khong_do": khong_do, "day_du": khong_do == 0,
            "thoi_gian_giay": _khoang_giay(moc), "canh_bao": canh_bao}


# ---------- quy đổi USD ----------


def _gia_cua(model: str, bang: dict[str, Any]) -> dict[str, Any] | None:
    khop = [p for p in bang if model.startswith(p)]
    return bang[max(khop, key=len)] if khop else None


def tinh_usd(mo_hinh: dict[str, dict[str, int]], gia: dict[str, Any]) -> tuple[float | None, list[str]]:
    """USD quy đổi theo bảng giá (USD / 1 triệu token). Mô hình nào thiếu giá → `None` + tên nó, không coi là 0.

    `cache_ghi` (TTL không rõ, nguồn X-Agents) tính theo giá ghi 5 phút; `khong_tach` theo giá input — cả hai là
    cận dưới, báo cáo nói rõ."""
    bang = gia.get("usd_moi_trieu_token") or {}
    tong, thieu = 0.0, []
    for model, o in mo_hinh.items():
        g = _gia_cua(model, bang)
        cot = {"input": "input", "cache_ghi_5m": "cache_ghi_5m", "cache_ghi_1h": "cache_ghi_1h",
               "cache_ghi": "cache_ghi_5m", "cache_doc": "cache_doc", "output": "output", "khong_tach": "input"}
        can = {cot[k] for k in LOAI if o[k]}
        if g is None or any(g.get(c) is None for c in can):
            thieu.append(model)
            continue
        tong += sum(o[k] * float(g[cot[k]]) for k in LOAI if o[k]) / 1_000_000
    return (None, thieu) if thieu else (round(tong, 4), [])


# ---------- báo cáo ----------


def _so(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ") if float(x).is_integer() else f"{x:,.2f}".replace(",", " ").replace(".", ",")


def _tv(xs: list[float], fmt: Any = _so, hau_to: str = "") -> str:
    """Trung vị (nhỏ nhất–lớn nhất); `hau_to` chỉ gắn sau trung vị (vd `/12`)."""
    if not xs:
        return "—"
    return f"{fmt(statistics.median(xs))}{hau_to} ({fmt(min(xs))}–{fmt(max(xs))})"


def _usd(v: float) -> str:
    return f"{v:.2f}".replace(".", ",") + " USD"


def _nt(x: dict[str, Any]) -> Any:
    """Kết quả nghiệm thu ẩn của lượt, `None` khi chưa chấm."""
    return x.get("nghiem_thu")


def bao_cao(luot: list[dict[str, Any]], gia: dict[str, Any] | None) -> str:
    """Bảng Markdown: trung vị (min–max) mỗi khung qua các lượt, rồi ma trận Must đạt và cảnh báo của từng lượt."""
    khung = [k for k in KHUNG if any(x["khung"] == k for x in luot)]
    nhom = {k: [x for x in luot if x["khung"] == k] for k in khung}

    def cot(fn: Any, hau_to: str = "") -> list[str]:
        return [_tv([v for x in nhom[k] if (v := fn(x)) is not None], hau_to=hau_to) for k in khung]

    def tok(loai: tuple[str, ...]) -> Any:
        return lambda x: sum(x["token"]["tong"][t] for t in loai)

    dong: list[tuple[str, list[str]]] = [
        ("Số lượt chạy", [str(len(nhom[k])) for k in khung]),
        ("Token tổng (mọi loại)", cot(tok(LOAI))),
        ("Input không cache", cot(tok(("input",)))),
        ("Ghi cache", cot(tok(("cache_ghi_5m", "cache_ghi_1h", "cache_ghi")))),
        ("Đọc cache", cot(tok(("cache_doc",)))),
        ("Output", cot(tok(("output",)))),
        ("Không tách được", cot(tok(("khong_tach",)))),
        ("Lời gọi / bước có token", cot(lambda x: x["token"]["tong"]["luot"])),
        ("Thời gian (phút)", cot(lambda x: (x.get("thoi_gian_giay") or x["token"].get("thoi_gian_giay") or 0) / 60)),
        ("Can thiệp của người (lần)", cot(lambda x: len(x.get("can_thiep") or []))),
        ("Can thiệp của người (phút)", cot(lambda x: sum(float(c.get("phut") or 0) for c in x.get("can_thiep") or []))),
        ("Must đạt (nghiệm thu ẩn)", cot(lambda x: _nt(x)["must_dat"] if _nt(x) else None, "/12")),
        ("Ca đạt (nghiệm thu ẩn)", cot(lambda x: _nt(x)["ca_dat"] if _nt(x) else None)),
        ("`test.sh` của dự án xanh", cot(lambda x: (_nt(x)["test_sh"]["exit"] == 0) * 1 if _nt(x) else None)),
    ]
    usd_cot = []
    for k in khung:
        xs, thieu = [], set()
        for x in nhom[k]:
            usd, t = tinh_usd(x["token"]["mo_hinh"], gia or {})
            thieu.update(t)
            if usd is not None:
                xs.append(usd)
        usd_cot.append(f"thiếu giá: {', '.join(sorted(thieu))}" if thieu else _tv(xs, _usd))
    dong.insert(7, ("USD quy đổi (cận dưới)", usd_cot))
    hang = ["| Chỉ số | " + " | ".join(khung) + " |", "|---|" + "---:|" * len(khung)]
    hang += [f"| {ten} | " + " | ".join(gt) + " |" for ten, gt in dong]
    hang += ["", "Trung vị (nhỏ nhất–lớn nhất) qua các lượt. `test.sh` xanh: 1 = xanh, 0 = đỏ.", "",
             "### Must đạt theo lượt", "", "| Must | " + " | ".join(khung) + " |", "|---|" + "---:|" * len(khung)]
    for m in MUST:
        o = []
        for k in khung:
            cham = [x for x in nhom[k] if _nt(x)]
            o.append(f"{sum(1 for x in cham if _nt(x)['must'].get(m))}/{len(cham)}")
        hang.append(f"| {m} | " + " | ".join(o) + " |")
    hang += ["", "### Từng lượt", ""]
    for x in luot:
        ket = (f"{_nt(x)['must_dat']}/{_nt(x)['must_tong']} Must" if _nt(x) else "**chưa chấm nghiệm thu**")
        hang.append(f"- {x['khung']} lần {x['lan']}: kết cục `{x.get('ket_cuc', '?')}`, khung tự khai xong "
                    f"`{x.get('khai_xong')}`, {ket}")
        hang += [f"  - cảnh báo: {c}" for c in x["token"].get("canh_bao") or []]
    if gia:
        hang += ["", f"Bảng giá: {gia.get('ngay', '?')} — {gia.get('nguon', '?')}"]
    return "\n".join(hang) + "\n"


# ---------- CLI ----------


def ghep(khung: str, lan: int, token: dict[str, Any], nghiem_thu: dict[str, Any] | None, ket_cuc: str,
         khai_xong: bool, can_thiep: list[str]) -> dict[str, Any]:
    """Một file lượt (`luot.example.json`) từ output của `claude-jsonl`/`xagents` và `nghiem_thu_dhcb.py`.

    `can_thiep` mỗi phần tử dạng `phút:việc` — mỗi lần người chạm vào lượt chạy, kể cả duyệt gate theo câu cố định."""
    ct = []
    for c in can_thiep:
        phut, _, viec = c.partition(":")
        try:
            ct.append({"phut": float(phut), "viec": viec.strip()})
        except ValueError:
            raise ValueError(f"--can-thiep {c!r}: cần dạng phút:việc, vd 2:duyệt gate spec") from None
        if not viec.strip():
            raise ValueError(f"--can-thiep {c!r}: cần dạng phút:việc, thiếu việc")
    return {"khung": khung, "lan": lan, "ket_cuc": ket_cuc, "khai_xong": khai_xong, "can_thiep": ct,
            "thoi_gian_giay": token.get("thoi_gian_giay"), "token": token, "nghiem_thu": nghiem_thu}



def _ghi(kq: dict[str, Any], out: str | None) -> None:
    s = json.dumps(kq, ensure_ascii=False, indent=2) + "\n"
    if out:
        Path(out).write_text(s, encoding="utf-8")
    else:
        sys.stdout.write(s)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="do_hai_khung", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="lenh", required=True)
    cj = sub.add_parser("claude-jsonl", help="token của phiên Claude Code (X-Templates) từ thư mục transcript")
    cj.add_argument("goc"); cj.add_argument("--out")
    xa = sub.add_parser("xagents", help="token của X-Agents từ audit-log của company.sqlite")
    xa.add_argument("db"); xa.add_argument("--du-an"); xa.add_argument("--out")
    gh = sub.add_parser("ghep", help="ghép token + nghiệm thu + can thiệp thành một file lượt")
    gh.add_argument("--khung", required=True, choices=KHUNG); gh.add_argument("--lan", required=True, type=int)
    gh.add_argument("--token", required=True); gh.add_argument("--nghiem-thu")
    gh.add_argument("--ket-cuc", required=True, help="done | done-pending-human | blocked | budget | het-gio | ...")
    gh.add_argument("--khai-xong", required=True, choices=("co", "khong"), help="khung có tự khai đã xong không")
    gh.add_argument("--can-thiep", action="append", default=[], help="phút:việc — lặp lại cho mỗi lần")
    gh.add_argument("--out")
    bc = sub.add_parser("bao-cao", help="báo cáo Markdown từ các file lượt (luot.json)")
    bc.add_argument("luot", nargs="+"); bc.add_argument("--gia")
    a = ap.parse_args(argv)
    try:
        if a.lenh == "claude-jsonl":
            _ghi(doc_claude_jsonl(Path(a.goc)), a.out)
        elif a.lenh == "xagents":
            _ghi(doc_xagents(Path(a.db), a.du_an), a.out)
        elif a.lenh == "ghep":
            doc = lambda f: json.loads(Path(f).read_text(encoding="utf-8"))  # noqa: E731
            _ghi(ghep(a.khung, a.lan, doc(a.token), doc(a.nghiem_thu) if a.nghiem_thu else None, a.ket_cuc,
                      a.khai_xong == "co", a.can_thiep), a.out)
        else:
            gia = json.loads(Path(a.gia).read_text(encoding="utf-8")) if a.gia else None
            luot = [json.loads(Path(f).read_text(encoding="utf-8")) for f in a.luot]
            sys.stdout.write(bao_cao(luot, gia))
    except (OSError, ValueError) as e:
        print(f"do_hai_khung: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
