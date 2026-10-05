"""Năm khuôn lỗi lặp lại của TRAPS.md §1 (root), mỗi khuôn một test (K1.6/K1.7 đặc tả kịch bản B).
Đây không phải test tính năng — là test QUY ƯỚC: mọi module mới trong `orch/` phải tuân, không chỉ những
module đã viết tại thời điểm này. Đỏ ở đây nghĩa là một PR sau đã phá quy ước, không phải một tính năng hỏng."""
from __future__ import annotations

import ast
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from company.bus import InMemoryBus
from company.events import Envelope
from company.llm import FakeClient
from company.orch.guards import _can_author_tests
from company.orchestrator import Orchestrator
from test_orchestrator import T1, handler
from test_tools_and_agentic import _init_repo

ORCH_DIR = Path(__file__).resolve().parents[1] / "src" / "company" / "orch"
ORCH_SRC = {p.name: p.read_text(encoding="utf-8") for p in ORCH_DIR.glob("*.py")}


# ---------- khuôn 1: mọi nhánh `except` chung ghi phân biệt được LOẠI lỗi, không phải một chuỗi cố định ----------

def test_khuon1_except_chung_trong_scheduler_ghi_type_name():
    """`watch()` là vòng chạy DÀI NHẤT trong orch/ — một nhịp lỗi không được giết vòng, nhưng cũng không được
    che mọi nguyên nhân sau một nhãn `tick_error` chung chung (khuôn 1: thông điệp phải nói rõ ĐANG LÀ lỗi gì)."""
    src = ORCH_SRC["scheduler.py"]
    m = re.search(r"except Exception as e:.*?\n(?:.*\n){0,4}", src)
    assert m, "watch() phải còn nhánh except Exception chung quanh tick()"
    assert "type(e).__name__" in m.group(0), "phải ghi TÊN LOẠI lỗi, không phải một chuỗi tick_error cố định"


# ---------- khuôn 2: bất biến restart — bảng chuyển giao K1.7 không được lén thêm state RAM-only ----------

def test_khuon2_bang_chuyen_giao_la_du_lieu_tinh_khong_phai_state():
    """`TICKET_TRANSITIONS`/`RELEASE_TRANSITIONS` (orch/fsm.py) phải là hằng số module-level bất biến — nếu một
    PR sau lỡ biến nó thành state đổi lúc chạy (vd. thêm/bớt hàng theo request), khôi phục qua restart sẽ dựng
    lại bảng khác nhau giữa hai tiến trình mà không ai biết (khuôn 2: state RAM không sống sót qua restart)."""
    from company.orch.release_fsm import RELEASE_TRANSITIONS
    from company.orch.ticket_fsm import TICKET_TRANSITIONS
    assert isinstance(TICKET_TRANSITIONS, list) and isinstance(RELEASE_TRANSITIONS, list)
    for row in (*TICKET_TRANSITIONS, *RELEASE_TRANSITIONS):
        assert row.__class__.__dataclass_params__.frozen, f"{row.name}: Transition phải frozen=True"
    # OrchState (K1.3) vẫn là nơi DUY NHẤT giữ state cần rehydrate; bảng K1.7 không định nghĩa trường nào ở đó.
    from company.orch.state import OrchState
    field_names = {f.name for f in __import__("dataclasses").fields(OrchState)}
    assert not ({"ticket_transitions", "release_transitions"} & field_names)


# ---------- khuôn 3: mọi khoá `once`/`_remember` phải mang THẾ HỆ, trừ danh sách miễn có lý do ----------

