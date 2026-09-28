"""BT8 — tab `keeper` của console: đọc CHỈ ĐỌC bus của công ty bảo trì, và **không hiện số xanh khi rỗng**.

Luật của gói này (`keeper/docs/DAC-TA-KEEPER.md` §10): một số 0 màu xanh và một hệ thống chưa từng chạy nhìn
giống hệt nhau. Nên khi `keeper` chưa chạy lần nào, MỌI ô của tab phải ghi "chưa chạy lần nào" và KHÔNG ô nào
được mang số 0 — kể cả "0 ticket quá hạn".

Ca chiều ngược ở cuối file TẮT đúng bản sửa (`KeeperView.ran` luôn `True`) rồi đo lại: lúc đó bốn ô hiện
`0/0/0/0` và test phải ĐỎ. Không có nó thì test trên xanh vì bus rỗng, đúng bệnh nó sinh ra để chữa.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from keeper.bus import KeeperBus
from keeper.core import CORE as KEEPER_CORE
from keeper.events import AuditLog, DebtEntry, Envelope, ReleaseNote, Ticket

from console import collect as co
from console.collect import KEEPER, KEEPER_EMPTY_NOTE, KeeperView, collect

DEAD_GATEWAY = "http://127.0.0.1:9"
NOW = datetime.now(UTC)


def _publish(bus, topic: str, key: str, actor: str, payload: dict, ts: datetime | None = None) -> None:
    bus.publish(Envelope(topic=topic, key=key, actor=actor, payload=payload,
                         **({"ts": ts} if ts else {})))


@pytest.fixture
def keeper_db(tmp_path: Path) -> Path:
    """Một `keeper.sqlite` THẬT: hai ticket bảo trì (một đã có dòng release), một mục nợ quá hạn và một chưa,
    một gate `patch` đang chờ. Event đi qua `KeeperBus` của chính `keeper`, không viết SQL tay."""
    path = tmp_path / "keeper.sqlite"
    bus = KeeperBus(KEEPER_CORE, path)
    try:
        for tid, subject, tier, gate in (("KT-1", "docs/QUY-TRINH-GIT.md", "high", True),
                                         ("KT-2", "pyproject.toml", "low", False)):
            t = Ticket(ticket_id=tid, subject=subject, risk_tier=tier, requires_gate=gate,
                       due_at=(NOW + timedelta(days=3)).isoformat())
            _publish(bus, "maintenance-tickets", tid, "triager", t.model_dump())
        note = ReleaseNote(ticket_id="KT-2", changelog_line="- keeper: nâng ruff (#PR)",
                           session_line="KT-2 xong")
        _publish(bus, "release-notes", "KT-2", "release-clerk", note.model_dump())
        for subject, due in (("xagents-core/guard.py", NOW - timedelta(days=2)), ("README.md", NOW + timedelta(days=9))):
            d = DebtEntry(subject=subject, reason="hoãn chờ ADR", due_at=due.isoformat(), tier="medium")
            _publish(bus, "debt-ledger", subject, "triager", d.model_dump())
        data = {"kind": "patch", "subject_id": "KT-1", "checklist": ["risk_tier đúng bậc"],
                "created_by": "keeper-supervisor"}
        audit = AuditLog(actor="keeper-supervisor", action="gate.request", ticket_id="KT-1",
                         evidence=json.dumps(data, ensure_ascii=False))
        _publish(bus, "audit-log", "keeper-supervisor", "keeper-supervisor", audit.model_dump())
    finally:
        bus.close()
    return path


# ---------- chưa chạy lần nào: không một con số ----------

@pytest.mark.parametrize("db", ["khong-cau-hinh", "chua-co-file", "rong"])
def test_chua_chay_lan_nao_thi_moi_o_ghi_chu_khong_co_so(tmp_path: Path, db: str) -> None:
    """Ba cách một công ty "chưa chạy": không cấu hình đường dẫn, file chưa tồn tại, và file CÓ nhưng log rỗng.

    Cái thứ ba là cái nguy hiểm: nguồn `ok=True`, mọi phép đếm chạy trơn tru và trả 0 — đúng con số xanh mà
    §10 cấm."""
    if db == "khong-cau-hinh":
        path = None
    elif db == "chua-co-file":
        path = tmp_path / "khong-co.sqlite"
    else:
        path = tmp_path / "rong.sqlite"
        KeeperBus(KEEPER_CORE, path).close()

    k = collect(None, path, gateway_url=DEAD_GATEWAY)["keeper"]
    assert k["ran"] is False
    assert k["empty_note"] == KEEPER_EMPTY_NOTE == "chưa chạy lần nào"
    assert k["tickets"] == [] and k["debts"] == [] and k["gates"] == []
    assert len(k["cards"]) == 4, "bốn ô của tab phải luôn có mặt, kể cả khi chưa chạy"
    assert [c["v"] for c in k["cards"]] == [None] * 4, "ô nào cũng phải rỗng, không ô nào là số 0"
    assert all(c["n"] == KEEPER_EMPTY_NOTE for c in k["cards"])
    assert 0 not in [c["v"] for c in k["cards"]]


def test_o_rong_khong_bao_gio_la_so_khong(tmp_path: Path) -> None:
    """Phép so tường minh: `v` phải là `None`, không phải một giá trị "giả rỗng" mà JSON in ra thành 0."""
    k = collect(None, tmp_path / "khong-co.sqlite", gateway_url=DEAD_GATEWAY)["keeper"]
    for c in k["cards"]:
        assert c["v"] is None and not isinstance(c["v"], int)


# ---------- đã chạy: số thật ----------

def test_da_chay_thi_hien_so_that(keeper_db: Path) -> None:
    s = collect(None, keeper_db, gateway_url=DEAD_GATEWAY)
    k = s["keeper"]
    assert k["ran"] is True and s["sources"][KEEPER]["ok"] is True
    # KT-2 đã có dòng release → rời hàng đợi; KT-1 còn lại.
    assert [t["id"] for t in k["tickets"]] == ["KT-1"]
    assert k["tickets"][0]["tier"] == "high" and k["tickets"][0]["gate"] is True
    # chỉ mục QUÁ hạn, không phải cả sổ nợ
    assert [d["subject"] for d in k["debts"]] == ["xagents-core/guard.py"]
    assert [g["id"] for g in k["gates"]] == ["KT-1"]
    values = {c["k"]: c["v"] for c in k["cards"]}
    assert values["Hàng đợi ticket"] == 1 and values["Nợ quá hạn"] == 1 and values["Gate đang chờ"] == 1
    # ngân sách: một dòng release trong 7 ngày, trần mặc định 5 → còn 4
    assert values["Ngân sách còn lại"] == 4
    assert "ý định PR chưa có số" in dict((c["k"], c["n"]) for c in k["cards"])["Ngân sách còn lại"]


def test_gate_keeper_di_chung_hang_doi_truc_ban(keeper_db: Path) -> None:
    """Người trực có MỘT chỗ để ký: gate của `keeper` nằm trong `state["gates"]` như hai xưởng kia, mang
    `xuong="keeper"` để `decide.py` biết ghi vào bus nào."""
    gates = collect(None, keeper_db, gateway_url=DEAD_GATEWAY)["gates"]
    assert [(g["id"], g["xuong"], g["kind"]) for g in gates] == [("KT-1", KEEPER, "patch")]


def test_han_muc_tuan_doc_bien_moi_truong_moi_lan(keeper_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`KEEPER_MAX_PR_PER_WEEK` hạ giữa đêm phải có hiệu lực ngay — console đọc qua `keeper.budget`, không
    giữ bản sao nào."""
    from keeper.budget import MAX_PR_ENV

    monkeypatch.setenv(MAX_PR_ENV, "1")
    k = collect(None, keeper_db, gateway_url=DEAD_GATEWAY)["keeper"]
    assert dict((c["k"], c["v"]) for c in k["cards"])["Ngân sách còn lại"] == 0, \
        "đã soạn 1 dòng release trong tuần, trần 1 → còn 0 (số 0 THẬT, vì công ty đã chạy)"


