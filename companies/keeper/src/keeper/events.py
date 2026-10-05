from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from xagents_core.events import SCHEMA_VERSION as SCHEMA_VERSION
from xagents_core.events import AuditLog as CoreAuditLog
from xagents_core.events import Envelope as CoreEnvelope
from xagents_core.events import SharedContext as CoreSharedContext
from xagents_core.events import SupervisorAction as CoreSupervisorAction
from xagents_core.events import SupervisorActionKind as SupervisorActionKind

# Đặc tả §1 (`DAC-TA-KEEPER.md`) viết "9 giá trị" — ĐẾM SAI, đã đo lại: bảng "Topic của keeper" ở §1 liệt kê
# tám topic riêng của công ty (maintenance-signals, maintenance-tickets, patch-proposals, verification-reports,
# security-findings, debt-ledger, release-notes, supervisor-actions) CỘNG hai topic mở dùng chung với hai công
# ty kia (audit-log, shared-context) = 10, không phải 9.
Topic = Literal[
    "maintenance-signals", "maintenance-tickets", "patch-proposals", "verification-reports",
    "security-findings", "debt-ledger", "release-notes", "supervisor-actions",
    "shared-context", "audit-log",
]
Namespace = Literal["knowledge"]
RiskTier = Literal["low", "medium", "high"]
SignalKind = Literal["dependency", "health", "drift", "security"]
SemverJump = Literal["patch", "minor", "major"]

ID_PATTERN = r"^[A-Za-z0-9_.:/-]{1,200}$"


class Envelope(CoreEnvelope):
    """Khung ở `xagents_core.events` (K3.5a); thu hẹp `topic` về `Literal` của `keeper` để publish một topic
    lạ vẫn đỏ ngay ở lớp kiểu, trước khi chạm bus."""

    topic: Topic


class Signal(BaseModel):
    """Một quan sát thô, chưa phán xét (`dependency-scout`, `health-monitor`, `drift-detector`,
    `adapter:github`). `triager` gộp các signal trùng nhau (`dedupe`, `signals.py`) rồi mới thành `Ticket`."""
    subject: str = Field(pattern=ID_PATTERN)  # đường dẫn file / tên gói / mã workflow bị chạm
    kind: SignalKind
    detail: str
    semver_jump: SemverJump | None = None  # chỉ có nghĩa với kind="dependency"
    # Chỉ có nghĩa với kind="security" (dependabot / code-scanning alert). Trường RIÊNG chứ không moi từ
    # `detail`: `risk.py` xếp `security >= high` thành tier `high`, và một quyết định rủi ro không được dựa
    # vào việc dò chuỗi trong văn bản tự do do NGOÀI công ty viết (`detail` nằm trong `untrusted_fields`).
    severity: Literal["low", "medium", "high", "critical"] | None = None
    is_dev: bool = False
    evidence: str = ""
    seen_count: int = 1
    source: str = "keeper"


class Ticket(BaseModel):
    """`maintenance-signals` đã gom (`triager`) + `risk_tier` + hạn xử lý."""
    ticket_id: str = Field(pattern=ID_PATTERN)
    subject: str
    risk_tier: RiskTier
    signal_subjects: list[str] = []
    #: `Envelope.event_id` của những `maintenance-signals` đã bị ticket này tiêu thụ. ĐÂY là sổ chống-trùng của
    #: `triager` ở dạng dựng lại được từ bus (`triage.py`): không có nó thì trạng thái ấy chỉ sống trong RAM.
    signal_event_ids: list[str] = []
    due_at: str | None = None
    requires_gate: bool = False
    status: Literal["open", "in_progress", "blocked", "closed"] = "open"


class PatchProposal(BaseModel):
    """Nhánh + diff + phạm vi do `patcher`/`refactorer` chuẩn bị trên worktree riêng của ticket."""
    ticket_id: str = Field(pattern=ID_PATTERN)
    branch: str
    operation: Literal["bump_dependency", "regen_derived", "fix_docs", "refactor"]
    summary: str
    files: list[str] = []


class RunOutcome(BaseModel):
    """Output THẬT của một lần chạy lệnh CI — không phải lời khai của model."""
    cmd: str
    exit_code: int
    output_tail: str = ""


