"""Vòng lặp `watch → triage → patch → verify → gate? → release` của `keeper` (BT7, `DAC-TA-KEEPER.md` §9).

Khuôn lấy từ `software-company/src/company/orch/scheduler.py` (`run`/`tick`/`watch`, `_audit`, một nhịp lỗi
không giết vòng watch). **Sao khuôn, không import chéo công ty** — `keeper` không phụ thuộc `company`.

## Trạng thái KHÔNG sống trong RAM

Mọi thứ orchestrator biết đều dựng lại được từ `keeper.sqlite` bằng `bus.replay()` lúc mở: ticket đã tạo
(`maintenance-tickets`), khoá chống-trùng của `triager` (suy từ `ticket_id`, xem `_apply`), bằng chứng đã đo
(`verification-reports`), dòng release đã soạn (`release-notes`), và sổ gate (`PersistentGate` tự replay
`audit-log`). Đó là điều kiện để `--watch` chết giữa chừng rồi chạy lại mà không làm lại việc đã làm — và là
một trong bốn khuôn lỗi lặp lại của X-Agents (`TRAPS.md`).

## Bốn cổng, không đi vòng

`pr_blockers()` là NƠI DUY NHẤT quyết định "được mở PR chưa", và nó gọi thẳng bốn cổng đã dựng ở BT4–BT6:

| Khoá | Cổng | Bất biến |
|---|---|---|
| `human-only` | `patcher.HUMAN_ONLY_SEGMENTS` — chạm `agents/`/`skills/` thì mở ticket `high` cho NGƯỜI | bảy bước `CONTRIBUTING.md` §3 |
| `evidence` | `evidence.check_report()` (qua `record_verification` và `_apply`) + worktree VẪN đúng `patch_id` đã đo (ADR keeper 0001) | I2 |
| `gate` | gate `keeper` approved cho ticket `risk_tier == "high"` | §9 |
| `budget` | `budget.can_open_pr()` — hỏi `gh` thật mỗi lần | I3 |

`human-only` là khoá VĨNH VIỄN: một người duyệt gate cũng không biến nó thành việc `keeper` tự làm — gate ở
đó để người biết mà làm, không phải để uỷ quyền ngược lại cho máy.

## "Mở PR" ở BT7 nghĩa là gì — và "publish" ở BT8 khác gì

`open_pr()` (BT7) soạn và phát `release-notes` + ghi `pr.intent` vào `audit-log` — chỉ Ý ĐỊNH. `gh pr create`
THẬT không nằm ở đây: `github.py` chỉ đọc (bất biến I1). Nói "mở PR" cho một hàm KHÔNG gọi `gh` sẽ là lời khai,
và `AGENTS.md` cấm §8 áp cho chính `keeper` trước tiên — nên cả tên hàm lẫn tên action đều nói ý định, không
nói kết quả.

`publish()` (BT8, `keeper/publish.py`) là bước KHÁC, gọi SAU `open_pr()`: nó push nhánh của ticket rồi
`gh pr create` thật, sau đó `release.fill_pr_number()` điền số PR thật vào dòng CHANGELOG/session-log đã soạn.
Nó không tự động — vòng lặp `watch` chưa nối scout→patch→verify→publish thành một chuỗi (không scout nào chạy
tự động trong `tick()`, patch cần `keeper run` hoặc người commit tay), nên `publish()` là bước NGƯỜI/script gọi
qua CLI `keeper publish <ticket_id>` sau khi patch đã commit vào worktree — không phải một nhịp tự động.

Chính vì `open_pr()` không tạo PR thật mà `gh.open_prs()` vẫn trả 0 ở ticket kế tiếp trong CÙNG một nhịp (bộ
đệm TTL của `GitHubReader` còn giữ câu trả lời cũ nữa). Nên cổng `budget` đếm THÊM những `release-notes` mà
`keeper` đã xin mở nhưng chưa thấy số PR thật (`outstanding_pr_intents`) — trạng thái ấy dựng lại được từ bus,
không phải một biến RAM. Không có nó, N ticket đủ cổng trong một nhịp ra N `release-notes` và I3 thủng mà
không cần đa luồng (`sc-qa` chấm BT7).
"""
from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .budget import GitHubLike, can_open_pr
from .bus import KeeperBus
from .core import CORE
from .events import AuditLog, Envelope, ReleaseNote, Signal, Ticket, VerificationReport
from .evidence import EvidenceError, TwoWayEvidence, build_report, check_report
from .gates import PersistentGate, gate_approvers, request_gate
from .github import GitHubWriteAttempt
from .patcher import HUMAN_ONLY_SEGMENTS
from .publish import PullRequest, PullRequestExists, create_pr, push_branch
from .release import compose, fill_pr_number
from .triage import ObservedSignal, TriageState, triager
from .worktree import KeeperWorktree, WorktreeError, content_tree