def test_no_khong_qua_han_thi_o_hien_so_khong_that(tmp_path: Path) -> None:
    """Chiều còn lại của luật: đã chạy rồi thì 0 là một con số HỢP LỆ, không bị đổi thành chữ."""
    path = tmp_path / "keeper.sqlite"
    bus = KeeperBus(KEEPER_CORE, path)
    try:
        t = Ticket(ticket_id="KT-9", subject="README.md", risk_tier="low")
        _publish(bus, "maintenance-tickets", "KT-9", "triager", t.model_dump())
    finally:
        bus.close()
    k = collect(None, path, gateway_url=DEAD_GATEWAY)["keeper"]
    assert k["ran"] is True
    assert dict((c["k"], c["v"]) for c in k["cards"])["Nợ quá hạn"] == 0


# ---------- chỉ đọc ----------

def test_khong_ghi_mot_byte_nao_vao_db_cua_keeper(keeper_db: Path) -> None:
    """`collect` mở SQLite `mode=ro`: không `CREATE TABLE`, không đổi journal mode. Đo bằng nội dung file
    trước/sau — dựng `KeeperOrchestrator` hay `KeeperBus` ở đây sẽ làm test này đỏ."""
    truoc = keeper_db.read_bytes()
    collect(None, keeper_db, gateway_url=DEAD_GATEWAY)
    assert keeper_db.read_bytes() == truoc