# Miễn vì lý do RÕ, không phải vì "chưa ai kêu ca":
# - lesson:{tid} / closed:{tid}: đích của chúng (gói bài học, trạng thái cuối) tự nó chỉ xảy ra MỘT LẦN trong
#   đời chủ thể — không có "lần thứ hai hợp lệ" để bị nuốt oan.
# - uat:{rid} TỪNG được miễn cùng lý do ("production deploy một lần mỗi RC"). Sai: `redeploy`/`_rerun_release`
#   chạy lại production cùng `rid` sau khi khách từ chối nghiệm thu, và lần `deployed` thứ hai KHÔNG mở lại gate
#   (audit 2026-09-22). Nay mang `event_id` của release-event: `uat:{rid}:{gen}`.
# - review.escalate:{key}: một thành phần nhưng `key` là biến ĐÃ ghép sẵn `review:{tid}:{src}:{since}` ngay
#   trên đó — thế hệ (`since`) nằm trong biến, mẫu regex không nhìn xuyên biến được.
# - delivery.skipped / smoke.unverified TỪNG được miễn với lý do "audit phụ, đường ống đã có audit chính".
#   K1.4 bỏ miễn: lý do đó chỉ đúng cho nhánh CÓ chạy được smoke (`release.smoke` mang payload từng lượt) —
#   đúng hai nhánh dùng khoá này là nhánh KHÔNG chạy được (thiếu `runtime`, thiếu worktree) và ở đó audit phụ
#   là bản ghi DUY NHẤT nói lượt ấy chưa kiểm. Cả hai nay mang `event_id` của lượt.
KHOA_MIEN: frozenset[str] = frozenset({"lesson", "closed", "review.escalate"})


def _co_the_he(key_tmpl: str) -> bool:
    """Khoá mang thế hệ khi có ≥ 2 thành phần, HOẶC khi thành phần duy nhất là `event_id` — `event_id` đổi mỗi
    lần một event mới tới, nên một lượt "hợp lệ lặp lại" tự nhiên có khoá khác và không đụng khoá cũ."""
    phan = re.findall(r"\{([^}]+)\}", key_tmpl)
    return len(phan) >= 2 or any(x.strip().endswith("event_id") for x in phan)


def test_khuon3_khoa_once_mang_the_he_hoac_nam_trong_danh_sach_mien():
    """`re.findall` theo đúng khuôn đặc tả K1.6: mọi `_remember(f"...")`/`once=f"..."`/`once_key=f"..."` viết
    trực tiếp bằng f-string literal (không qua biến trung gian) phải mang thế hệ (`_co_the_he`) hoặc có tiền tố
    nằm trong `KHOA_MIEN`. `once_key=` (đường của `supervisor.escalate_gate`) từng lọt lưới vì mẫu cũ chỉ bắt
    `once=`, mà `"once_key="` không chứa chuỗi con `"once="` — `gate.escalate:{sid}` sống sót nhờ lỗ đó."""
    pattern = re.compile(r'(?:_remember|once(?:_key)?=)\(?f"([^"]+)"')
    vi_pham: list[str] = []
    for name, src in ORCH_SRC.items():
        for key_tmpl in pattern.findall(src):
            prefix = key_tmpl.split(":", 1)[0].split("{", 1)[0]
            if _co_the_he(key_tmpl) or prefix in KHOA_MIEN: continue
            vi_pham.append(f"{name}: {key_tmpl!r} (không mang thế hệ, không nằm trong KHOA_MIEN)")
    assert not vi_pham, "khoá không thế hệ, không miễn — event lặp lại hợp lệ sẽ bị once nuốt:\n" + "\n".join(vi_pham)


