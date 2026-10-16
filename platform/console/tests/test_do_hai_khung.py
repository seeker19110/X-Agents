"""`scripts/do_hai_khung.py` — gom token của một lượt đo hai khung (`docs/do-hai-khung/README.md`).

Sổ X-Agents dựng bằng bus/payload thật của software-company (cùng cách `conftest.py`), không viết SQL tay: định dạng
sổ đổi thì test này đỏ trước khi số đo sai. Transcript Claude Code dựng theo đúng hình dạng đo được trên phiên thật
2026-10-16: một tin nhắn nhiều dòng cùng `message.id`, `output_tokens` tăng dần qua các dòng.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from company.events import AuditLog, Envelope
from company.sqlite_bus import SQLiteBus

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.cong_repo
SCRIPT = ROOT / "scripts" / "do_hai_khung.py"


def _load():
    spec = importlib.util.spec_from_file_location("do_hai_khung", SCRIPT)
    assert spec and spec.loader, f"Không tải được script {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["do_hai_khung"] = module
    spec.loader.exec_module(module)
    return module


# ---------- transcript Claude Code (X-Templates) ----------


def _dong(mid: str, model: str, *, inp: int, out: int, doc: int, ghi: int, ts: str, ttl: dict | None = None) -> str:
    usage = {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": doc,
             "cache_creation_input_tokens": ghi}
    if ttl is not None:
        usage["cache_creation"] = ttl
    return json.dumps({"type": "assistant", "timestamp": ts, "requestId": f"req_{mid}",
                       "message": {"id": mid, "model": model, "usage": usage}})


def _phien(goc: Path) -> Path:
    goc.mkdir(parents=True, exist_ok=True)
    phien = goc / "abc.jsonl"
    phien.write_text("\n".join([
        json.dumps({"type": "user", "timestamp": "2026-10-16T01:00:00Z", "message": {"content": "/autopilot"}}),
        # cùng một tin nhắn, ba dòng: lấy lớn nhất mỗi trường, không cộng ba lần
        _dong("m1", "claude-opus-5-5", inp=2, out=7, doc=1000, ghi=500, ts="2026-10-16T01:00:05Z",
              ttl={"ephemeral_1h_input_tokens": 500, "ephemeral_5m_input_tokens": 0}),
        _dong("m1", "claude-opus-5-5", inp=2, out=300, doc=1000, ghi=500, ts="2026-10-16T01:00:06Z",
              ttl={"ephemeral_1h_input_tokens": 500, "ephemeral_5m_input_tokens": 0}),
        _dong("m1", "claude-opus-5-5", inp=2, out=300, doc=1000, ghi=500, ts="2026-10-16T01:00:06Z",
              ttl={"ephemeral_1h_input_tokens": 500, "ephemeral_5m_input_tokens": 0}),
        "{dòng hỏng không phải JSON",
        # tin nhắn tổng hợp của CLI, không phải lời gọi model
        _dong("m0", "<synthetic>", inp=0, out=0, doc=0, ghi=0, ts="2026-10-16T01:00:07Z"),
        # không có tách TTL → vào `cache_ghi` (TTL không rõ)
        _dong("m2", "claude-opus-5-5", inp=10, out=40, doc=2000, ghi=100, ts="2026-10-16T01:30:00Z"),
    ]) + "\n", encoding="utf-8")
    sub = goc / "abc" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-1.jsonl").write_text(
        _dong("s1", "claude-sonnet-5-5", inp=5, out=60, doc=300, ghi=0, ts="2026-10-16T01:10:00Z") + "\n",
        encoding="utf-8")
    return goc


def test_claude_jsonl_lay_lon_nhat_moi_truong_cua_mot_tin_nhan(tmp_path: Path) -> None:
    kq = _load().doc_claude_jsonl(_phien(tmp_path))
    opus = kq["mo_hinh"]["claude-opus-5-5"]
    assert opus == {"input": 12, "cache_ghi_5m": 0, "cache_ghi_1h": 500, "cache_ghi": 100, "cache_doc": 3000,
                    "output": 340, "khong_tach": 0, "luot": 2}


def test_claude_jsonl_tinh_ca_subagent_va_bo_tin_nhan_tong_hop(tmp_path: Path) -> None:
    kq = _load().doc_claude_jsonl(_phien(tmp_path))
    assert set(kq["mo_hinh"]) == {"claude-opus-5-5", "claude-sonnet-5-5"}
    assert kq["mo_hinh"]["claude-sonnet-5-5"]["output"] == 60
    assert kq["tep"] == {"phien": 1, "subagent": 1}
    assert kq["tong"]["luot"] == 3


def test_claude_jsonl_do_thoi_gian_tu_dong_dau_toi_dong_cuoi(tmp_path: Path) -> None:
    kq = _load().doc_claude_jsonl(_phien(tmp_path))
    assert kq["thoi_gian_giay"] == 30 * 60


def test_claude_jsonl_bao_dong_hong_khong_nuot_im(tmp_path: Path) -> None:
    kq = _load().doc_claude_jsonl(_phien(tmp_path))
    assert any("không phải JSON" in c for c in kq["canh_bao"])


def test_claude_jsonl_thu_muc_rong_la_loi_khong_phai_so_0(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="không có transcript"):
        _load().doc_claude_jsonl(tmp_path)


# ---------- sổ audit-log X-Agents ----------


def _audit(bus: SQLiteBus, actor: str, action: str, *, tokens: int = 0, evidence: str = "", **ids) -> None:
    payload = AuditLog(actor=actor, action=action, tokens=tokens, evidence=evidence, **ids)
    bus.publish(Envelope(topic="audit-log", key=actor, actor=actor, payload=payload.model_dump()))


def _so(path: Path) -> Path:
    bus = SQLiteBus(path)
    ev = {"model": "claude-opus-5", "cached_input_tokens": 60_000, "cache_write_tokens": 5_000, "num_turns": 3}
    _audit(bus, "builder", "produced:pull-requests", tokens=80_000, output_tokens=9_000,
           evidence=json.dumps(ev), ticket_id="B1-1", project_id="B1")
    ev2 = {"model": "claude-sonnet-5", "cached_input_tokens": 0, "cache_write_tokens": 0}
    _audit(bus, "qa", "produced:review-results", tokens=20_000, output_tokens=1_000,
           evidence=json.dumps(ev2), ticket_id="B1-1", project_id="B1")
    # lượt lỗi: có token nhưng không tách được input/output/cache
    _audit(bus, "builder", "llm_error", tokens=7_000, evidence="TransientError: quá tải", project_id="B1")
    # dự án khác trong cùng sổ
    _audit(bus, "qa", "produced:review-results", tokens=99_999, output_tokens=1, evidence=json.dumps(ev2),
           project_id="KHAC")
    # reviewer tự động: hold có ghi token trong evidence; decide thì không ghi token nào
    _audit(bus, "reviewer:tu-dong", "reviewer.hold", evidence=json.dumps({"tokens": 15_000, "model": "claude-opus-5"}))
    _audit(bus, "reviewer:tu-dong", "gate.decide", evidence=json.dumps({"subject_id": "SPEC-B1"}))
    # người: một lần duyệt gate
    _audit(bus, "human:do", "gate.decide", evidence=json.dumps({"subject_id": "REL-001"}))
    bus.close()
    return path


def test_xagents_tach_input_khong_cache_tu_tong_token(tmp_path: Path) -> None:
    kq = _load().doc_xagents(_so(tmp_path / "company.sqlite"), du_an="B1")
    opus = kq["mo_hinh"]["claude-opus-5"]
    # 80 000 = input (không cache) + 60 000 đọc cache + 5 000 ghi cache + 9 000 output
    assert opus == {"input": 6_000, "cache_ghi_5m": 0, "cache_ghi_1h": 0, "cache_ghi": 5_000, "cache_doc": 60_000,
                    "output": 9_000, "khong_tach": 0, "luot": 1}


def test_xagents_luot_loi_vao_khong_tach_chu_khong_mat(tmp_path: Path) -> None:
    kq = _load().doc_xagents(_so(tmp_path / "company.sqlite"), du_an="B1")
    assert kq["mo_hinh"]["?"]["khong_tach"] == 7_000


def test_xagents_loc_du_an_va_bao_phan_khong_gan_du_an(tmp_path: Path) -> None:
    kq = _load().doc_xagents(_so(tmp_path / "company.sqlite"), du_an="B1")
    assert kq["tong"]["output"] == 10_000          # không có 1 token của dự án KHAC
    assert any("không gắn dự án" in c for c in kq["canh_bao"])


def test_xagents_khong_loc_thi_tinh_ca_hold_cua_reviewer(tmp_path: Path) -> None:
    kq = _load().doc_xagents(_so(tmp_path / "company.sqlite"))
    assert kq["mo_hinh"]["claude-opus-5"]["khong_tach"] == 15_000


def test_xagents_dem_luot_reviewer_khong_do_duoc_va_bao_so_chua_du(tmp_path: Path) -> None:
    kq = _load().doc_xagents(_so(tmp_path / "company.sqlite"))
    assert kq["luot_khong_do"] == 1
    assert kq["day_du"] is False


def test_xagents_dem_can_thiep_cua_nguoi(tmp_path: Path) -> None:
    kq = _load().doc_xagents(_so(tmp_path / "company.sqlite"))
    assert kq["nguoi"] == {"audit-log:gate.decide": 1}


def test_xagents_so_chua_co_la_loi_khong_tao_so_rong(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _load().doc_xagents(tmp_path / "khong-co.sqlite")
    assert not (tmp_path / "khong-co.sqlite").exists()


# ---------- quy đổi USD ----------

GIA = {"ngay": "2026-10-16", "nguon": "https://example.invalid/gia",
       "usd_moi_trieu_token": {"claude-opus": {"input": 10.0, "cache_ghi_5m": 12.5, "cache_ghi_1h": 20.0,
                                               "cache_doc": 1.0, "output": 50.0}}}


def test_usd_theo_tien_to_dai_nhat_va_tung_loai_token() -> None:
    mo_hinh = {"claude-opus-5-5": {"input": 1_000_000, "cache_ghi_5m": 0, "cache_ghi_1h": 1_000_000, "cache_ghi": 0,
                                   "cache_doc": 1_000_000, "output": 1_000_000, "khong_tach": 0, "luot": 1}}
    usd, thieu = _load().tinh_usd(mo_hinh, GIA)
    assert (usd, thieu) == (pytest.approx(81.0), [])


def test_usd_mo_hinh_khong_co_gia_thi_bao_ten_khong_tinh_0() -> None:
    mo_hinh = {"claude-sonnet-5": {"input": 1_000_000, "cache_ghi_5m": 0, "cache_ghi_1h": 0, "cache_ghi": 0,
                                   "cache_doc": 0, "output": 0, "khong_tach": 0, "luot": 1}}
    usd, thieu = _load().tinh_usd(mo_hinh, GIA)
    assert usd is None and thieu == ["claude-sonnet-5"]


def test_usd_bang_gia_con_null_la_chua_co_gia() -> None:
    gia = {"usd_moi_trieu_token": {"claude-opus": {"input": None, "cache_ghi_5m": None, "cache_ghi_1h": None,
                                                   "cache_doc": None, "output": None}}}
    mo_hinh = {"claude-opus-5": {"input": 1, "cache_ghi_5m": 0, "cache_ghi_1h": 0, "cache_ghi": 0, "cache_doc": 0,
                                 "output": 0, "khong_tach": 0, "luot": 1}}
    assert _load().tinh_usd(mo_hinh, gia) == (None, ["claude-opus-5"])


# ---------- báo cáo ----------


def _luot(khung: str, lan: int, *, output: int, must: int, phut: float) -> dict:
    tong = {"input": 1_000, "cache_ghi_5m": 0, "cache_ghi_1h": 0, "cache_ghi": 0, "cache_doc": 9_000,
            "output": output, "khong_tach": 0, "luot": 4}
    return {"khung": khung, "lan": lan, "ket_cuc": "done", "khai_xong": True,
            "can_thiep": [{"viec": "duyệt gate spec", "phut": phut}],
            "token": {"mo_hinh": {"claude-opus-5": tong}, "tong": tong, "thoi_gian_giay": 3_600, "canh_bao": []},
            "nghiem_thu": {"de_bai": "DHCB-B1 v1", "must_dat": must, "must_tong": 12, "ca_dat": 20, "ca_tong": 24,
                           "must": {f"M-{i:02d}": i <= must for i in range(1, 13)},
                           "test_sh": {"exit": 0}}}


def test_bao_cao_dung_trung_vi_va_khoang_moi_khung() -> None:
    md = _load().bao_cao([_luot("x-agents", 1, output=100, must=12, phut=2),
                          _luot("x-agents", 2, output=300, must=10, phut=4),
                          _luot("x-agents", 3, output=200, must=11, phut=3),
                          _luot("x-templates", 1, output=50, must=9, phut=0)], GIA)
    assert "| Output | 200 (100–300) | 50 (50–50) |" in md
    assert "| Must đạt (nghiệm thu ẩn) | 11/12 (10–12) | 9/12 (9–9) |" in md


def test_bao_cao_ghi_ro_usd_thieu_gia_khong_in_0() -> None:
    md = _load().bao_cao([_luot("x-agents", 1, output=100, must=12, phut=2)], {"usd_moi_trieu_token": {}})
    assert "thiếu giá: claude-opus-5" in md
    assert "0,00 USD" not in md and "0.00 USD" not in md


def test_bao_cao_ma_tran_must_dem_so_lan_dat() -> None:
    md = _load().bao_cao([_luot("x-agents", 1, output=1, must=12, phut=0),
                          _luot("x-agents", 2, output=1, must=11, phut=0)], GIA)
    assert "| M-12 | 1/2 |" in md


def test_bao_cao_luot_chua_cham_nghiem_thu_thi_noi_ro() -> None:
    luot = _luot("x-templates", 1, output=1, must=0, phut=0)
    luot["nghiem_thu"] = None
    md = _load().bao_cao([luot], GIA)
    assert "chưa chấm" in md


# ---------- CLI ----------


def test_cli_claude_jsonl_ghi_file_ket_qua(tmp_path: Path) -> None:
    goc = _phien(tmp_path / "phien")
    out = tmp_path / "token.json"
    assert _load().main(["claude-jsonl", str(goc), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["nguon"] == "claude-jsonl"


def test_cli_xagents_in_ra_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = _so(tmp_path / "company.sqlite")
    assert _load().main(["xagents", str(db), "--du-an", "B1"]) == 0
    assert json.loads(capsys.readouterr().out)["nguon"] == "x-agents"


def test_cli_bao_cao_doc_file_luot_va_bang_gia(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "luot.json"
    f.write_text(json.dumps(_luot("x-agents", 1, output=100, must=12, phut=2)), encoding="utf-8")
    g = tmp_path / "gia.json"
    g.write_text(json.dumps(GIA), encoding="utf-8")
    assert _load().main(["bao-cao", str(f), "--gia", str(g)]) == 0
    assert "| Output | 100 (100–100) |" in capsys.readouterr().out


def test_cli_nguon_khong_ton_tai_thoat_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _load().main(["xagents", str(tmp_path / "khong-co.sqlite")]) == 2
    assert "khong-co.sqlite" in capsys.readouterr().err


def test_cli_ghep_dung_file_luot_cho_bao_cao(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    m = _load()
    token, nt = tmp_path / "token.json", tmp_path / "nt.json"
    assert m.main(["xagents", str(_so(tmp_path / "company.sqlite")), "--out", str(token)]) == 0
    nt.write_text(json.dumps(_luot("x-agents", 1, output=1, must=11, phut=0)["nghiem_thu"]), encoding="utf-8")
    out = tmp_path / "luot-x-agents-1.json"
    assert m.main(["ghep", "--khung", "x-agents", "--lan", "1", "--token", str(token), "--nghiem-thu", str(nt),
                   "--ket-cuc", "done", "--khai-xong", "co", "--can-thiep", "2:duyệt gate spec",
                   "--can-thiep", "1.5:trả lời câu hỏi làm rõ", "--out", str(out)]) == 0
    luot = json.loads(out.read_text(encoding="utf-8"))
    assert luot["can_thiep"] == [{"phut": 2.0, "viec": "duyệt gate spec"},
                                 {"phut": 1.5, "viec": "trả lời câu hỏi làm rõ"}]
    assert (luot["khai_xong"], luot["nghiem_thu"]["must_dat"]) == (True, 11)
    assert "| Must đạt (nghiệm thu ẩn) | 11/12 (11–11) |" in m.bao_cao([luot], GIA)


def test_cli_ghep_can_thiep_sai_khuon_thoat_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    token = tmp_path / "token.json"
    assert _load().main(["xagents", str(_so(tmp_path / "company.sqlite")), "--out", str(token)]) == 0
    assert _load().main(["ghep", "--khung", "x-agents", "--lan", "1", "--token", str(token), "--ket-cuc", "done",
                         "--khai-xong", "khong", "--can-thiep", "duyệt gate"]) == 2
    assert "phút:việc" in capsys.readouterr().err


def test_bang_gia_mau_va_luot_mau_doc_duoc() -> None:
    mau = ROOT / "docs" / "do-hai-khung"
    gia = json.loads((mau / "bang-gia.example.json").read_text(encoding="utf-8"))
    luot = json.loads((mau / "luot.example.json").read_text(encoding="utf-8"))
    assert _load().tinh_usd(luot["token"]["mo_hinh"], gia)[0] is None    # mẫu để null: chưa điền thì không ra số
    assert "chưa chấm" in _load().bao_cao([luot], gia)