__all__ = ["BLOCKED_ACTION", "CODE_ACTOR", "HUMAN_ONLY", "REJECT_ACTION", "SUBJECT_OVERRIDDEN_ACTION",
           "KeeperOrchestrator", "TickResult", "touches_human_only"]

#: Khoá chặn "việc này của người" — hằng số chứ không chuỗi rời, vì cả `pr_blockers` lẫn test đều nêu tên nó.
HUMAN_ONLY = "human-only"

SCOUT_ACTOR = "dependency-scout"
TRIAGER_ACTOR = "triager"
VERIFIER_ACTOR = "regression-guard"
RELEASE_ACTOR = "release-clerk"

#: Actor của mọi bản ghi `audit-log` do CODE phát (`pr.intent`, `pr.blocked`, `tick_error`, `gate.requested`,
#: `verification.rejected`). KHÁC `GATE_ACTOR`: `keeper-supervisor` là một VAI agent có prompt riêng, và audit
#: ghi dưới tên vai ấy đọc như thể agent đã làm việc đó. Khuôn `LEAD_ACTOR` của company: tên riêng cho code, để
#: câu hỏi "agent làm hay code làm" trả lời được bằng `env.actor` chứ không bằng suy đoán.
CODE_ACTOR = "keeper-orchestrator"

#: Action ghi khi một `verification-reports` đến từ bus KHÔNG qua được `require_two_way` (bất biến I2).
REJECT_ACTION = "verification.rejected"

#: Action ghi khi payload model khai `ticket_id` KHÁC ticket của route: route thắng (khuôn `*_overridden` của company,
#: `ARCHITECTURE.md` gốc — danh tính event lấy từ ROUTE, không từ lời khai model).
SUBJECT_OVERRIDDEN_ACTION = "verification.subject_overridden"

#: Action ghi khi `open_pr` bị cổng chặn — chỉ khi tập cổng chặn ĐỔI, không phải mỗi nhịp (xem `open_pr`).
BLOCKED_ACTION = "pr.blocked"


def touches_human_only(subject: str) -> bool:
    """`agents/`/`skills/` là THÀNH PHẦN đường dẫn, không phải substring — cùng phép so `patcher.check_path`
    dùng, nhắc lại ở lớp quyết định để `pr_blockers` không phải chạm đĩa mới biết."""
    parts = subject.replace("\\", "/").split("/")
    return any(seg in parts for seg in HUMAN_ONLY_SEGMENTS)


@dataclass
class TickResult:
    """Kết quả một nhịp: ticket mới sinh, dòng release mới soạn, và các việc đã làm (để in ra `--watch`)."""
    tickets: list[Ticket] = field(default_factory=list)
    notes: list[ReleaseNote] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)