def test_log_hong_thi_noi_ly_do_chu_khong_nem(tmp_path: Path) -> None:
    path = tmp_path / "hong.sqlite"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE events (seq INTEGER PRIMARY KEY, body TEXT)")
    con.execute("INSERT INTO events (body) VALUES (?)", ("khong-phai-json-envelope-hop-le",))
    con.commit()
    con.close()
    s = collect(None, path, gateway_url=DEAD_GATEWAY)
    assert s["sources"][KEEPER]["ok"] is False and "log hỏng" in s["sources"][KEEPER]["error"]
    assert s["keeper"]["ran"] is False and [c["v"] for c in s["keeper"]["cards"]] == [None] * 4


def test_mot_event_keeper_sai_schema_khong_giet_ca_trang(keeper_db: Path, company_db: Path) -> None:
    """Envelope đọc được nhưng payload không hợp `Ticket` (audit 2026-09-23): `_replay` ném `ValidationError`,
    không phải `_SourceError`. Trước đây nó thoát khỏi `collect()` → `/api/state` 500 và hàng gate của
    software-company biến mất theo. Nay chỉ nguồn `keeper` hỏng, có lý do; nguồn khác nguyên vẹn."""
    bad = Envelope(topic="maintenance-tickets", key="KT-X", actor="triager", payload={"ticket_id": "KT-X"})
    con = sqlite3.connect(keeper_db)
    con.execute("INSERT INTO events (event_id, topic, key, actor, ts, body) VALUES (?, ?, ?, ?, ?, ?)",
                (bad.event_id, bad.topic, bad.key, bad.actor, bad.ts.isoformat(), bad.model_dump_json()))
    con.commit()
    con.close()
    s = collect(company_db, keeper_db, gateway_url=DEAD_GATEWAY)
    src = s["sources"][KEEPER]
    assert src["ok"] is False and "ValidationError" in src["error"]
    assert s["keeper"]["ran"] is False and s["keeper"]["gates"] == []
    assert {g["xuong"] for g in s["gates"]} == {"software-company"}
    assert s["sources"]["software-company"]["ok"] is True


# ---------- ca chiều ngược ----------

