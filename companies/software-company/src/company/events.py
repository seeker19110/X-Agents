from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field
from xagents_core.events import SCHEMA_VERSION as SCHEMA_VERSION
from xagents_core.events import AuditLog as CoreAuditLog
from xagents_core.events import Envelope as CoreEnvelope
from xagents_core.events import SharedContext as CoreSharedContext
from xagents_core.events import SupervisorAction as CoreSupervisorAction
from xagents_core.events import SupervisorActionKind as SupervisorActionKind
from xagents_core.events import can_transition as _can_transition

from .roles import BUILD_PHASES, ROLE, Assignee, BuildPhase, ReviewSource

Topic = Literal[
    "research-requests", "research-findings", "requirements-draft",
    "clarification-questions", "clarification-answers", "approved-specs",
    "tasks", "test-suites", "pull-requests", "review-results", "release-candidates",
    "release-events", "incidents", "shared-context", "audit-log", "supervisor-actions",
    "change-requests", "acceptance-results", "external-feedback",
]
Namespace = Literal[
    "prd", "glossary", "design", "architecture", "api-contract", "schema", "threat-model",
    "infra", "analytics", "docs", "knowledge", "contract",
]

NAMESPACE_OWNERS: dict[str, set[str]] = {
    # ADR-0037 PR-5e: bốn namespace của khối nghiên cứu/kế hoạch về cùng một chủ — `product` (pha `research` ghi
    # glossary/design, pha `spec` ghi prd, pha `plan` ghi architecture/api-contract).
    "prd": {ROLE.PRODUCT}, "glossary": {ROLE.PRODUCT}, "design": {ROLE.PRODUCT},
    "architecture": {ROLE.PRODUCT}, "api-contract": {ROLE.PRODUCT, ROLE.BUILDER},
    "schema": {ROLE.BUILDER}, "threat-model": {ROLE.SECURITY}, "infra": {ROLE.BUILDER},
    "analytics": {ROLE.BUILDER}, "docs": {ROLE.OPS}, "knowledge": {ROLE.SUPERVISOR}, "contract": {ROLE.OPS},
}

# Namespace phạm vi toàn công ty (không thuộc dự án nào): bài học dùng chung cho mọi dự án.
GLOBAL_NAMESPACES = frozenset({"knowledge"})

# Ticket có bất kỳ tag nào dưới đây bắt buộc thêm review của `security` (ADR-0003).
RISK_TAGS = frozenset({"auth", "payment", "pii", "crypto", "upload", "admin", "external-api"})
BUDGET_FACTOR = 1.5  # budget_tokens ≥ estimate_tokens × BUDGET_FACTOR (skill cost-estimation)

# ADR-0037 PR-1: ticket vượt trần này phải chia nhỏ trước khi qua `_check_plan` (dời từ mục "Code gửi kèm" của
# gate plan cũ — mọi khoá gate plan nay là một kiểm ở `_check_plan`, không còn chỗ nào chỉ người mới thấy).
MAX_TICKET_TOKENS = 200_000
# Từ khoá trong title/scope/acceptance (so khớp không phân biệt hoa thường) buộc ticket phải khai `risk_tags`.
RISK_HINTS = frozenset({
    "auth", "login", "password", "payment", "thanh toán", "pii", "cccd", "email",
    "crypto", "upload", "admin", "webhook", "external",
})
# Hint nào suy được thẳng ra MỘT tag trong RISK_TAGS thì `_check_plan` tự gắn tag thay vì từ chối cả kế hoạch
# (đo 2026-09-22, CAMPUS-UNI: hai lượt `plan_rejected` liên tiếp chỉ vì thiếu đúng một khoá suy được từ đây —
# tốn một lượt model đầy đủ mỗi lần). Hint KHÔNG có mặt ở đây (bảng chưa phủ hết `RISK_HINTS`) vẫn bị từ chối
# như cũ, không đoán bừa.
HINT_TO_TAG: dict[str, str] = {
    "auth": "auth", "login": "auth", "password": "auth",
    "payment": "payment", "thanh toán": "payment",
    "pii": "pii", "cccd": "pii",
    "crypto": "crypto",
    "upload": "upload",
    "admin": "admin",
    "email": "external-api", "webhook": "external-api", "external": "external-api",
}



