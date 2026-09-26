"""ADR-0037 PR-4: id agent chỉ được là chuỗi ở MỘT chỗ — `src/company/roles.py` (và front matter `agents/*.md`).

Test quét bằng `tokenize`, không grep: chỉ token STRING mới tính, nên chú thích/docstring nhắc tên vai không bị bắt
(prose không đổi hành vi), còn `"delivery-lead"` trong `actor=` thì có. `TRAPS.md` §2 "Tin test canh quy ước kiểu
grep": bộ quét được chạy trên một vi phạm biết trước (`test_bo_quet_bat_duoc_vi_pham_biet_truoc`) để chứng minh nó
nhìn thấy thứ nó phải thấy — không kế thừa niềm tin.
"""
from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path
from typing import get_args

import pytest

from company.registry import load_agents
from company.roles import (
    BUILD_PHASES,
    ENGINEERING,
    FINDING_KIND,
    LEAD_ACTOR,
    PHASE,
    ROLE,
    SOURCE,
    STACK,
    Assignee,
    BuildPhase,
    ReviewSource,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "company"
CONSOLE_TRUTH = ROOT.parents[1] / "platform" / "console" / "src" / "console" / "truth.py"

# 21 id trước ADR-0037. Giữ danh sách này CỐ ĐỊNH qua PR-5a..5e: khi một agent bị gộp, tên cũ của nó không được
# quay lại src/ dưới dạng chuỗi — kể cả trong code "tương thích".
OLD_IDS = frozenset({
    "intake", "researcher", "synthesizer", "risk", "clarifier", "spec-writer", "delivery-lead",
    "backend", "frontend", "mobile", "database", "platform", "data",
    "test-author", "reviewer", "qa-debugger", "security-engineer", "release-engineer",
    "support-docs", "account-manager", "supervisor",
})

# Đã gộp/đổi tên tới đâu (PR-5a..5e): id cũ → id mới. Lớn dần đúng một dòng mỗi PR-5x, và là chỗ DUY NHẤT test
# biết đợt gộp đã đi tới đâu — quên cập nhật khi đổi `ROLE.*` là đỏ ở `test_hang_role_khop_front_matter_hai_chieu`.
MIGRATED: dict[str, str] = {
    "security-engineer": "security",  # PR-5a
    "release-engineer": "ops", "support-docs": "ops", "account-manager": "ops",  # PR-5b (gộp 3→1)
    "test-author": "qa", "reviewer": "qa", "qa-debugger": "qa",  # PR-5c (gộp 3→1, pha `author`/`review`)
    # PR-5d (gộp 6→1): sáu tên cũ SỐNG TIẾP nhưng đổi nghĩa — chúng là `stack` của ticket và pha của `builder`
    # (`roles.STACK`/`BUILD_PHASES`), không còn là id agent. Vì thế chúng vẫn bị cấm dưới dạng chuỗi ngoài roles.py.
    "backend": "builder", "frontend": "builder", "mobile": "builder",
    "database": "builder", "platform": "builder", "data": "builder",
    # PR-5e (gộp 7→1): bốn PHA của `product`. Hai tên cũ SỐNG TIẾP nhưng đổi nghĩa — `intake`/`researcher` là
    # `kind` của `research-findings` (`roles.FINDING_KIND`), `delivery-lead` là `LEAD_ACTOR` (actor của event do
    # `delivery.py` phát). Vì trùng id agent cũ, chúng vẫn bị cấm dưới dạng chuỗi ngoài roles.py.
    "intake": "product", "clarifier": "product", "researcher": "product", "synthesizer": "product",
    "risk": "product", "spec-writer": "product", "delivery-lead": "product",
}

# Chuỗi trùng tên vai nhưng KHÔNG phải vai. Miễn theo (file, đúng nguyên dòng): đổi dòng là phải xét lại lý do,
# không có chuyện dòng khác trong cùng file "thừa hưởng" miễn trừ.
EXEMPT_LINES: dict[tuple[str, str], str] = {
    ("orch/enrich.py", 'return {FINDING_KIND.INTAKE: found[-1].payload.get("data")} if found and found[-1].payload.get("data") else {}'):
        "`data` là TRƯỜNG của research-findings (schema bắt buộc `kind` + `data`), không phải agent `data`. "
        "Khoá đổi routes.py → enrich.py khi tách module (không đổi dòng, nên lý do giữ nguyên)",
    ("orch/routes.py", '"incidents": _field("root_cause_class", "code", "ops", "design"),'):
        "`\"ops\"` ở đây là GIÁ TRỊ enum `root_cause_class` của incidents.json (code/ops/design/…), không phải "
        "id agent — trùng chữ tình cờ từ PR-5b (`ROLE.OPS` mới là `\"ops\"`)",
    ("dast.py", 'OAS_SECURITY = "security"  # khoá Security Requirement của OpenAPI, không phải agent'):
        "`security` là khoá Security Requirement của OpenAPI (op đăng nhập công khai khai `security: []`, ADR-0047), "
        "không phải agent `security` — trùng chữ tình cờ với `ROLE.SECURITY`",
}


def _scan_files() -> list[Path]:
    files = [p for p in SRC.rglob("*.py") if p.name != "roles.py"]
    return [*files, CONSOLE_TRUTH]


def _violations(text: str, ids: frozenset[str], rel: str = "") -> list[tuple[int, str]]:
    """(dòng, giá trị) của mọi token STRING có giá trị đúng bằng một id — chỉ token, không đụng chú thích."""
    lines = text.splitlines()
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type != tokenize.STRING: continue
        try: val = ast.literal_eval(tok.string)
        except (ValueError, SyntaxError): continue  # f-string, bytes… không phải chuỗi thuần
        if not isinstance(val, str) or val not in ids: continue
        if (rel, lines[tok.start[0] - 1].strip()) in EXEMPT_LINES: continue
        out.append((tok.start[0], val))
    return out


def _all_ids() -> frozenset[str]:
    return frozenset(load_agents()) | OLD_IDS


def test_khong_con_id_agent_dang_chuoi_trong_src():
    ids = _all_ids()
    found: list[str] = []
    for f in _scan_files():
        rel = str(f.relative_to(SRC)) if f.is_relative_to(SRC) else f.name
        rel = rel.replace("\\", "/")
        found += [f"{rel}:{ln} {val!r}" for ln, val in _violations(f.read_text(encoding="utf-8"), ids, rel)]
    assert not found, "id agent viết tay ngoài roles.py — dùng ROLE.* / SOURCE.* / LEAD_ACTOR:\n" + "\n".join(found)


def test_moi_dong_mien_tru_van_ton_tai():
    """Miễn trừ chỉ có nghĩa khi dòng còn đó đúng nguyên văn — dòng đổi/mất là mục miễn trừ đã chết, phải gỡ."""
    for (rel, line), _reason in EXEMPT_LINES.items():
        text = (SRC / rel).read_text(encoding="utf-8")
        assert sum(1 for ln in text.splitlines() if ln.strip() == line) == 1, (rel, line)


def test_bo_quet_bat_duoc_vi_pham_biet_truoc():
    """Chiều ngược của test trên, tự chứa: một literal id thêm vào → phải thấy; chú thích và f-string → không."""
    ids = _all_ids()
    assert _violations('x = "delivery-lead"\n', ids) == [(1, "delivery-lead")]
    assert _violations("y = 'qa-debugger'\n", ids) == [(1, "qa-debugger")]
    assert _violations('z = {"reviewer": "qa"}\n', ids) == [(1, "reviewer"), (1, "qa")]  # key cũng là chuỗi
    assert _violations('# "delivery-lead" trong chú thích\nw = f"sc-{ROLE.LEAD}"\n', ids) == []
    assert _violations('v = "delivery-lead-x"\n', ids) == []  # chỉ bắt đúng nguyên id, không bắt chuỗi chứa nó


def test_hang_role_khop_front_matter_hai_chieu():
    """Mỗi `ROLE.*` là một agent thật, và mỗi agent thật có đúng một hằng — đổi tên agent mà quên roles.py là đỏ."""
    consts = {k: v for k, v in vars(ROLE).items() if not k.startswith("_")}
    agents = set(load_agents())
    assert set(consts.values()) == agents, (set(consts.values()) ^ agents)
    assert len(set(consts.values())) == len(consts), "hai hằng cùng một id"
    assert set(consts.values()) == (OLD_IDS - set(MIGRATED)) | set(MIGRATED.values()), \
        "hằng phải là 21 id cũ, trừ những id đã gộp/đổi tên trong MIGRATED"
    # PR-5e đã tách: AGENT delivery-lead vào `product`, còn ACTOR của event do `delivery.py` phát giữ nguyên
    # chuỗi cũ. Nó không được là id agent nữa — nếu trùng lại thì một agent đang mạo danh phần code đóng vòng.
    assert LEAD_ACTOR not in set(consts.values()), "LEAD_ACTOR là actor của code, không phải agent"


def test_source_va_literal_khop_hang():
    assert get_args(Assignee) == ENGINEERING
    assert get_args(BuildPhase) == BUILD_PHASES
    assert BUILD_PHASES == tuple(v for k, v in vars(STACK).items() if not k.startswith("_"))
    assert get_args(ReviewSource) == (SOURCE.REVIEWER, SOURCE.QA, SOURCE.SECURITY)
    assert set(SOURCE.__dict__) & {"REVIEWER", "QA", "SECURITY"} == {"REVIEWER", "QA", "SECURITY"}


@pytest.mark.parametrize("name", ["ROLE", "SOURCE", "STACK", "FINDING_KIND", "PHASE"])
def test_namespace_khong_khoi_tao_duoc_thay_doi(name):
    """Hằng là hằng: gán đè vào namespace phải bị mypy `Final` chặn lúc kiểm tĩnh; lúc chạy chỉ kiểm nó không rỗng."""
    ns = {"ROLE": ROLE, "SOURCE": SOURCE, "STACK": STACK, "FINDING_KIND": FINDING_KIND, "PHASE": PHASE}[name]
    assert all(isinstance(v, str) and v for k, v in vars(ns).items() if not k.startswith("_"))
