"""Bảng route + guard/enrich thuần: agent nào chạy tiếp theo cho topic nào (tách khỏi orchestrator.py, ADR-0034).

Không giữ trạng thái phiên — mọi hàm ở đây chỉ đọc từ `Orchestrator` (bus, lead, workspace, blackboard) qua tham
số, không có side effect ngoài audit-log của `_audit`. `check_routes` đối chiếu bảng với front matter agent lúc
khởi động (`Orchestrator.__init__`), nên lệch route/schema vỡ ngay, không phải lúc chạy.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from ..events import Envelope
from ..registry import AgentSpec
from ..roles import BUILD_PHASES, FINDING_KIND, PHASE, ROLE, SOURCE
from ..runner import CONTEXT_ONLY

if TYPE_CHECKING:
    pass

from .enrich import BLIND_STRIP as BLIND_STRIP  # re-export: worktree_flow/orchestrator nhập từ đây
from .enrich import _with_chan_doan, _with_diff, _with_draft, _with_intake, _with_task
from .guards import MAX_CLARIFY_ROUNDS as MAX_CLARIFY_ROUNDS
from .guards import PLAN_REWORKS as PLAN_REWORKS
from .guards import SPEC_KINDS as SPEC_KINDS
from .guards import SPEC_RUNTIME_REWORKS as SPEC_RUNTIME_REWORKS
from .guards import (
    Enrich,
    When,
    _answers_incomplete,
    _can_author_tests,
    _cr_accepted_direct,
    _cr_accepted_needs_research,
    _deployed,
    _field,
    _from_kind,
    _from_phase,
    _has_dispute,
    _needs_security,
    _no_test_author,
    _release_needs_security,
    _spec_ready,
)
from .guards import spec_runtime_gap as spec_runtime_gap

ACTOR = "orchestrator"
PAUSING = frozenset({"pause", "budget_cut", "escalate"})

MAX_CONFLICT_RETRIES = 6  # xung đột merge thứ 7 liên tiếp cho một ticket mới tính vào retry nội dung (xem conflict_retries)
MAX_TURN_CONTINUATIONS = 3  # lần builder hết lượt tool mà worktree có tiến độ được làm tiếp không tính retry (xem turn_continuations)
# Chuỗi nghiên cứu chạy theo key=project, không có ticket/retry/blocked: một agent lỗi là cả dự án đứng mà không ai
# thấy. Lỗi ở các topic này mở gate `escalation` cấp dự án (approve = chạy lại event, reject = đóng dự án).
RESEARCH_TOPICS = frozenset({"research-requests", "research-findings", "requirements-draft", "clarification-answers"})
CONTROL_TOPICS = frozenset({"audit-log", "shared-context", "supervisor-actions"})
# Nhãn `source` của review-results → agent chấm. ADR-0037: `reviewer` và `qa` là hai GÓC NHÌN của cùng agent `qa`.
REVIEW_AGENT = {SOURCE.REVIEWER: ROLE.QA, SOURCE.QA: ROLE.QA, SOURCE.SECURITY: ROLE.SECURITY}
KEY_FIELD = {"tasks": "ticket_id", "pull-requests": "ticket_id", "test-suites": "ticket_id", "review-results": "ticket_id", "incidents": "incident_id",
             "change-requests": "change_id", "release-candidates": "release_id", "release-events": "release_id",
             "acceptance-results": "release_id"}  # topic khác (project_id) giữ key của event nguồn
#: Topic mà mỗi event thuộc về đúng MỘT ticket: đầu ra của route đọc chúng mang `ticket_id` của chính ticket đó
#: (`Orchestrator._run_route`, audit `output.subject_overridden`).
TICKET_TOPICS = frozenset({"tasks", "pull-requests", "test-suites"})
#: Action DUY NHẤT model được ghi lên `audit-log` (route `change-requests → product`, ước lượng impact).
CR_IMPACT_ACTION = "change.impact"


def key_for(topic: str, payload: dict[str, Any], default: str) -> str:
    return str(payload.get(KEY_FIELD.get(topic, ""), "") or default)
ACTIVE_STATES = frozenset({"dispatched", "in_progress", "in_review"})



@dataclass(frozen=True)
class Route:
    topic_in: str
    agent: str  # id agent
    topic_out: str  # topic, hoặc CONTEXT_ONLY = chỉ ghi blackboard
    when: When | None = None
    target_env: str | None = None  # route release: đầu ra phải có env đúng như yêu cầu
    many: bool = False  # 0..n payload một lượt (agent được quyền "không có gì để phát")
    enrich: Enrich | None = None  # thêm dữ liệu vào payload đầu vào (vd. bản draft mới nhất cho pha `spec`)
    tools: str | None = None  # "rw": sửa code trong worktree (kỹ thuật); "ro": chỉ đọc + chạy test (QA); "research": đọc repo khách + web
    # ADR-0037: pha của lượt — agent nạp thêm skill của pha này (`AgentSpec.phases`). None = chỉ skill cấp agent,
    # trừ route sửa code: pha lấy theo `stack` của ticket lúc chạy, xem `phase_for`.
    phase: str | None = None


def phase_for(r: Route, spec: AgentSpec, inp: Envelope) -> str | None:
    """Pha của một lượt (ADR-0037). Route khai sẵn thì dùng; route sửa code lấy theo `stack` của ticket (ADR-0013)
    vì cùng một `builder` làm cả sáu stack.

    `stack` là DỮ LIỆU trong payload chứ không phải bảng route, nên nó chỉ được nhận khi agent thật sự khai pha
    đó: ticket không khai `stack` (hoặc khai một chuỗi lạ) chạy bằng prompt chung của `builder` thay vì ném lỗi
    — mất skill của mảng là mất chất lượng, còn ném lỗi ở đây là ticket đứng im. Pha do ROUTE khai thì
    `check_routes` đã đối chiếu với front matter lúc khởi động."""
    if r.phase is not None: return r.phase
    if r.tools != "rw": return None
    stack = str(inp.payload.get("stack") or "")
    return stack if stack in spec.phases else None


# `_from(*actors)` (guard theo `env.actor`) BIẾN MẤT ở PR-5e: sau khi bảy vai nghiên cứu thành bốn pha của cùng
# một `product`, mọi chỗ dùng nó đều so một hằng với chính nó. Hai guard dưới đây thay nó — không giữ lại làm
# "tiện sau này": một hàm không ai gọi là một hàm không ai chạy, và `fail_under = 100` nói đúng điều đó.


















































STAGING_ROUTE = Route("release-candidates", ROLE.OPS, "release-events", target_env="staging", phase="deploy")
# release-check của security: tách hằng để `recheck` (ADR-0047 §5) gọi lại ĐÚNG dòng này, không dựng tay
RELEASE_CHECK_ROUTE = Route("release-candidates", ROLE.SECURITY, "review-results", _release_needs_security)
ROUTES: tuple[Route, ...] = (
    # ADR-0037 PR-5e — khối nghiên cứu: MỘT agent `product`, bốn pha, cùng chuỗi cũ trừ một mắt xích.
    # intake → research → spec (draft đã kèm `risks`) → intake (câu hỏi) → (người trả lời) → spec (PRD).
    # Lượt `risk` riêng (`requirements-draft` → `requirements-draft`) BỊ BỎ: draft của pha `spec` phải có sẵn mục
    # `risks` (schema nâng lên required ở PR-5e), nên một lượt ít hơn cho mỗi dự án và không còn hai bản draft
    # chồng nhau cho cùng một key.
    Route("research-requests", ROLE.PRODUCT, "research-findings", phase=PHASE.INTAKE),
    Route("research-findings", ROLE.PRODUCT, "research-findings", _from_kind(FINDING_KIND.INTAKE),
          tools="research", phase=PHASE.RESEARCH),
    Route("research-findings", ROLE.PRODUCT, "requirements-draft", _from_kind(FINDING_KIND.RESEARCH),
          enrich=_with_intake, phase=PHASE.SPEC),
    Route("requirements-draft", ROLE.PRODUCT, "clarification-questions", _from_phase(PHASE.SPEC), phase=PHASE.INTAKE),
    Route("clarification-answers", ROLE.PRODUCT, "clarification-questions", _answers_incomplete,
          enrich=_with_draft, phase=PHASE.INTAKE),
    Route("clarification-answers", ROLE.PRODUCT, "approved-specs", _spec_ready, enrich=_with_draft, phase=PHASE.SPEC),
    # kỹ thuật + chất lượng
    # ADR-0028: có repo và phân vùng được vùng test → test-author viết test MÙ trước, rồi assignee viết code cho
    # tới khi xanh mà KHÔNG ghi được file test. Không phân vùng được (stack lạ, không repo) → đường cũ, và PR mang
    # `tests_authored_by: "assignee"` để reviewer biết bộ test này không độc lập.
    Route("tasks", ROLE.QA, "test-suites", _can_author_tests, tools="tests", phase="author"),
    # ADR-0037 PR-5d: một agent `builder` cho cả sáu mảng; pha KHÔNG khai ở route mà lấy theo `stack` của ticket
    # lúc chạy (`phase_for`) — `stack` là dữ liệu của ticket, không phải của bảng route.
    Route("tasks", ROLE.BUILDER, "pull-requests", _no_test_author, tools="rw"),
    Route("test-suites", ROLE.BUILDER, "pull-requests", enrich=_with_task, tools="rw"),
    # Assignee không sửa được test (tool chặn): nó ghi `test_dispute` và việc quay về pha `author` — lượt DUY NHẤT
    # bộ test được đổi sau khi đã viết, và lượt duy nhất pha `author` được xem diff.
    Route("pull-requests", ROLE.QA, "test-suites", _has_dispute, enrich=_with_diff, tools="tests", phase="author"),
    # ADR-0037: reviewer + qa-debugger thành MỘT lượt pha `review` cho MỌI ticket (không còn guard `_needs_qa`
    # theo `risk_tags`: `RISK_REVIEWS` chỉ còn `security`), nên enrich gộp cả diff lẫn `chan_doan`.
    # Pha `review` và security cũng có tool CHỈ ĐỌC trên worktree: diff dài hơn `max_input_chars` bị cắt giữa,
    # agent "không được suy diễn" nên BLOCK vì "diff không có trong đầu vào" — không phải lỗi code. Đo được
    # 2026-09-06 (TCK-CR-DEV-001-02, PR 877 dòng): security chặn vì thiếu diff `http_adapter.py`, ticket bị trả
    # về làm lại dù reviewer + QA pass. Có tool thì nó đọc đúng file bị cắt rồi mới chấm.
    Route("pull-requests", ROLE.QA, "review-results",
          enrich=lambda e, o: {**_with_diff(e, o), **_with_chan_doan(e, o)}, tools="ro", phase="review"),
    Route("pull-requests", ROLE.SECURITY, "review-results", _needs_security, enrich=_with_diff, tools="ro"),
    # vận hành: RC → staging (+ security DAST/license khi có risk) → QA hồi quy; production đi qua gate 3 (PROD_ROUTE)
    STAGING_ROUTE,
    RELEASE_CHECK_ROUTE,
    Route("release-events", ROLE.QA, "review-results", _deployed("staging"), tools="ro", phase="review"),  # tool trên worktree tích hợp
    Route("release-events", ROLE.OPS, CONTEXT_ONLY, _deployed("production"), phase="docs"),  # docs, release notes, runbook
    # khách và hậu release
    Route("external-feedback", ROLE.OPS, "change-requests", phase="account"),
    Route("external-feedback", ROLE.OPS, "incidents", many=True, phase="docs"),
    Route("incidents", ROLE.OPS, "research-requests", _field("root_cause_class", "requirement"), many=True, phase="docs"),
    Route("acceptance-results", ROLE.OPS, "change-requests", _field("verdict", "conditional"), many=True, phase="account"),
    Route("change-requests", ROLE.PRODUCT, "audit-log", _field("decision", "pending"), phase=PHASE.PLAN),  # ước lượng impact → người quyết
    Route("change-requests", ROLE.PRODUCT, "research-findings", _cr_accepted_needs_research, phase=PHASE.INTAKE),
)
PROD_ROUTE = Route("release-candidates", ROLE.OPS, "release-events", target_env="production", phase="deploy")


def review_route(agent: str) -> Route:
    """Route chấm PR THẬT của một agent chấm, để chỗ giao lại review (`gates_flow`, `scheduler`) không dựng tay.

    Dựng tay `Route("pull-requests", agent, "review-results")` chạy đúng khi mỗi vai chấm là một agent không
    pha — nhưng ADR-0037 gộp reviewer + qa-debugger vào `qa[review]`, và một Route dựng tay không mang `phase`,
    `enrich`, `tools`: lượt giao lại sẽ chạy bằng prompt pha `author` (không skill code-review, không diff,
    không tool đọc worktree) rồi trả ra `test-suites`. Lấy đúng dòng trong `ROUTES` thì không thể lệch."""
    for r in ROUTES:
        if r.topic_in == "pull-requests" and r.topic_out == "review-results" and r.agent == agent:
            return r
    raise KeyError(f"không có route chấm pull-requests cho {agent}")
def spec_route(topic_in: str) -> Route:
    """Route đưa một event THẲNG về lượt viết PRD của `product` (pha `spec`), cho hai chỗ gọi lại ngoài vòng
    `ROUTES`: `_spec_runtime_missing` (trả spec về vì thiếu `runtime`) và `_act_clarification_fallback`
    (không còn câu hỏi nào để hỏi).

    Không dựng `Route(...)` tay: một Route dựng tay không mang `phase`, nên từ PR-5e lượt ấy chạy bằng prompt
    CHUNG của `product` (không skill `risk-analysis`, không threat-modeling) rồi vẫn trả `approved-specs` — sai
    bộ skill mà không test nào đỏ (đúng bẫy PR-5c đã trả giá với `qa`). Lấy đúng dòng trong `ROUTES` rồi chỉ đổi
    `topic_in`/`when` thì `phase` và `enrich` không thể lệch."""
    base = next(r for r in ROUTES if r.topic_in == "clarification-answers" and r.topic_out == "approved-specs")
    if topic_in == "clarification-answers": return base
    # `requirements-draft` CHÍNH LÀ bản draft: đính kèm nó lần nữa qua `_with_draft` là gửi cùng một thứ hai lần.
    return replace(base, topic_in=topic_in, when=None, enrich=None if topic_in == "requirements-draft" else base.enrich)


THREAT_ROUTE = Route("approved-specs", ROLE.SECURITY, "review-results")  # threat model trước ticket đầu (ADR-0003)

# Đầu vào khiến `product` pha `plan` lập kế hoạch (sinh nhiều ticket một lượt) → `_check_plan` → dispatch (ADR-0037).
PLAN_INPUTS: dict[str, When] = {
    "approved-specs": lambda e, _o: True,
    "incidents": _field("root_cause_class", "code", "ops", "design"),
    "change-requests": _cr_accepted_direct,
}


def check_routes(agents: dict[str, AgentSpec]) -> list[str]:
    """Bảng route phải khớp front matter reads/writes; trả về danh sách vi phạm (rỗng = ổn)."""
    bad = []
    for r in (*ROUTES, PROD_ROUTE, THREAT_ROUTE):
        a = r.agent
        spec = agents[a]
        if r.topic_in not in spec.reads and "*" not in spec.reads: bad.append(f"{a} không đọc {r.topic_in}")
        if r.phase is not None and r.phase not in spec.phases:
            bad.append(f"{a} không có pha {r.phase} (front matter khai: {sorted(spec.phases) or 'không pha nào'})")
        if r.topic_out == CONTEXT_ONLY:
            if not spec.namespaces_write: bad.append(f"{a} không có namespace để ghi blackboard")
        elif r.topic_out not in spec.writes: bad.append(f"{a} không ghi {r.topic_out}")
    # Route sửa code không khai `phase`: pha lấy theo `stack` lúc chạy, nên bảng pha của `builder` phải phủ đúng
    # sáu `stack` hợp lệ — lệch một tên là ticket mảng ấy chạy bằng prompt chung mà không ai thấy.
    build = agents[ROLE.BUILDER]
    bad += [f"{ROLE.BUILDER} không có pha {p} (stack của ticket)" for p in BUILD_PHASES if p not in build.phases]
    lead = agents[ROLE.PRODUCT]
    bad += [f"{ROLE.PRODUCT} không đọc {t}" for t in PLAN_INPUTS if t not in lead.reads]
    return bad