def test_do_hai_chieu_tat_co_ran_thi_o_rong_hien_so_khong(tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """TẮT đúng bản sửa: `ran` luôn `True` (tức "ok là đủ", bản trước khi đếm cả log rỗng). Cùng một bus rỗng,
    bốn ô lập tức mang `0` — và phép khẳng định của test đầu tiên phải đỏ."""
    path = tmp_path / "rong.sqlite"
    KeeperBus(KEEPER_CORE, path).close()

    assert [c["v"] for c in collect(None, path, gateway_url=DEAD_GATEWAY)["keeper"]["cards"]] == [None] * 4

    monkeypatch.setattr(KeeperView, "ran", property(lambda self: self.ok))
    hong = collect(None, path, gateway_url=DEAD_GATEWAY)["keeper"]
    assert hong["ran"] is True
    assert [c["v"] for c in hong["cards"]] == [0, 5, 0, 0], "bản hỏng đúng là bốn số xanh vì rỗng"
    with pytest.raises(AssertionError):
        assert [c["v"] for c in hong["cards"]] == [None] * 4


def test_do_hai_chieu_ghi_chu_rong_phai_la_chu_khong_phai_chuoi_rong() -> None:
    """`KEEPER_EMPTY_NOTE` là văn bản người đọc, không phải một hằng số rỗng vô hại: đổi nó thành `""` thì
    tab hiện bốn ô trắng trơn — vẫn không có số 0, nhưng cũng không nói gì."""
    assert KEEPER_EMPTY_NOTE.strip() and "chưa chạy" in KEEPER_EMPTY_NOTE
    assert all(note == KEEPER_EMPTY_NOTE for _, note in co.KEEPER_CARDS)
    assert len(co.KEEPER_KEYS) == len(co.KEEPER_CARDS) == 4


# ---------- duyệt gate và nạp tín hiệu cho `keeper` qua console ----------

def test_duyet_gate_keeper_qua_console_di_dung_duong_gate(keeper_db: Path) -> None:
    """Console không dựng `gate.decide` bằng tay: nó mở `PersistentGate` của `keeper` và gọi `decide(...)`,
    nên four-eyes + allowlist + bản ghi `audit-log` đều đi đúng đường mà `keeper gate` của người đi."""
    from keeper.gates import PersistentGate as KeeperGate

    from console.decide import decide

    out = decide(None, keeper_db, subject_id="KT-1", xuong=KEEPER, decision="approve",
                 by="human:truc-ban", reason="bằng chứng hai chiều đủ")
    assert out["ok"] is True and out["decision"] == "approve" and out["event_id"]
    bus = KeeperBus(KEEPER_CORE, keeper_db)
    try:
        assert KeeperGate(bus).is_approved("KT-1")
    finally:
        bus.close()
    assert collect(None, keeper_db, gateway_url=DEAD_GATEWAY)["keeper"]["gates"] == []


def test_four_eyes_va_allowlist_cua_keeper_van_ap_tren_duong_console(keeper_db: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """Console không được là lối tắt bỏ qua `KEEPER_GATE_APPROVERS` (K3.7 của company, lặp lại cho keeper).
    Four-eyes thử trên gate do NGƯỜI mở: `by` không hình người (`keeper-supervisor`) bị chặn trước đó (F-A)."""
    from keeper.gates import APPROVERS_ENV, CHECKLIST, GateRequest
    from keeper.gates import PersistentGate as KeeperGate

    from console.decide import GateError, decide

    bus = KeeperBus(KEEPER_CORE, keeper_db)
    try:
        KeeperGate(bus).request(GateRequest(kind="patch", subject_id="KT-2", created_by="human:truc-ban",
                                            checklist=list(CHECKLIST)))
    finally:
        bus.close()
    with pytest.raises(GateError) as e:
        decide(None, keeper_db, subject_id="KT-2", xuong=KEEPER, decision="approve",
               by="human:truc-ban", reason="tự duyệt")
    assert "four-eyes" in str(e.value)
    monkeypatch.setenv(APPROVERS_ENV, "human:cto")
    with pytest.raises(GateError) as e2:
        decide(None, keeper_db, subject_id="KT-1", xuong=KEEPER, decision="approve",
               by="human:nguoi-la", reason="")
    assert "danh sách người duyệt" in str(e2.value)


@pytest.mark.parametrize("by", ["owner", "reviewer:x", "patcher"])
def test_by_khong_phai_nguoi_khong_duyet_duoc_gate_keeper_qua_console(keeper_db: Path, by: str) -> None:
    """Bus keeper không chặn actor lạ ghi `gate.decide`, nên trước bản vá (audit 2026-09-27, F-A) console trả `ok`
    kèm `event_id` cho MỌI `by` không phải người, còn `trusted_decision` bỏ bản ghi ở mọi tiến trình khác — gate
    vẫn chờ. `keeper gate` (CLI) chặn đúng chỗ này từ đầu; console là lối vòng qua chốt đó."""
    from keeper.gates import PersistentGate as KeeperGate

    from console.decide import decide

    with pytest.raises(ValueError, match="không phải người"):
        decide(None, keeper_db, subject_id="KT-1", xuong=KEEPER, decision="approve", by=by, reason="ok")
    bus = KeeperBus(KEEPER_CORE, keeper_db)
    try:
        assert "KT-1" in KeeperGate(bus).pending
    finally:
        bus.close()


def test_quyet_dinh_rieng_cua_keeper_duoc_nhan(keeper_db: Path) -> None:
    """`keeper.gates.Decision` có `hold`/`rollback` — console phải nhận đúng bảng verb của xưởng đó, không
    phải bảng của company."""
    from console.decide import decide

    assert decide(None, keeper_db, subject_id="KT-1", xuong=KEEPER, decision="hold",
                  by="human:truc-ban", reason="chờ ADR")["decision"] == "hold"


def test_nap_tin_hieu_bao_tri_qua_console(tmp_path: Path) -> None:
    """`maintenance-signals` là topic DUY NHẤT người nạp tay được của `keeper` (`core.HUMAN_TOPICS`); key lấy
    từ `subject`."""
    from console import submit as sm

    db = tmp_path / "keeper.sqlite"
    r = sm.submit(None, db, xuong=KEEPER, topic="maintenance-signals",
                  payload={"subject": "pyproject.toml", "kind": "dependency", "detail": "ruff tụt sau 3 minor"},
                  actor="human:truc-ban")
    assert r["ok"] is True and r["xuong"] == KEEPER and r["key"] == "pyproject.toml"
    bus = KeeperBus(KEEPER_CORE, db)
    try:
        env = list(bus.replay("maintenance-signals", "pyproject.toml"))[-1]
    finally:
        bus.close()
    assert env.event_id == r["event_id"] and env.actor == "human:truc-ban"


def test_khong_nap_tay_duoc_ticket_bao_tri(tmp_path: Path) -> None:
    """Ticket phải đi qua `triager` để có `risk_tier` — console không mở một cửa sau cho việc đó."""
    from console import submit as sm

    with pytest.raises(ValueError, match="maintenance-tickets"):
        sm.submit(None, tmp_path / "k.sqlite", xuong=KEEPER, topic="maintenance-tickets",
                  payload={"ticket_id": "KT-3"}, actor="human:x")


def test_thieu_duong_dan_bus_keeper_thi_noi_ro_co(tmp_path: Path) -> None:
    from console import submit as sm

    with pytest.raises(ValueError, match="--keeper-db"):
        sm.submit(None, None, xuong=KEEPER, topic="maintenance-signals",
                  payload={"subject": "a", "kind": "drift", "detail": "x"}, actor="human:x")


# ---------- trang: tab `bao-tri` có đủ chỗ, và không chỗ nào bịa ra số 0 ----------

STATIC = Path(__file__).resolve().parents[1] / "src" / "console" / "static"


def test_tab_bao_tri_co_du_khung_tren_trang() -> None:
    """Trang không có bước build: một `id` viết sai chỉ lộ ra khi mở trình duyệt. Ràng buộc bốn chỗ mà
    `keeper.js` ghi vào với bốn chỗ `index.html` khai."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "js" / "keeper.js").read_text(encoding="utf-8")
    assert 'data-v="bao-tri"' in html and 'id="v-bao-tri"' in html
    for anchor in ("kp-tiles", "kp-tickets", "kp-debts", "kp-gates", "nav-keeper"):
        assert f'id="{anchor}"' in html, f"index.html thiếu #{anchor}"
        assert f'"#{anchor}"' in js, f"keeper.js không ghi vào #{anchor}"
    assert '"bao-tri"' in (STATIC / "js" / "router.js").read_text(encoding="utf-8")


def test_trang_khong_bia_ra_so_khi_o_rong() -> None:
    """Chiều hiển thị của luật §10, canh bằng chính mã trang: `keeper.js` phải phân biệt `v == null` (chưa
    chạy → chữ) với `v === 0` (đã chạy → số), và không được có `||0` — mẫu đó biến một ô rỗng thành số 0."""
    js = (STATIC / "js" / "keeper.js").read_text(encoding="utf-8")
    assert "c.v==null" in js.replace(" ", ""), "phải so với null, không phải so 'giả rỗng'"
    assert "||0" not in js.replace(" ", ""), "`||0` biến ô chưa chạy thành số 0"
    assert "empty_note" in js and "k.ran" in js
