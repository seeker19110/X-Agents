"""Guard của bảng route: vị từ thuần "event này có đi đường này không" (tách khỏi `routes.py`, ADR-0034).

Tách vì `routes.py` chạm trần 400 dòng của `test_orch_khuon_loi.py` — cùng lý do ADR-0034 tách `orchestrator.py`.
Ranh giới: ở đây KHÔNG có bảng route và KHÔNG có `Route`; `routes.py` nhập vào chứ không có chiều ngược lại, nên
thêm một guard không bao giờ phải sửa bảng và ngược lại.

Mọi hàm chỉ ĐỌC từ `Orchestrator` (bus, lead, workspace) qua tham số. Ngoại lệ có chủ ý: hai chỗ ghi `audit-log`
qua `_audit` để một lối thoát khỏi cổng không bao giờ im lặng.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypedDict

from ..events import BUDGET_FACTOR, HINT_TO_TAG, MAX_TICKET_TOKENS, RISK_HINTS, Envelope, Task
from ..roles import SOURCE
from ..smoke import parse_runtime

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator


MAX_CLARIFY_ROUNDS = 2  # khớp `clarification-questions.round` (maximum 2) và prompt clarifier


class CauHoi(TypedDict):
    id: str
    text: str
    options: list[str]
    default: str


class ClarificationPending(TypedDict):
    """Một dự án đang chờ người trả lời câu hỏi làm rõ (`pending_clarifications`)."""

    round: int
    event_id: str
    unanswered: list[str]
    since: str
    asked_by: str
    questions: list[CauHoi]


When = Callable[[Envelope, "Orchestrator"], bool]
Enrich = Callable[[Envelope, "Orchestrator"], dict[str, Any]]


def _from_phase(name: str) -> When:
    """Event này do lượt của PHA nào sinh ra (ADR-0037 §1.2)? Thay `_from(<agent>)` khi nhiều pha của CÙNG một
    agent phát cùng một topic: từ PR-5e cả `requirements-draft` lẫn `clarification-questions` đều mang
    `actor="product"`, nên guard theo actor không còn phân biệt được lượt nào.

    Đọc `payload["_phase"]` — trường do RUNNER ghi (PR-3, `runner.generate`), không phải lời khai của model,
    cùng nguyên tắc với `env`/`release_id` của `_release`. Event cũ trong bus (trước PR-3) không có trường này
    nên guard trả False: chuỗi nghiên cứu của dự án đang chạy dừng ở đó thay vì chạy sai pha, và `_stall` hiện nó
    ra cho người."""
    return lambda e, _o: e.payload.get("_phase") == name


def _from_kind(kind: str) -> When:
    """`research-findings` tự mang `kind` (schema bắt buộc) nên chuỗi intake → research → spec phân biệt được
    bằng chính dữ liệu, không cần `_phase`: một event của dự án cũ vẫn đi đúng đường."""
    return lambda e, _o: e.payload.get("kind") == kind


def _field(name: str, *values: Any) -> When:
    return lambda e, _o: e.payload.get(name) in values


def _needs_security(e: Envelope, o: Orchestrator) -> bool:
    tid = e.payload.get("ticket_id") or e.key
    return tid in o.lead.tickets and SOURCE.SECURITY in o.lead.required_reviews(tid)


def _release_needs_security(e: Envelope, o: Orchestrator) -> bool:
    return o.lead.release_needs_security(e.payload["release_id"])


def _dict_of(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _deployed(env_name: str) -> When:
    return lambda e, _o: e.payload.get("env") == env_name and e.payload.get("status") == "deployed"


def _answers_complete(e: Envelope, o: Orchestrator) -> bool:
    """Người đã trả lời hết câu hỏi của vòng gần nhất (hoặc đã hết vòng hỏi) → đi thẳng pha `spec`.
    Thiếu câu trả lời mà vẫn viết spec thì spec dựa trên giả định người chưa xác nhận.

    Câu trả lời TÍCH LUỸ trong vòng hiện tại, không chỉ tính event này: người trả lời bổ sung một câu ở lượt
    sau (vd. sau khi `security` nêu thêm câu hỏi mở) không phải gửi lại toàn bộ câu cũ. Trước đây chỉ
    đọc `e.payload`, nên lượt bổ sung luôn bị coi là "thiếu hết các câu trước" và pha `spec` không bao giờ
    chạy lại — câu trả lời nằm im trong bus, không audit, không báo ai (đo được khi chạy thật 2026-09-04)."""
    pid = str(e.payload.get("project_id") or e.key)
    q = o.latest("clarification-questions", pid)
    if q is None:
        return True
    answered = {str(a.get("question_id")) for a in e.payload.get("answers", [])}
    missing = [x for x in unanswered_questions(o.bus, q) if x not in answered]
    return not missing or int(q.payload.get("round", 1)) >= MAX_CLARIFY_ROUNDS


def unanswered_questions(bus: Any, q: Envelope) -> list[str]:
    """Id câu hỏi của vòng `q` chưa có câu trả lời TÍCH LUỸ trên bus — chỉ tính `clarification-answers` từ
    `q.ts` trở đi: id có thể trùng giữa các vòng, câu cũ không được vô tình thoả mãn câu hỏi mới."""
    pid = str(q.payload.get("project_id") or q.key)
    answered: set[str] = set()
    for prev in bus.replay(topic="clarification-answers", key=pid):
        if prev.ts >= q.ts:
            answered |= {str(a.get("question_id")) for a in prev.payload.get("answers", [])}
    return [str(x.get("id")) for x in q.payload.get("questions", []) if str(x.get("id")) not in answered]


def assumed_clarifications(bus: Any) -> set[str]:
    """event_id của các vòng câu hỏi đã được orchestrator giả định theo `default` vì quá hạn (audit
    `clarification.assumed`). Đọc từ bus để restart vẫn nhớ."""
    out: set[str] = set()
    for a in bus.replay(topic="audit-log"):
        if a.payload.get("action") != "clarification.assumed":
            continue
        try:
            out.add(str(json.loads(a.payload.get("evidence") or "{}").get("event_id")))
        except (TypeError, ValueError):
            continue
    return out


def pending_clarifications(bus: Any) -> dict[str, ClarificationPending]:
    """Dự án đang ĐỨNG IM chờ người trả lời câu hỏi làm rõ, tính từ bus (không RAM — mở lại tiến trình vẫn thấy).

    Đo được 2026-09-22 (CAMPUS-UNI): `product` hỏi vòng 1, không ai trả lời, mà `status`/console không có chỗ
    nào nói ra — không ticket, không gate, `warnings: []`. Một dự án chờ người nhưng chỉ có người mới biết.

    Vòng cuối (`round >= MAX_CLARIFY_ROUNDS`) đã có bất kỳ câu trả lời nào thì `_spec_ready` đã cho đi tiếp,
    không còn chờ; chưa có câu trả lời nào thì vẫn chờ, kể cả ở vòng cuối."""
    latest: dict[str, Envelope] = {}
    for q in bus.replay(topic="clarification-questions"):
        latest[str(q.payload.get("project_id") or q.key)] = q
    assumed = assumed_clarifications(bus)
    out: dict[str, ClarificationPending] = {}
    for pid, q in latest.items():
        missing = unanswered_questions(bus, q)
        if not missing or q.event_id in assumed:
            continue  # đã giả định theo default (quá hạn, `_assume_clarifications`): không còn "chờ người"
        rnd = int(q.payload.get("round", 1))
        asked = [str(x.get("id")) for x in q.payload.get("questions", [])]
        if rnd >= MAX_CLARIFY_ROUNDS and len(missing) < len(asked):
            continue  # vòng cuối, đã trả lời một phần
        out[pid] = {
            "round": rnd,
            "event_id": q.event_id,
            "unanswered": missing,
            "since": q.ts.isoformat(timespec="seconds"),
            "asked_by": q.actor,
            "questions": [
                {
                    "id": str(x.get("id")),
                    "text": str(x.get("text") or ""),
                    "options": [str(v) for v in (x.get("options") or [])],
                    "default": str(x.get("default") or ""),
                }
                for x in q.payload.get("questions", [])
                if str(x.get("id")) in missing
            ],
        }
    return out


def _answers_incomplete(e: Envelope, o: Orchestrator) -> bool:
    return not _answers_complete(e, o)


def _spec_ready(e: Envelope, o: Orchestrator) -> bool:
    """Pha `spec` chỉ chạy khi đã trả lời hết câu hỏi VÀ dự án có `requirements-draft`. Trước đây câu trả lời gửi cho
    một dự án chưa có bản nháp (chuỗi nghiên cứu chết, hoặc gửi nhầm dự án) vẫn sinh PRD từ đầu vào trống."""
    if not _answers_complete(e, o):
        return False
    pid = str(e.payload.get("project_id") or e.key)
    if o.latest("requirements-draft", pid) is not None:
        return True
    o._audit(
        "spec_writer.no_draft",
        {
            "project_id": pid,
            "event_id": e.event_id,
            "reason": "clarification-answers nhưng dự án chưa có requirements-draft",
        },
        once=f"no_draft:{e.event_id}",
        project_id=pid,
    )
    return False


def _cr_accepted_needs_research(e: Envelope, _o: Orchestrator) -> bool:
    return e.payload.get("decision") == "accepted" and bool(e.payload.get("affects_requirements"))


def _cr_accepted_direct(e: Envelope, _o: Orchestrator) -> bool:
    return e.payload.get("decision") == "accepted" and not e.payload.get("affects_requirements")


SPEC_KINDS = (
    "application",
    "library",
    "docs",
)  # `approved-specs.payload.kind`; thiếu = application (không khai ≠ được miễn)
SPEC_RUNTIME_REWORKS = (
    1  # số lần tự trả spec về spec-writer vì thiếu runtime trước khi hỏi người (= max_retries của nó)
)
# Số lần tự trả kế hoạch về `product[plan]` (kèm `hint` = problems của `_check_plan`) trước khi hỏi người, tính theo
# EVENT nguồn. Đo 2026-09-22 (CAMPUS-UNI): hai lần liên tiếp người phải gõ "retry" cho một việc máy tự làm được.
PLAN_REWORKS = 1


def spec_runtime_gap(payload: dict[str, Any]) -> str | None:
    """ADR-0031: Gate 1 chỉ mở khi spec trả lời được "chạy ở đâu". Trả về lý do thiếu (để gửi lại spec-writer), None
    khi đủ. `kind=library|docs` được miễn `runtime` nhưng phải KHAI RÕ — thiếu `kind` tính là ứng dụng, vì im lặng
    chính là cách QLKH đi qua bốn gate mà không có điểm vào nào (báo cáo 2026-09-06-ban-giao-khong-chay-duoc)."""
    kind = payload.get("kind") or "application"
    if kind not in SPEC_KINDS:
        return f"`kind`={kind!r} không hợp lệ; phải là một trong {', '.join(SPEC_KINDS)}"
    if kind != "application":
        return None
    if parse_runtime(payload) is not None:
        return None
    rt = payload.get("runtime")
    what = (
        "thiếu `runtime`"
        if not isinstance(rt, dict)
        else "`runtime.command` rỗng hoặc `port`/`timeout_s`/`expect_status` không phải số"
    )
    return (
        f"spec kind=application {what}: Gate 1 cần lệnh khởi động (`runtime.command`, có thể chứa {{port}}), "
        "`port` (0 = tự chọn), `health` (đường GET trả 200) và phụ thuộc ngoài; nếu sản phẩm là thư viện hay tài liệu "
        "thì khai `kind: library|docs` thay vì bỏ trống"
    )


def _test_scope_ok(o: Orchestrator, tid: str) -> bool:
    """Có worktree cho ticket và stack của repo khách khai được vùng test không (ADR-0028 §3, fail closed)."""
    ws = o.workspace(tid)
    if ws is None:
        return False
    try:
        ws.create()
    except Exception as ex:  # không dựng được worktree thì cứ đi đường cũ, `_engineer` báo lỗi thật — nhưng để lại dấu
        err = f"{type(ex).__name__}: {ex}"[:200]
        o._audit("test_scope.worktree_failed", {"ticket_id": tid, "error": err}, ticket_id=tid,
                 once=f"test_scope.worktree_failed:{tid}:{err}")
        return False
    return bool(ws.stack().test_globs)


def _da_co_bo_test(e: Envelope, o: Orchestrator, tid: str) -> bool:
    """Đã có `test-suites` từ TRƯỚC lượt này chưa — hỏi BUS, không hỏi worktree. Lọc `causation_id` chứ KHÔNG
    lọc `ts`: hai route của `tasks` đánh giá tuần tự trong cùng event, nên "bus có bộ test không" lật ngay sau
    khi qa phát và ticket đi cả hai đường. Đo: `test_test_author.py::test_rework_khi_da_co_bo_test_*`."""
    return any(x.causation_id != e.event_id for x in o.bus.replay(topic="test-suites", key=tid))


def _can_author_tests(e: Envelope, o: Orchestrator) -> bool:
    if not o.test_author:
        return False
    tid = str(e.payload.get("ticket_id") or e.key)
    # Khoá `once` của CẢ HAI lối thoát dưới đây mang thế hệ = số lần rework của TICKET (khuôn 3, TRAPS.md §1):
    # thiếu nó, ticket rework lần 2 vẫn rơi vào cùng nhánh nhưng audit không ghi lần hai — người đọc tưởng
    # chuyện chỉ xảy ra một lần trong khi nó lặp mỗi lần dispatch.
    retry = o.lead.tickets[tid].retry if tid in o.lead.tickets else 0
    if _da_co_bo_test(e, o, tid):
        # Rework phát lại `tasks`; bộ test lượt trước đã commit nên test-author đúng đắn KHÔNG ghi gì → "không
        # viết file test nào" → escalation → duyệt → phát lại → lặp (đo 2026-09-14 QLKH: bốn vòng). Re-author
        # còn đúng một đường khác: tranh chấp test (`_has_dispute`), nơi agent được xem diff.
        o._audit(
            "test_author_bo_qua",
            {"ticket_id": tid, "reason": "bộ test cho ticket này đã có trên bus"},
            ticket_id=tid,
            project_id=e.payload.get("project_id"),
            once=f"test-author-bo-qua:{tid}:{retry}",
        )
        return False
    if _test_scope_ok(o, tid):
        return True
    o._audit(
        "tests_authored_by_assignee",
        {"ticket_id": tid, "reason": "không phân vùng được vùng test của stack"},
        ticket_id=tid,
        project_id=e.payload.get("project_id"),
        once=f"no-test-author:{tid}:{retry}",
    )
    return False


def _no_test_author(e: Envelope, o: Orchestrator) -> bool:
    return not _can_author_tests(e, o)


def _has_dispute(e: Envelope, _o: Orchestrator) -> bool:
    return bool(str(e.payload.get("test_dispute") or "").strip())


def clarification_warnings(bus: Any) -> list[str]:
    """Dòng `warnings` của `status()` cho mỗi dự án đang chờ người trả lời câu hỏi làm rõ (không dấu, grep được)."""
    return [f"dang cho nguoi tra loi cau hoi lam ro: {pid} vong {c['round']}, "
            f"{len(c['unanswered'])} cau chua tra loi ({', '.join(c['unanswered'][:5])}) — "
            f"phat clarification-answers de du an di tiep"
            for pid, c in sorted(pending_clarifications(bus).items())]


def _check_plan(o: Orchestrator, tickets: list[Task], project: str) -> list[str]:
    """ADR-0037 PR-1: mọi khoá "Code gửi kèm" của gate plan cũ trở thành một kiểm ở đây, để PR-2 bỏ gate mà
    không mất kiểm nào (`docs/DAC-TA-TRIEN-KHAI-ADR-0037.md` §2). Tách khỏi `ticket_fsm.py` (2026-09-22) vì
    module đó chạm trần 400 dòng — cùng lý do ADR-0034 tách các guard khác ra khỏi orchestrator.py/routes.py.
    Đây là chỗ thứ ba ghi `audit-log` qua `_audit` (bên cạnh hai chỗ đã có ở guard trên): autofix `risk_tags`."""
    ids = {t.ticket_id for t in tickets}; known = ids | set(o.lead.tickets)
    problems = ["kế hoạch rỗng"] if not tickets else []
    if len(ids) != len(tickets): problems.append("ticket_id trùng")
    for t in tickets:
        if t.ticket_id in o.lead.tickets: problems.append(f"{t.ticket_id} đã tồn tại")
        # ADR gốc 0021 §d: `quality:` là namespace của nghiệm thu do trusted driver chạy — không agent nào được giao.
        if t.ticket_id.startswith("quality:"): problems.append(f"{t.ticket_id} dùng tiền tố dành riêng quality:")
        if t.estimate_tokens is None: problems.append(f"{t.ticket_id} thiếu estimate_tokens")
        elif t.budget_tokens < t.estimate_tokens * BUDGET_FACTOR: problems.append(f"{t.ticket_id} budget < estimate×{BUDGET_FACTOR}")
        if not t.acceptance: problems.append(f"{t.ticket_id} thiếu acceptance")
        # ADR-0037 §4.2: `stack` chọn bộ skill mà `builder` được nạp cho ticket này. Kiểm ở ĐÂY chứ không đặt
        # `required` trong `tasks.json` (§13): bus từ chối một ticket là kế hoạch chết giữa chừng — vài ticket đã
        # publish, phần còn lại rơi vào `invalid_output` — còn ở đây cả kế hoạch bị trả về cho `product` sửa,
        # kèm tên ticket thiếu. Thiếu `stack` mà lọt xuống builder thì ticket chạy bằng prompt chung, không ai đỏ.
        if not t.stack: problems.append(f"{t.ticket_id} thiếu stack")
        unknown = [d for d in t.depends_on if d not in known]
        if unknown or t.ticket_id in t.depends_on: problems.append(f"{t.ticket_id} depends_on sai {unknown or 'chính nó'}")
        if t.estimate_days > 1 or (t.estimate_tokens is not None and t.estimate_tokens > MAX_TICKET_TOKENS):
            problems.append(f"{t.ticket_id} quá 1 ngày/200k token: chia nhỏ")
        text = " ".join((t.title, " ".join(t.scope), " ".join(t.acceptance))).lower()
        if not t.risk_tags and any(hint in text for hint in RISK_HINTS):
            hit = next(hint for hint in RISK_HINTS if hint in text)
            tag = HINT_TO_TAG.get(hit)
            if tag is None:
                # Hint không suy được tag (bảng HINT_TO_TAG chưa phủ hết RISK_HINTS): không đoán bừa, vẫn từ
                # chối như hành vi cũ để người/product tự khai đúng tag.
                problems.append(f"{t.ticket_id} chạm {hit} nhưng không có risk_tags")
            else:
                # Suy được thẳng một tag: tự gắn thay vì bắt `product` sinh lại cả kế hoạch (tốn một lượt model
                # đầy đủ) chỉ vì thiếu một khoá suy được. An toàn hơn hiện trạng: tag được THÊM chứ không bớt,
                # nên security review (phụ thuộc risk_tags) vẫn chạy đúng như khi product tự khai đúng ngay từ đầu.
                t.risk_tags = [tag]
                o._audit("risk_tags_autofixed", {"ticket_id": t.ticket_id, "hint": hit, "risk_tags": t.risk_tags},
                         project_id=project)
    sid = f"SPEC-{project}"
    if sid in o.missing_threat_model or o.latest("review-results", sid) is None:
        problems.append(f"thiếu threat model cho {sid}")
    if o.blackboard:
        have = o.blackboard.snapshot(project)
        for ns in ("architecture", "api-contract"):
            if ns not in have: problems.append(f"blackboard thiếu {ns}")
    cyc = _cycle({t.ticket_id: [d for d in t.depends_on if d in ids] for t in tickets})
    if cyc: problems.append("depends_on vòng: " + " → ".join(cyc))
    return problems


def _cycle(graph: dict[str, list[str]]) -> list[str]:
    """Một chu trình trong đồ thị phụ thuộc (rỗng nếu không có) — bắt ở bước lập kế hoạch, trước gate, không để tới dispatch."""
    state: dict[str, int] = {}; stack: list[str] = []
    def visit(n: str) -> list[str]:
        state[n] = 1; stack.append(n)
        for m in graph.get(n, []):
            if state.get(m) == 1: return [*stack[stack.index(m):], m]
            if m not in state and (c := visit(m)): return c
        stack.pop(); state[n] = 2; return []
    for n in graph:
        if n not in state and (c := visit(n)): return c
    return []