class Ruling(BaseModel):
    """ADR-0030 — sổ Ruling: quyết định agent TỰ đưa ra thay vì dừng chờ người. Ba phần bắt buộc, không phần nào
    được bỏ: `decision` (quyết gì), `why` (căn cứ: spec, shared-context, quy ước), `cost_if_wrong` (sai thì mất gì —
    để người soát biết có đáng lật lại không). Chỉ bốn việc được phép dừng chờ người: không đảo ngược được; nhạy cảm
    bảo mật; tác động ra ngoài worktree (merge/push/publish); kế hoạch hỏng tới mức mọi hướng đều là đoán."""
    decision: str
    why: str
    cost_if_wrong: str


class Envelope(CoreEnvelope):
    """Khung ở `xagents_core.events` (K3.5a). Ở đây chỉ thu hẹp `topic` về Literal của công ty này — đó là chỗ
    duy nhất biết đủ để làm việc ấy, và nhờ nó `bus.publish` vẫn đỏ khi ai đó gửi một topic không tồn tại."""

    topic: Topic


class Task(BaseModel):
    ticket_id: str
    project_id: str
    requirement_id: str
    assignee: Assignee
    # ADR-0037: mảng kỹ thuật của ticket = PHA của agent làm ticket (`AgentSpec.phases`), thay cho việc chọn một
    # agent riêng cho mỗi stack. Từ PR-5d `assignee` chỉ còn một giá trị (`builder`) nên đây là trường DUY NHẤT
    # nói ticket thuộc mảng nào; thiếu nó thì `routes.phase_for` trả None và builder chạy bằng prompt chung.
    stack: BuildPhase | None = None
    title: str
    acceptance: list[str]
    scope: list[str] = []
    estimate_days: float = 0.5
    depends_on: list[str] = []
    retry: int = 0
    hint: str | None = None
    # Hướng dẫn của NGƯỜI (gate escalation `reopen`, `comment`). Tách khỏi `hint` vì `hint` bị delivery-lead ghi
    # đè bằng thông điệp máy mỗi lần retry ("lần trước lỗi: ..."), nên chẩn đoán của người — thứ giá trị nhất —
    # là thứ mất đầu tiên. Đo được 2026-09-06 (QLKH-012): hint chi tiết sống đúng MỘT lượt rồi bị thay.
    human_hint: str | None = None
    estimate_tokens: int | None = None
    budget_tokens: int = 120_000
    risk_tags: list[str] = []
    budget_usd: float | None = None  # trần chi phí tiền của ticket (tuỳ chọn); supervisor cắt khi chạm, ngoài budget_tokens
    priority: int = 3  # 1 = cao nhất (WSJF/MoSCoW quy về 1..5); delivery-lead dispatch theo priority rồi thứ tự tạo
    rulings: list[Ruling] = []  # ADR-0030

    #: Từ vựng `assignee` của thời 21 agent (trước ADR-0037/PR-5d). Sáu giá trị ấy trùng đúng `BUILD_PHASES`:
    #: chúng không biến mất khi gộp agent, chúng ĐỔI CHỖ — từ "ai làm" sang "mảng kỹ thuật nào" (`Task.stack`).
    _ASSIGNEE_CU: ClassVar[frozenset[str]] = frozenset(BUILD_PHASES)

    @classmethod
    def tu_log(cls, raw: dict[str, Any]) -> Task:
        """Dựng `Task` từ một bản ghi CŨ đọc lại từ bus/audit-log — dùng ở MỌI đường phát lại.

        `Assignee` nay là `Literal["builder"]`, nhưng bus là bản ghi bền và bất biến: mọi ticket lập trước PR-5d
        còn mang `assignee` là một trong sáu stack. `model_validate` thẳng tay trên chúng ném `ValidationError`
        giữa `_rehydrate`, tức là trong `Orchestrator.__init__`, nên **không lệnh nào** mở nổi DB đó nữa — kể cả
        `status` chỉ đọc. Đo trên `company.sqlite` của QLKH (2026-09-09): 18 293 event còn nguyên vẹn mà công ty
        không khởi động lại được. Thắt schema thì phải nới đường ĐỌC LẠI lịch sử.

        Không vứt thông tin: `assignee: "platform"` cũ mang đúng nghĩa `stack: "platform"` ngày nay, nên nó
        chuyển sang `stack` (chỉ khi bản ghi chưa có `stack` riêng — bản ghi mới hơn thì tôn trọng nó).

        Khoan dung ĐÚNG sáu giá trị lịch sử: `assignee` lạ vẫn ném, để một kế hoạch hỏng thật không lặng lẽ
        biến mất khỏi hàng đợi sau restart.
        """
        if raw.get("assignee") in cls._ASSIGNEE_CU:
            raw = {**raw, "assignee": ROLE.BUILDER, "stack": raw.get("stack") or raw["assignee"]}
        return cls.model_validate(raw)