class FamilySafeEntry(BaseModel):
    """Một chỗ cùng cơ chế ĐÃ SOI và kết luận an toàn, mang theo LÝ DO — hình thu hẹp của `family.SafeSite`
    cho bus (không có `mechanism`/`line`: chi tiết nội bộ của lượt rà, không cần lên topic).

    `reason` bắt buộc có nội dung: trước bản sửa này `family_safe` chỉ là `list[str]` đường dẫn — đúng lúc
    payload rời tiến trình để lên `verification-reports` thì lý do (thứ `family.py` ép buộc phải có,
    `family.py:62-67`) bị vứt, và cái lên bus lại là "lời khai" hình dạng `family.py` được viết ra để chống
    (`AGENTS.md` cấm §8, `TRAPS.md` §1)."""
    path: str
    reason: str = Field(min_length=1)


class VerificationReport(BaseModel):
    """Bằng chứng hai chiều bắt buộc (bất biến I2): `before.exit_code == 0` là báo cáo vô hiệu."""
    ticket_id: str = Field(pattern=ID_PATTERN)
    before: RunOutcome
    after: RunOutcome
    verified_by: Literal["workspace", "orchestrator"]
    family_hits: list[str] = []
    family_safe: list[FamilySafeEntry] = []
    #: Danh tính NỘI DUNG đã đo (`worktree.content_tree`, ADR keeper 0001): báo cáo chỉ mở cổng `evidence` khi
    #: worktree của ticket VẪN đúng nội dung này. Do `collect_two_way` đo, không bao giờ lấy từ payload model
    #: (`evidence.SELF_CLAIM_FIELDS`). `None` = báo cáo không nói nó đo gì (hình dạng trước ADR) ⇒ bị từ chối.
    patch_id: str | None = None
    #: Phần model KỂ không dựng được báo cáo (pydantic `ValidationError`): code điền lý do và bỏ hẳn phần kể, chỉ giữ
    #: số đo. Khác `None` ⇒ báo cáo không bao giờ đạt — nó tồn tại để lần đo hỏng vẫn THU HỒI bền qua bus (ADR keeper
    #: 0001, mục c), không để mở cổng. Model tự điền trường này chỉ làm báo cáo của chính nó hỏng (fail closed).
    payload_error: str | None = None


class SecurityFinding(BaseModel):
    """gitleaks / audit dependency / Scorecard, do `security-auditor` phát."""
    subject: str
    severity: Literal["low", "medium", "high", "critical"]
    kind: Literal["secret", "dependency", "scorecard"]
    detail: str


class DebtEntry(BaseModel):
    """Việc bảo trì đã hoãn, mang NGÀY đáo hạn.

    Không phải `debt_due` của lõi: cơ chế đó (`xagents_core/supervisor.py:82,102-123`) đếm **chuỗi review liên
    tiếp** không nhắc lại một mã nợ, không đo thời gian. `keeper` cần hạn theo lịch, nên đây là cơ chế riêng —
    tên khác nhau có chủ ý để không ai tưởng hai thứ là một."""
    subject: str
    reason: str
    due_at: str
    tier: RiskTier


class ReleaseNote(BaseModel):
    """Dòng `CHANGELOG.md` + mục nhật ký phiên do `release-clerk` soạn."""
    ticket_id: str = Field(pattern=ID_PATTERN)
    pr_number: int | None = None  # None trước khi có số PR (`AGENTS.md` §10)
    changelog_line: str
    session_line: str


class SharedContext(CoreSharedContext):
    namespace: Namespace


class AuditLog(CoreAuditLog):
    # Trường PHẠM VI của keeper, cùng vai trò `ticket_id` ở company / `video_id` ở studio — lý do `AuditLog`
    # lên core dưới dạng lớp cơ sở chứ không phải lớp dùng thẳng (xem docstring `xagents_core/events.py`).
    ticket_id: str | None = None


class SupervisorAction(CoreSupervisorAction):
    """Không thêm trường nào — khung core đã đủ cho `keeper-supervisor` (dừng, hạ hạn mức, escalate)."""


NAMESPACE_OWNERS: dict[str, set[str]] = {
    "knowledge": {"keeper-supervisor"},  # bài học chung công ty, không thuộc ticket nào (ADR-0018 của studio/company)
}

PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "maintenance-signals": Signal,
    "maintenance-tickets": Ticket,
    "patch-proposals": PatchProposal,
    "verification-reports": VerificationReport,
    "security-findings": SecurityFinding,
    "debt-ledger": DebtEntry,
    "release-notes": ReleaseNote,
    "supervisor-actions": SupervisorAction,
    "shared-context": SharedContext,
    "audit-log": AuditLog,
}