class KeeperOrchestrator:
    """Một tiến trình vòng lặp trên một `keeper.sqlite`. Nhiều tiến trình cùng file thì `bus.poll()` mỗi nhịp
    nạp event của nhau (gate CLI của người là tiến trình khác)."""

    #: Kiểm `require_two_way` ở đường NẠP event (`_apply`). Thuộc tính lớp để ca "chiều ngược" TẮT được đúng
    #: bản sửa rồi đo lại trên cùng event; mã sản xuất không bao giờ đổi nó.
    VERIFY_ON_APPLY = True

    #: Đếm `release-notes` chưa có số PR vào cổng `budget` (I3 trong cùng một nhịp). Cùng lý do như trên.
    INTENT_GUARD = True

    def __init__(self, db: Path, repo: Path, gh: GitHubLike, *, approvers: frozenset[str] | None = None,
                 env: Mapping[str, str] | None = None,
                 patch_identity: Callable[[str], str | None] | None = None) -> None:
        self.repo = Path(repo)
        self.gh = gh
        self.env = env
        # Danh tính nội dung HIỆN TẠI của worktree một ticket (ADR keeper 0001) — tiêm được, khuôn
        # `runner: CommandRunner`: ca kiểm thử cổng không cần git thật. Mặc định đo worktree thật của ticket.
        self.patch_identity: Callable[[str], str | None] = patch_identity or self._worktree_identity
        self.bus: KeeperBus = KeeperBus(CORE, db)
        self.signals: list[ObservedSignal] = []
        self.tickets: dict[str, Ticket] = {}
        self.reports: dict[str, VerificationReport] = {}
        self.verified: set[str] = set()
        self.notes: dict[str, ReleaseNote] = {}
        self.triage = TriageState()
        self.ticks = 0
        # Bản ghi từ chối bằng chứng: `_audited_rejects` là `event_id` đã CÓ bản ghi trên `audit-log` (đọc từ
        # `key` của envelope audit, không phải parse JSON), `_pending_rejects` là những cái phát hiện TRONG
        # lúc replay. Không audit ngay giữa vòng replay vì hai lẽ: `bus.replay()` đang đọc trên cùng kết nối
        # SQLite, và bản ghi từ chối của lần chạy trước còn nằm PHÍA SAU trong log — audit ngay là nhân bản
        # một dòng mỗi lần mở lại.
        self._audited_rejects: set[str] = set()
        self._pending_rejects: list[tuple[str, dict[str, Any]]] = []
        # `evidence` của bản ghi `pr.blocked` gần nhất mỗi ticket — dựng lại từ `audit-log`, không phải RAM thuần.
        self._last_blocked: dict[str, str] = {}
        self._replaying = True
        for env_ in self.bus.replay():
            self._apply(env_)
        self._replaying = False
        for event_id, data in self._pending_rejects:
            self._audit_reject(event_id, data)
        self._pending_rejects.clear()
        for topic in ("maintenance-signals", "maintenance-tickets", "verification-reports", "release-notes"):
            self.bus.subscribe(topic, self._apply)
        # Gate mở SAU replay của mình nhưng tự replay `audit-log` lấy sổ gate — hai nguồn không giẫm nhau vì
        # `_apply` ở đây bỏ qua `audit-log` (xem dưới).
        self.gate = PersistentGate(self.bus, approvers=approvers if approvers is not None else gate_approvers())

    # ---------- dựng lại trạng thái ----------

    def _apply(self, env: Envelope) -> None:
        """Một event → trạng thái. Chạy cho cả replay lúc mở lẫn event mới (subscribe), nên phải idempotent."""
        if env.topic == "audit-log":
            # Chỉ để biết event hỏng nào ĐÃ có bản ghi từ chối. `key` mang `event_id` bị từ chối, nên không
            # phải parse `evidence` (một dòng log xấu không được làm sập replay của cả orchestrator).
            # `audit-log` là topic MỞ (ai cũng ghi): chỉ bản ghi của code làm khoá, bản giả không nuốt được dòng thật.
            if env.actor != CODE_ACTOR:
                return
            if env.payload.get("action") == REJECT_ACTION:
                self._audited_rejects.add(env.key)
            elif env.payload.get("action") == BLOCKED_ACTION:
                self._last_blocked[str(env.payload.get("ticket_id"))] = str(env.payload.get("evidence"))
        elif env.topic == "maintenance-signals":
            self.signals.append(ObservedSignal(env.event_id, Signal.model_validate(env.payload)))
        elif env.topic == "maintenance-tickets":
            t = Ticket.model_validate(env.payload)
            self.tickets[t.ticket_id] = t
            # Sổ chống-trùng của `triager` dựng lại từ chính ticket: `signal_event_ids` là những envelope
            # signal ticket này đã tiêu thụ (`triage.py`). Lưu thêm một bản là hai nguồn cho một sự thật.
            self.triage.seen.update(t.signal_event_ids)
        elif env.topic == "verification-reports":
            r = VerificationReport.model_validate(env.payload)
            # **Cổng I2 đứng ở ĐƯỜNG TIÊU THỤ, không chỉ ở hàm dựng.** `verification_report()` chặn được lời
            # khai đi qua `record_verification()`, nhưng một event đến từ tiến trình KHÁC — hay từ replay của
            # một bus đã bị ghi thẳng — không đi qua hàm ấy. Nạp thẳng vào `self.verified` là mở cổng
            # `evidence` cho bất cứ ai publish được `verification-reports` (`sc-security` chấm BT7).
            if self.VERIFY_ON_APPLY:
                try:
                    self._check_report(r)
                except EvidenceError as e:
                    self._reject_report(env, r, e)
                    return
            self.reports[r.ticket_id] = r
            self.verified.add(r.ticket_id)
        elif env.topic == "release-notes":
            n = ReleaseNote.model_validate(env.payload)
            self.notes[n.ticket_id] = n

    def _publish(self, topic: str, key: str, actor: str, payload: dict[str, Any]) -> Envelope:
        return self.bus.publish(Envelope(topic=topic, key=key, actor=actor, payload=payload))  # type: ignore[arg-type]

    def _audit(self, action: str, data: dict[str, Any], *, ticket_id: str | None = None,
               key: str | None = None) -> None:
        a = AuditLog(actor=CODE_ACTOR, action=action, ticket_id=ticket_id,
                     evidence=json.dumps(data, ensure_ascii=False))
        self._publish("audit-log", key or CODE_ACTOR, CODE_ACTOR, a.model_dump())

    def _reject_report(self, env: Envelope, report: VerificationReport, err: EvidenceError) -> None:
        """Báo cáo không đạt hai chiều: KHÔNG vào `self.verified`, và ghi lý do — nuốt im lặng là đúng khuôn
        "chế độ hỏng không tự khai báo" (`TRAPS.md`).

        Ticket đã `verified` từ báo cáo TRƯỚC thì bị thu hồi: báo cáo mới nhất trên bus quyết định. Giữ báo cáo
        cũ không chống được giả mạo (kẻ ghi được topic này dựng được cả báo cáo trông hợp lệ), chỉ để cổng
        `evidence` mở trên bằng chứng mà lần đo sau đã phủ nhận."""
        self.verified.discard(report.ticket_id)
        self.reports.pop(report.ticket_id, None)
        data = {"ticket_id": report.ticket_id, "event_id": env.event_id, "error": str(err)[:300]}
        if self._replaying:
            self._pending_rejects.append((env.event_id, data))
            return
        self._audit_reject(env.event_id, data)

    def _audit_reject(self, event_id: str, data: dict[str, Any]) -> None:
        """Đúng MỘT bản ghi cho một event hỏng, dù mở lại bus bao nhiêu lần."""
        if event_id in self._audited_rejects:
            return
        self._audited_rejects.add(event_id)
        self._audit(REJECT_ACTION, data, ticket_id=str(data["ticket_id"]), key=event_id)

    # ---------- watch: nạp việc ----------

    def submit_signal(self, signal: Signal, *, actor: str = SCOUT_ACTOR) -> Envelope:
        """Một quan sát thô lên bus. `scout`/`health`/`drift` (BT3) gọi hàm này; người nạp tay cũng được
        (`maintenance-signals` là topic người ghi được, `core.py:HUMAN_TOPICS`)."""
        return self._publish("maintenance-signals", signal.subject, actor, signal.model_dump())

    # ---------- triage ----------

    def _triage(self, now: datetime) -> list[Ticket]:
        """Cả lô một lần: `triager` gộp trùng theo `(kind, subject)` NGAY TRONG lô, và chống trùng theo
        `event_id` nên hai chủ thể khác nhau không dùng chung một khoá. (Bản trước phải gọi từng signal một vì
        `generation` là tham số chung cho cả lời gọi — trục thế hệ ấy đã bỏ, lý do ở `triage.py`.)

        `triager` ghi vào một BẢN NHÁP của sổ: sổ thật chỉ nhận id qua `_apply` khi ticket đã lên bus. Đưa sổ
        thật vào thì publish lỗi giữa nhịp vẫn để id lại trong sổ, và nhịp sau nuốt signal tới khi mở lại."""
        out: list[Ticket] = []
        for t in triager(self.signals, state=TriageState(self.triage.seen), now=now):
            self._publish("maintenance-tickets", t.ticket_id, TRIAGER_ACTOR, t.model_dump())
            out.append(self.tickets[t.ticket_id])
        return out

    # ---------- verify (I2) ----------

    def _check_report(self, report: VerificationReport) -> None:
        """MỘT phép kiểm cho cả đường dựng (`record_verification`) lẫn đường nạp (`_apply`): hai đường mà kiểm
        khác nhau thì replay cho kết quả khác lần ghi. `check_report` (I2 + rà họ lỗi) cộng danh tính patch: báo
        cáo không nói nó đo nội dung nào thì không mở được cổng cho nội dung nào cả (ADR keeper 0001, mục b). Báo cáo
        mang `payload_error` (phần model kể sai hình, xem `record_verification`) không bao giờ đạt."""
        if report.payload_error is not None:
            raise EvidenceError(f"phần model kể của {report.ticket_id} sai hình, không dựng được báo cáo — chỉ còn số "
                                f"đo, không đủ để rời pha quality: {report.payload_error}")
        check_report(report)
        if report.patch_id is None:
            raise EvidenceError(f"báo cáo của {report.ticket_id} không mang patch_id — không biết nó đo nội dung "
                                "nào; chỉ bằng chứng từ collect_two_way mới gắn danh tính (ADR keeper 0001)")

    def record_verification(self, ticket_id: str, payload: Mapping[str, Any],
                            evidence: TwoWayEvidence) -> VerificationReport:
        """`payload` (phần model KỂ) + `evidence` (phần code ĐO) → `VerificationReport` đã qua `_check_report`.
        Ném `EvidenceError` nếu bằng chứng không đủ — ticket ở lại pha quality (I2).

        Không đạt thì báo cáo VẪN lên bus trước khi ném: `_apply` (subscribe đồng bộ) từ chối nó qua
        `_reject_report` — thu hồi `verified` của lần đo trước, ghi đúng một `verification.rejected` — và vì nó là
        báo cáo MỚI NHẤT của ticket trên bus, replay cho cùng kết quả thay vì dựng lại `verified` từ báo cáo cũ
        (ADR keeper 0001, mục c). Một đường thu hồi, không phải hai.

        **`ticket_id` là của ROUTE (tham số), không của payload.** Payload chỉ là phần model kể; để nó chọn khoá thì
        model đổi được ticket nào `verified`. Route ghi đè, lệch thì để lại `verification.subject_overridden`.

        **Payload sai hình** (pydantic `ValidationError`) cũng là một lần đo hỏng: phần kể bị bỏ hẳn, báo cáo dự
        phòng chỉ mang số đo + `payload_error`, nên `_check_report` luôn từ chối nó và nó đi đúng đường thu hồi trên.
        Không lên bus thì báo cáo đạt cũ đứng nguyên qua replay. Người gọi nhận `EvidenceError` (nguyên nhân là
        `ValidationError` gốc) — cùng một loại lỗi cho mọi cách "ticket ở lại pha quality"."""
        claimed = payload.get("ticket_id", ticket_id)
        if claimed != ticket_id:
            self._audit(SUBJECT_OVERRIDDEN_ACTION, {"ticket_id": ticket_id, "claimed_ticket_id": claimed},
                        ticket_id=ticket_id)
        cause: ValidationError | None = None
        try:
            report = build_report({**payload, "ticket_id": ticket_id}, evidence=evidence)
        except ValidationError as e:
            cause = e
            report = build_report({"ticket_id": ticket_id, "payload_error": str(e)[:1000]}, evidence=evidence)
        try:
            self._check_report(report)
        except EvidenceError as err:
            self._publish("verification-reports", report.ticket_id, VERIFIER_ACTOR, report.model_dump())
            if cause is not None:
                raise err from cause
            raise
        self._publish("verification-reports", report.ticket_id, VERIFIER_ACTOR, report.model_dump())
        return self.reports[ticket_id]

    def _worktree_identity(self, ticket_id: str) -> str | None:
        """`content_tree` của worktree ticket; không đo được (đã dọn, git lỗi) ⇒ `None` — không bao giờ bằng một
        danh tính đã đo, nên cổng đóng (fail closed)."""
        try:
            return content_tree(KeeperWorktree(repo=self.repo, ticket_id=ticket_id).path)
        except WorktreeError:
            return None

    def _evidence_current(self, ticket_id: str) -> bool:
        """Cổng `evidence`: có báo cáo đạt I2 VÀ worktree vẫn đúng nội dung báo cáo ấy đã đo. Từng `verified`
        không đủ — patch sửa tiếp sau lần đo là code chưa đo (ADR keeper 0001)."""
        if ticket_id not in self.verified:
            return False
        # no-ky-thuat: mỗi lần hỏi cổng là băm lại cả worktree (~50 ms cho 825 file vì index tạm không có stat), quay lại khi một lần pr_blockers đo được quá 1 s hoặc repo khách vượt ~10k file track
        current = self.patch_identity(ticket_id)
        return current is not None and current == self.reports[ticket_id].patch_id

    # ---------- gate? ----------

    def _gate_seen(self, ticket_id: str) -> bool:
        return ticket_id in self.gate.pending or any(r.subject_id == ticket_id for r in self.gate.history)

    def ensure_gate(self, ticket: Ticket) -> None:
        """Ticket `requires_gate` mà chưa có gate nào trong đời nó → xin một gate `patch`. Đúng một lần: gate
        đã đóng (`history`) thì KHÔNG xin lại — mở lại là quyết định riêng, phải phát `supervisor-actions`
        `resume` một cách tường minh (xem `gates.py`, mục 3)."""
        if not ticket.requires_gate or self._gate_seen(ticket.ticket_id):
            return
        request_gate(self.gate, "patch", ticket.ticket_id)
        self._audit("gate.requested", {"subject_id": ticket.ticket_id, "risk_tier": ticket.risk_tier},
                    ticket_id=ticket.ticket_id)

    # ---------- release ----------

    def outstanding_pr_intents(self) -> set[str]:
        """Ticket mà `keeper` đã XIN mở PR nhưng chưa thấy số PR thật.

        Dựng lại từ bus (`release-notes`), không phải biến RAM: `ReleaseNote.pr_number is None` nghĩa là dòng
        CHANGELOG còn mang chỗ trống `(#PR)` (`release.PR_PLACEHOLDER`), tức PR chưa tồn tại dưới dạng số. Ý
        định chỉ hết khi một `release-notes` sau đó mang `pr_number` — đường `release.fill_pr_number` (BT8)."""
        return {n.ticket_id for n in self.notes.values() if n.pr_number is None}

    def _budget_ok(self, ticket: Ticket) -> bool:
        """Cổng I3. Hai nguồn, cố ý thừa: `gh` (sự thật NGOÀI) và ý định của chính mình (sự thật TRONG). Chỉ
        hỏi `gh` là thủng ngay trong một nhịp — `open_pr()` không tạo PR thật nên `gh.open_prs()` vẫn trả 0 ở
        ticket thứ hai, và bộ đệm TTL của `GitHubReader` còn giữ câu trả lời cũ nữa."""
        if self.INTENT_GUARD and (self.outstanding_pr_intents() - {ticket.ticket_id}):
            return False
        return can_open_pr(self.gh, env=self.env)

    def pr_blockers(self, ticket: Ticket) -> list[str]:
        """Những cổng CHƯA qua, theo thứ tự từ "không bao giờ qua được" tới "hỏi lại sau là qua"."""
        blockers: list[str] = []
        if touches_human_only(ticket.subject):
            blockers.append(HUMAN_ONLY)
        if not self._evidence_current(ticket.ticket_id):
            blockers.append("evidence")
        if ticket.risk_tier == "high" and not self.gate.is_approved(ticket.ticket_id):
            blockers.append("gate")
        if not self._budget_ok(ticket):
            blockers.append("budget")
        return blockers

    def open_pr(self, ticket: Ticket) -> ReleaseNote | None:
        """Soạn dòng release và ghi ý định mở PR, hoặc `None` kèm audit nêu ĐÍCH DANH cổng chặn.

        Ghi lý do chặn vào `audit-log` chứ không im lặng trả `None`: một ticket đứng yên mà không ai biết vì
        sao là đúng khuôn "chế độ hỏng không tự khai báo" (`TRAPS.md`).

        Ghi khi tập cổng chặn ĐỔI, không phải mỗi nhịp: `watch` 5 giây một nhịp thì một ticket chờ người duyệt
        gate cả ngày là ~17k dòng y hệt nhau, và mọi lần mở lại đều `replay()` hết chúng. Đánh dấu SAU khi
        audit đã ghi: đánh dấu trước mà audit lỗi thì lý do chặn không bao giờ được ghi."""
        blockers = self.pr_blockers(ticket)
        if blockers:
            data = {"ticket_id": ticket.ticket_id, "blockers": blockers}
            evidence = json.dumps(data, ensure_ascii=False)
            if self._last_blocked.get(ticket.ticket_id) != evidence:
                self._audit(BLOCKED_ACTION, data, ticket_id=ticket.ticket_id)
                self._last_blocked[ticket.ticket_id] = evidence
            return None
        note = compose(ticket)
        self._publish("release-notes", note.ticket_id, RELEASE_ACTOR, note.model_dump())
        self._audit("pr.intent", {"ticket_id": ticket.ticket_id, "changelog_line": note.changelog_line},
                    ticket_id=ticket.ticket_id)
        return self.notes[ticket.ticket_id]

    def publish(self, ticket_id: str, wt: KeeperWorktree, *, remote: str = "origin", base: str = "main",
               now: datetime | None = None) -> PullRequest | None:
        """Biến ý định (`pr.intent`) thành PR THẬT (BT8 canary) — `git push` + `gh pr create`, rồi điền số PR
        thật vào dòng CHANGELOG/session-log đã soạn (`release.fill_pr_number`) bằng một commit THỨ HAI vào
        CHÍNH PR đó (`AGENTS.md` luật bắt buộc 10).

        Giả định: commit ĐẦU TIÊN (patch + dòng release mang `release.PR_PLACEHOLDER`) đã có sẵn trong
        `wt.path` — hàm này không tự vá, không tự commit lần đầu; nó chỉ publish. Idempotent: note đã có
        `pr_number` thì trả `None` ngay, không gọi `push`/`gh` lần hai (I3)."""
        # no-ky-thuat: không so danh tính patch lúc publish vì dòng CHANGELOG/nhật ký được ghi vào worktree SAU lần đo theo thiết kế nên khoảng open_pr → publish chưa kiểm, quay lại khi publish được nối tự động vào tick hoặc dòng release được ghi vào worktree trước lần đo
        note = self.notes.get(ticket_id)
        if note is None:
            raise ValueError(f"{ticket_id} chưa có release-notes — open_pr() chưa qua hết cổng?")
        if note.pr_number is not None:
            return None
        ticket = self.tickets[ticket_id]

        push_branch(wt, remote=remote)
        try:
            pr = create_pr(self.repo, title=f"fix(keeper): {ticket.subject}",
                           body=f"Ticket bảo trì `{ticket_id}` — mở tự động bởi keeper (I1), cần người merge.",
                           head=wt.branch, base=base)
        except PullRequestExists as e:
            pr = PullRequest(number=e.number, url=e.url)

        moc = now or datetime.now(UTC)
        moi = fill_pr_number(wt.path, note, pr.number, session_date=moc.strftime("%Y-%m-%d"))
        # Điền số chỉ trong worktree là chưa xong: phải thành commit THỨ HAI và lên remote, TRƯỚC khi note mang
        # `pr_number` lên bus — note có số rồi thì lần `publish()` sau trả sớm, và PR giữ `(#PR)` mãi.
        wt.commit_tracked(f"chore(keeper): điền số PR #{pr.number} cho {ticket_id}")
        push_branch(wt, remote=remote)
        self._publish("release-notes", ticket_id, RELEASE_ACTOR, moi.model_dump())
        self._audit("pr.created", {"ticket_id": ticket_id, "pr_number": pr.number, "url": pr.url},
                    ticket_id=ticket_id)
        return pr

    # ---------- vòng lặp ----------

    def tick(self, now: datetime | None = None) -> TickResult:
        """Một nhịp: nạp event tiến trình khác → triage → xin gate cho tier cao → thử mở PR cho ticket đủ cổng."""
        moc = now or datetime.now(UTC)
        self.bus.poll()
        res = TickResult(tickets=self._triage(moc))
        res.actions += [f"ticket:{t.ticket_id}" for t in res.tickets]
        for ticket in list(self.tickets.values()):
            # KHÔNG kiểm `ticket.status == "closed"`: không chỗ nào trong `keeper/src/` đặt trạng thái ấy, nên
            # nhánh đó là mã chết — và mã chết đọc như một cổng đang hoạt động (`sc-security` chấm BT7). Thứ
            # thật sự đánh dấu "đã xong một vòng" là có `release-notes`.
            if ticket.ticket_id in self.notes:
                continue
            self.ensure_gate(ticket)
            note = self.open_pr(ticket)
            if note is not None:
                res.notes.append(note)
                res.actions.append(f"pr:{ticket.ticket_id}")
        return res

    def watch(self, interval: float = 5.0, max_ticks: int | None = None) -> None:
        """`--watch` như hai công ty kia. Một nhịp lỗi (bus/git/`gh`) KHÔNG được giết vòng lặp: ghi
        `tick_error` vào `audit-log` rồi đi tiếp — nhưng ghi, không nuốt.

        `GitHubWriteAttempt` là NGOẠI LỆ và thoát thẳng ra: nó được khai là "không bao giờ được bắt và bỏ qua"
        (`github.py`), vì nó nghĩa là có mã đang thử GHI lên GitHub — bất biến I1 đã thủng. Ghi `tick_error`
        rồi chạy tiếp sau lỗi đó là để công ty vận hành trong đúng trạng thái mà I1 sinh ra để chặn."""
        n = 0
        while max_ticks is None or n < max_ticks:
            try:
                for a in self.tick().actions:
                    print(a)
            except GitHubWriteAttempt:  # I1 thủng — không nuốt vào tick_error, xem docstring
                raise
            except Exception as e:  # mọi lỗi khác của một nhịp: ghi lại rồi đi tiếp — xem docstring
                self._audit("tick_error", {"error": f"{type(e).__name__}: {str(e)[:300]}"})
                print(f"tick_error: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
            n += 1
            self.ticks = n
            if max_ticks is None or n < max_ticks:
                time.sleep(interval)