class PullRequest(BaseModel):
    ticket_id: str
    branch: str
    pr_ref: str
    summary: str = ""
    impact: dict[str, Any] = {}
    local_checks: dict[str, Any]
    project_id: str | None = None  # orchestrator điền từ ticket: blackboard và chi phí phân vùng theo dự án (ADR-0018)
    rulings: list[Ruling] = []  # ADR-0030
    # ADR-0033: bằng chứng ngoài `local_checks` — hiện dùng `screenshots[]` cho ticket frontend. Hình mở (dict)
    # vì mỗi loại bằng chứng có hình dạng riêng; ràng buộc từng loại nằm ở JSON Schema, không ở đây.
    evidence: dict[str, Any] = {}
    # Đường hợp lệ để khai "việc đã xong từ lượt trước, không cần sửa thêm" — cùng tinh thần `test_dispute`:
    # agent tự đối chiếu với acceptance criteria rồi giải thích VÌ SAO không sửa gì, thay vì im lặng bị tính
    # invalid_output (TCK-CR-RUNTIME-01, 2026-09-06). Ngưỡng độ dài xác thực ở runner, không ở đây.
    no_changes_reason: str | None = None

class Finding(BaseModel):
    level: Literal["block", "warn", "nit"]
    text: str
    location: str | None = None

class ReviewResult(BaseModel):
    ticket_id: str
    source: ReviewSource
    verdict: Literal["pass", "block", "fail"]
    findings: list[Finding] = []
    root_cause: str | None = None
    bug_reports: list[str] = []
    metrics: dict[str, Any] = {}
    project_id: str | None = None
    # Trường prompt reviewer/qa-debugger vẫn đòi (nay có trong schema, không còn lọt nhờ additionalProperties)
    sbom_ref: str | None = None
    # Model trả câu tóm tắt hoặc object theo từng loại scan/test: nhận cả hai, không ép model đổi hình đầu ra
    scan_summary: str | dict[str, Any] | None = None
    test_summary: str | dict[str, Any] | None = None
    mutation_score: float | None = None
    perf: dict[str, Any] | None = None
    a11y: dict[str, Any] | None = None
    rulings: list[Ruling] = []  # ADR-0030