def test_khuon3_no_test_author_ghi_lai_o_moi_lan_rework(tmp_path):
    """Hồi quy cho đúng bẫy K1.2 đã ghi trong đặc tả nhưng chưa sửa tới K1.7: `once=f"no-test-author:{tid}"`
    (không thế hệ) nuốt lần ghi thứ hai — ticket rework mà vẫn không phân vùng được vùng test chỉ hiện MỘT LẦN
    trong audit dù mất lớp bảo vệ ở MỌI lần dispatch. Đo hai chiều nằm trong lịch sử sửa (routes.py)."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "pyproject.toml").unlink()
    import subprocess
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "bỏ dấu hiệu stack"], check=True, capture_output=True)
    bus = InMemoryBus()
    orch = Orchestrator(bus, FakeClient(handler=handler), repo=repo, base="main", test_author=True)
    orch.lead.tickets["T1"] = __import__("company.events", fromlist=["Task"]).Task.model_validate({**T1, "retry": 0})
    for retry in (0, 1):
        orch.lead.tickets["T1"] = orch.lead.tickets["T1"].model_copy(update={"retry": retry})
        env = Envelope(topic="tasks", key="T1", actor="delivery-lead", payload={**T1, "retry": retry})
        assert _can_author_tests(env, orch) is False
    acts = [e.payload for e in bus.replay(topic="audit-log") if e.payload["action"] == "tests_authored_by_assignee"]
    assert len(acts) == 2, "hai lần rework (retry khác nhau) phải ghi hai audit riêng, không bị once nuốt"


def test_khuon3_gate_the_he_hai_van_duoc_escalate(tmp_path):
    """K1.4: `gate.escalate:{sid}` (một thành phần) nuốt gate THỨ HAI của cùng subject. Cùng một `subject_id`
    mở gate nhiều lần trong đời là chuyện thường (`escalation` sau `release`, gate mở lại sau khi hỏng), và
    `HumanGate.pending` khoá theo `subject_id` nên gate mới ghi đè gate cũ dưới đúng cái tên đó — không có gì
    trong khoá cũ phân biệt được hai thế hệ. Đo hai chiều: bỏ `:{_the_he(...)}` khỏi hai khoá trong
    `scheduler.py` thì cả hai assert của thế hệ hai đỏ."""
    from company.gates import GateRequest

    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    def _mo_va_qua_han():
        orch.gate.request(GateRequest(kind="escalation", subject_id="G1", created_by="supervisor",
                                      checklist=["root_cause", "decision:reopen|close", "hint"]))
        orch.tick(now=datetime.now(UTC) + orch.gate.timeout + timedelta(minutes=1))

    _mo_va_qua_han()
    assert len([a for a in orch.supervisor.actions if a.target == "G1" and a.action == "escalate"]) == 1
    orch.gate.decide("G1", "approve", by="human:pm", reason="root_cause: kẹt; decision: reopen; hint: chạy lại")

    _mo_va_qua_han()   # thế hệ hai: gate MỚI cho cùng subject, cũng quá hạn
    esc = [a for a in orch.supervisor.actions if a.target == "G1" and a.action == "escalate"]
    assert len(esc) == 2, f"gate thế hệ hai quá hạn phải escalate lần nữa, nhận được {len(esc)}"
    overdue = [e.payload for e in bus.replay(topic="audit-log") if e.payload["action"] == "gate.overdue"]
    assert len(overdue) == 2, "và phải vào audit-log lần nữa — audit-log là bản ghi bền duy nhất"


def test_khuon3_smoke_unverified_ghi_lai_o_lan_deploy_thu_hai():
    """K1.4: `smoke.unverified:{rid}` nuốt lần deploy thứ hai của cùng release. Hai nhánh dùng khoá này là hai
    nhánh KHÔNG chạy được smoke (thiếu `runtime`, thiếu worktree) — ở đó audit phụ này là bản ghi DUY NHẤT nói
    lượt ấy chưa kiểm, nên nuốt là mất bằng chứng thật. Đo hai chiều: bỏ `:{rc.event_id}` thì assert == 2 đỏ."""
    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler))
    for _ in range(2):   # cùng release id, hai lượt deploy staging riêng biệt (redeploy sau khi sửa)
        rc = Envelope(topic="release-candidates", key="REL-1", actor="delivery-lead",
                      payload={"release_id": "REL-1", "project_id": "P1"})
        orch._smoke("release-engineer", rc, "REL-1", {"status": "deployed"}, None)
    acts = [e.payload for e in bus.replay(topic="audit-log") if e.payload["action"] == "release.smoke_unverified"]
    assert len(acts) == 2, f"hai lượt deploy phải ghi hai audit unverified, nhận được {len(acts)}"


def test_khuon3_delivery_skipped_ghi_lai_o_lan_giao_thu_hai():
    """K1.4: `delivery.skipped:{rid}` nuốt lần giao thứ hai. Nhánh này không đưa `rid` vào `o.delivered` (chưa
    giao được gì cả) nên lượt production sau của cùng release ĐI TỚI đây lần nữa — và im lặng. Đo hai chiều:
    bỏ `:{env.event_id}` thì assert == 2 đỏ."""
    from company.orchestrator import StepResult

    bus = InMemoryBus(); orch = Orchestrator(bus, FakeClient(handler=handler), deliver=True)
    for _ in range(2):
        env = Envelope(topic="release-events", key="REL-1", actor="ops",
                       payload={"release_id": "REL-1", "env": "production", "status": "deployed"})
        orch._deliver(env, StepResult(env.event_id, env.topic, env.key))
    acts = [e.payload for e in bus.replay(topic="audit-log") if e.payload["action"] == "delivery.skipped"]
    assert len(acts) == 2, f"hai lượt production phải ghi hai audit skipped, nhận được {len(acts)}"


# ---------- khuôn 4: event cũ (đã bị vượt) không được phát lại như mới sau resume/restart ----------

def test_khuon4_task_cu_bi_vuot_khong_duoc_chay_lai_tren_worktree_da_commit():
    """Kịch bản QLKH-004 (PR #55): task cũ + PR cũ nằm trong hàng đợi hoãn, mở lại bus/duyệt gate → phát lại →
    KHÔNG được giao cho backend chạy trên worktree đã commit tiếp (đó là superseded, không phải việc mới)."""
    from company.orch.ticket_fsm import TICKET_TRANSITIONS
    names = {t.name for t in TICKET_TRANSITIONS}
    assert "superseded" in names, "TICKET_TRANSITIONS phải còn dòng superseded — đây là chốt chặn khuôn 4"
    row = next(t for t in TICKET_TRANSITIONS if t.name == "superseded")
    assert {"tasks", "pull-requests"} <= row.topics, "phải canh cả tasks lẫn pull-requests, không chỉ một trong hai"


# ---------- khuôn 5: mọi sort/sorted theo dấu thời gian phải có khoá phụ `seq` (thứ tự ghi vào bus) ----------

def test_khuon5_moi_sorted_theo_at_hoac_ts_co_khoa_phu():
    """`sorted(...)`/`.sort(...)` mà `key=` chạm `.at`/`.ts`/`["at"]`/`["ts"]` (dấu thời gian) mà KHÔNG có `seq`
    trong cùng biểu thức key là nghi vấn: hai event ghi trong cùng lượt có thể trùng `ts` tới micro giây (#108)."""
    pattern = re.compile(r"(?:\.sort|sorted)\([^)]*key=[^,)]*\b(?:at|ts)\b[^,)]*\)", re.S)
    vi_pham = []
    for name, src in ORCH_SRC.items():
        for m in pattern.finditer(src):
            if "seq" not in m.group(0): vi_pham.append(f"{name}: {m.group(0)!r}")
    assert not vi_pham, "sort theo thời gian thiếu khoá phụ seq — trùng ts tới micro giây sẽ chập chờn:\n" + "\n".join(vi_pham)


# ---------- nghiệm thu cuối K1 (K1.8): kích thước ----------
#
# K1.8 gốc đặt "wc -l orchestrator.py ≤ 300". Tiêu chí đó **mâu thuẫn với K1.7** của chính epic này (K1.7:
# `_call` và `process` Ở LẠI `orchestrator.py`) và đo sai thứ cần đo. Đo được 2026-09-07 trên 498 dòng còn lại:
#
#   ngoài thân hàm (import, re-export, bảng gán `x = module.fn`, docstring)   250
#   _call 78 · __init__ 48 · process 31 · status/rulings/_deadlock/… 91       248
#
# 250 dòng "ngoài thân hàm" CHÍNH LÀ bề mặt shim mà K1.7 cố ý tạo ra để mọi tên public cũ còn import được
# (K1.1) — cắt nó là đảo ngược K1.7. Và kể cả moi hết `__init__`/`status`/`rulings` ra ngoài (~100 dòng) cũng
# chỉ xuống ~400, đổi lại chỗ dựng đối tượng nằm ở file khác: thuần trang trí, đọc khó hơn.
#
# Nên K1.8 đổi TIÊU CHÍ chứ không chỉ đổi số (ghi lại trong `docs/DAC-TA-KICH-BAN-B.md` §6): đo phần thật sự
# khó đọc — THÂN HÀM — thay vì tổng số dòng vốn phạt đúng cái refactor đã làm đúng.
MAX_THAN_HAM_ORCHESTRATOR = 260
MAX_DONG_MODULE_ORCH = 400
MAX_DONG_MAIN = 60


def _dong_than_ham(src: str, chi_ham: str | None = None) -> int:
    """Tổng số dòng nằm TRONG thân hàm/method (hàm lồng nhau tính một lần, theo hàm ngoài cùng)."""
    tree = ast.parse(src)
    tong = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
        if chi_ham is not None and node.name != chi_ham: continue
        if chi_ham is None and any(isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
                                   for x in ast.walk(tree) if _chua(x, node)): continue
        tong += node.end_lineno - node.lineno + 1   # type: ignore[operator]
    return tong


def _chua(cha: ast.AST, con: ast.AST) -> bool:
    """`cha` bọc `con` và không phải chính nó — để hàm lồng nhau không bị đếm hai lần."""
    if cha is con or not isinstance(cha, (ast.FunctionDef, ast.AsyncFunctionDef)): return False
    return bool(getattr(cha, "lineno", 0) < getattr(con, "lineno", 0)
                and getattr(con, "end_lineno", 0) <= getattr(cha, "end_lineno", 0))


def test_k18_orchestrator_chi_con_wiring_va_dispatcher():
    """Chốt đích ĐÃ SỬA của K1.8. Đỏ ở đây nghĩa là ai đó đưa logic nghiệp vụ MỚI vào `orchestrator.py` thay vì
    vào một module `orch/` — không phải là file dài thêm vài dòng import."""
    src = (ORCH_DIR.parent / "orchestrator.py").read_text(encoding="utf-8")
    n = _dong_than_ham(src)
    assert n <= MAX_THAN_HAM_ORCHESTRATOR, (
        f"thân hàm trong orchestrator.py = {n} dòng (trần {MAX_THAN_HAM_ORCHESTRATOR}). K1.7 giữ `_call`/`process` "
        f"ở đây, nên chỗ duy nhất được phép phình là hai hàm đó — logic mới thuộc về một module `orch/`.")


def test_k18_main_duoi_60_dong():
    """`main` từng là chuỗi 13 nhánh `if ns.cmd == …` dài 162 dòng: thêm một lệnh là thêm một nhánh vào giữa,
    và không đọc được MỘT lệnh mà không cuộn qua mười hai lệnh khác. Nay là parser + ba bảng dispatch."""
    n = _dong_than_ham(ORCH_SRC["cli.py"], chi_ham="main")
    assert 0 < n <= MAX_DONG_MAIN, f"main = {n} dòng (trần {MAX_DONG_MAIN}); tách subcommand vào `cli_cmds.py`"


def test_k18_moi_lenh_cli_co_dung_mot_ham_trong_bang():
    """Bảng dispatch phải PHỦ HẾT subcommand: thiếu một tên là `KeyError` giữa lúc người vận hành gõ lệnh, chứ
    không phải lỗi lúc nạp module. Đối chiếu thẳng với parser thay vì với một danh sách chép tay."""
    from company.orch import cli, cli_cmds
    sub = next(a for a in cli._parser()._actions if getattr(a, "choices", None) and a.dest == "cmd")
    thieu = set(sub.choices) - set(cli_cmds.FILE_CMDS) - set(cli_cmds.BUS_CMDS) - set(cli_cmds.ORCH_CMDS)
    thua = (set(cli_cmds.FILE_CMDS) | set(cli_cmds.BUS_CMDS) | set(cli_cmds.ORCH_CMDS)) - set(sub.choices)
    assert not thieu, f"subcommand không có hàm trong bảng: {sorted(thieu)}"
    assert not thua, f"bảng có hàm cho lệnh không tồn tại: {sorted(thua)}"


# ---------- nghiệm thu cuối K1 (đặc tả kịch bản B): mỗi module orch/ ≤ 400 dòng ----------

def test_kich_thuoc_module_orch_duoi_400_dong():
    """Chốt để không ai vô tình biến MỘT module `orch/` thành `orchestrator.py` thứ hai — mục tiêu của K1 là chia
    nhỏ, một module phình lại tới ~1000 dòng là dấu hiệu cần tách tiếp, không phải "thêm chút cho tiện"."""
    qua_kho: list[str] = []
    for name, src in ORCH_SRC.items():
        n = len(src.splitlines())
        if n > MAX_DONG_MODULE_ORCH: qua_kho.append(f"{name}: {n} dòng")
    assert not qua_kho, "module orch/ vượt 400 dòng, cần tách tiếp:\n" + "\n".join(qua_kho)