class SharedContext(CoreSharedContext):
    # `project_id` và `content` lên core ở K3.6b cùng `blackboard.py` — chúng là cơ chế của blackboard, không
    # phải trường của miền company (xem docstring `xagents_core/events.py`). Ở lại đây đúng một thứ: `rulings`.
    namespace: Namespace
    # `default_factory` thay `= []`: lớp cha nay ở package khác nên ruff không nhận ra đây là model
    # pydantic và báo RUF012. Pydantic vốn deep-copy default nên hành vi không đổi.
    rulings: list[Ruling] = Field(default_factory=list)  # ADR-0030


class AuditLog(CoreAuditLog):
    ticket_id: str | None = None
    project_id: str | None = None
    # Token ĐẦU RA riêng. `tokens` (ở lớp cha) là tổng (input + output) và phình theo số lượt tool vì mỗi lượt
    # gửi lại cả hội thoại, nên nó không đo được "agent đã làm bao nhiêu việc". Ngân sách ticket dùng trường này.
    output_tokens: int = 0
    cost_usd: float = 0.0  # từ bảng giá `prices` trong llm.yaml; 0 khi model không có giá (supervisor đếm `unpriced`)
    # `default_factory` thay `= []`: lớp cha nay ở package khác nên ruff không nhận ra đây là model
    # pydantic và báo RUF012. Pydantic vốn deep-copy default nên hành vi không đổi.
    rulings: list[Ruling] = Field(default_factory=list)  # ADR-0030
    phase: str | None = None  # ADR-0037: pha của lượt (`AgentSpec.phases`) — hai lượt cùng actor khác pha phân biệt được ở sổ


class ChangeRequest(BaseModel):
    """Khách yêu cầu đổi phạm vi sau khi spec đã duyệt (account-manager tạo). Không sửa spec trực tiếp."""
    change_id: str
    project_id: str
    requested_by: str
    description: str
    affects_requirements: list[str] = []
    impact: dict[str, Any] = {}
    decision: Literal["pending", "accepted", "rejected", "deferred"] = "pending"
    rulings: list[Ruling] = []  # ADR-0030

class AcceptanceResult(BaseModel):
    """Kết quả nghiệm thu (UAT) của khách trên một release (account-manager ghi nhận)."""
    release_id: str
    project_id: str
    verdict: Literal["accepted", "rejected", "conditional"]
    signed_by: str
    findings: list[Finding] = []
    evidence_ref: str | None = None
    rulings: list[Ruling] = []  # ADR-0030

class SupervisorAction(CoreSupervisorAction):
    project_id: str | None = None
    # `default_factory` thay `= []`: lớp cha nay ở package khác nên ruff không nhận ra đây là model
    # pydantic và báo RUF012. Pydantic vốn deep-copy default nên hành vi không đổi.
    rulings: list[Ruling] = Field(default_factory=list)  # ADR-0030


PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "tasks": Task, "pull-requests": PullRequest, "review-results": ReviewResult,
    "shared-context": SharedContext, "audit-log": AuditLog, "supervisor-actions": SupervisorAction,
    "change-requests": ChangeRequest, "acceptance-results": AcceptanceResult,
}

TicketState = Literal["draft", "waiting", "dispatched", "in_progress", "in_review", "changes_requested",
                      "approved", "merged", "released", "closed", "blocked", "escalated"]
TRANSITIONS: dict[str, set[str]] = {
    "draft": {"dispatched", "waiting"}, "waiting": {"dispatched"}, "dispatched": {"in_progress"},
    "in_progress": {"in_review"}, "in_review": {"changes_requested", "approved"}, "changes_requested": {"dispatched", "waiting"},
    "approved": {"merged", "changes_requested"}, "merged": {"released", "changes_requested"}, "released": {"closed", "changes_requested"},
    "blocked": {"dispatched", "escalated", "waiting"},
    "escalated": {"dispatched", "closed", "waiting"}, "closed": set(),
}
def can_transition(src: str, dst: str) -> bool:
    """Bảng `TRANSITIONS` là của công ty này; cơ chế ở `xagents_core.events`."""
    return _can_transition(src, dst, TRANSITIONS)
