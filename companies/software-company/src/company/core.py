"""`CORE` — công ty gia công phần mềm, nhìn từ `xagents_core` (ADR gốc 0001 §2).

Một chỗ DUY NHẤT nói "công ty này tên COMPANY, gốc ở đây, bus tên `company.sqlite`". Mọi module của company cần
một trong ba thứ đó thì đọc từ đây, không tự dựng lại từ `__file__` của mình — hai nguồn cho một sự thật thì sớm
muộn chúng lệch (và lệch đường dẫn gốc là đọc nhầm `llm.yaml` của repo khác mà không có lỗi nào nổi lên).

K3.4 điền ba trường của guard (`external_topics`, `derived_topics`, `untrusted_fields`); K3.5b điền
`topic_acl`, `payload_models`, `namespace_owners` khi bus chuyển sang core. `transitions` vẫn để trống: nó là
việc của `can_transition`, không phải của bus, và khai trước một bảng rỗng là mời người sau tin vào nó.

Bảng `topic_acl` ở đây là bảng `TOPIC_PRODUCERS`/`HUMAN_TOPICS`/`OPEN_TOPICS` **chuyển nguyên văn** từ
`bus.py`, không viết lại — company không đổi một hành vi nào ở K3.5b.

`extra_injection_patterns` để TRỐNG có chủ ý: bảng chung của `xagents_core.guard` đã là bảng của company. Hai
mẫu riêng của studio (`developer mode`, `jailbreak`) cố ý KHÔNG có ở đây — chúng là từ vựng nghiệp vụ hợp lệ của
một công ty phần mềm (`skills/mobile.md` dùng "jailbreak" cho yêu cầu bảo mật app di động), thêm vào là làm
ticket bảo mật mobile bị `injection_detected` và không chạy được.
"""
from __future__ import annotations

from pathlib import Path

from xagents_core.config import CoreConfig, TopicACL

from .events import NAMESPACE_OWNERS, PAYLOAD_MODELS
from .roles import ENGINEERING, LEAD_ACTOR, ROLE, SOURCE

# Producer hợp lệ của mỗi topic — rút từ bảng topic trong docs/architecture.md và front matter `writes` của agent.
# Người (`human` / `human:<tên>`) chỉ được phát các topic đầu vào của khách/người duyệt (`human_topics`); agent chỉ
# phát topic mình khai `writes`. `audit-log` ai cũng ghi; `shared-context` kiểm theo `namespace_owners`. Bus là chốt
# chặn cuối: runner đã kiểm `writes`, nhưng CLI `publish` hay code gọi thẳng `bus.publish` cũng không được vượt quyền.
ENGINEERING_ACTORS = frozenset(ENGINEERING)
# ADR gốc 0035: họ actor reviewer có chữ ký (`reviewer:<id>`, `bus.REVIEWER_PREFIX`) được NỘP và QUYẾT change request
# thay người ở phạm vi `toan-bo`. Bus chỉ cho ghi; tin hay không là `gate_reviewer.cr_trusted` lúc orchestrator áp.
REVIEWER_FAMILY = "reviewer:*"
REVIEW_PRODUCERS = frozenset({ROLE.QA, ROLE.SECURITY, SOURCE.QA, SOURCE.SECURITY})  # tên agent hoặc `source`
TOPIC_PRODUCERS: dict[str, frozenset[str]] = {
    "research-requests": frozenset({ROLE.OPS}),
    "research-findings": frozenset({ROLE.PRODUCT}),
    "requirements-draft": frozenset({ROLE.PRODUCT}),
    "clarification-questions": frozenset({ROLE.PRODUCT}),
    "clarification-answers": frozenset(),
    "approved-specs": frozenset({ROLE.PRODUCT}),
    # ADR-0037 PR-5e: HAI producer, hai vai khác nhau — `LEAD_ACTOR` là CODE (`delivery.py`) đóng vòng dispatch
    # sau `_check_plan`, `product` là AGENT sinh danh sách ticket (front matter `writes: tasks`, và `runner`
    # publish dưới danh nghĩa agent trong eval). Trước PR-5e hai thứ này tình cờ cùng một chuỗi nên không ai
    # phải nói ra. Chốt chặn "ticket chỉ ra đời sau khi kế hoạch qua kiểm" KHÔNG nằm ở đây mà ở
    # `DeliveryLead.dispatch` (`plans_ok`, PR-2) — bảng này chỉ nói ai được phát topic, không nói khi nào.
    "tasks": frozenset({LEAD_ACTOR, ROLE.PRODUCT}),
    "pull-requests": ENGINEERING_ACTORS,
    "test-suites": frozenset({ROLE.QA}),  # ADR-0028: bộ test do một vai KHÁC người viết code phát (qa, pha `author`)
    "review-results": REVIEW_PRODUCERS,
    "release-candidates": frozenset({LEAD_ACTOR}),
    "release-events": frozenset({ROLE.OPS}),
    "incidents": frozenset({ROLE.OPS}),
    "external-feedback": frozenset(),
    # ADR-0051: `LEAD_ACTOR` là CODE (`DeliveryLead._request_replan`) nộp CR `REPLAN-<ticket>-<thế hệ>` khi ticket hết
    # retry — coordinator leo thang retry → replan → người. Người vẫn quyết (`decide-change`), bảng này chỉ nói ai được nộp.
    "change-requests": frozenset({ROLE.OPS, LEAD_ACTOR, REVIEWER_FAMILY}),
    "acceptance-results": frozenset({ROLE.OPS}),
    "supervisor-actions": frozenset({ROLE.SUPERVISOR}),
}
# Topic người được phát: đầu vào của khách (`orchestrator publish`), quyết định change request (`decide-change`),
# PR khi tiếp quản ticket (`takeover`), resume sau gate escalation (supervisor-actions).
HUMAN_TOPICS = frozenset({"research-requests", "clarification-answers", "external-feedback", "acceptance-results",
                          "change-requests", "pull-requests", "supervisor-actions"})
OPEN_TOPICS = frozenset({"audit-log", "shared-context"})  # audit: ai cũng ghi; shared-context: kiểm theo namespace

CORE = CoreConfig(
    prefix="COMPANY",
    root=Path(__file__).resolve().parents[2],   # software-company/ : llm.yaml, agents/, skills/, topics/schemas/
    db_name="company.sqlite",
    global_namespaces=frozenset({"knowledge"}),   # ADR-0018: namespace toàn công ty, không thuộc dự án nào
    topic_acl=TopicACL(producers=TOPIC_PRODUCERS, human_topics=HUMAN_TOPICS, open_topics=OPEN_TOPICS,
                       engineering_actors=ENGINEERING_ACTORS, review_producers=REVIEW_PRODUCERS),
    payload_models=PAYLOAD_MODELS,
    namespace_owners=NAMESPACE_OWNERS,
    # Topic mà payload đến từ ngoài công ty (khách, người dùng, hệ thống ngoài): lọc thay vì từ chối.
    external_topics=frozenset({"external-feedback", "research-requests", "clarification-answers",
                               "acceptance-results", "incidents", "change-requests"}),
    # Topic nội bộ nhưng payload dẫn xuất từ code/tài liệu khách: lọc thay vì từ chối (từ chối = lặp vô tận).
    derived_topics=frozenset({"pull-requests", "research-findings", "review-results"}),
    # `hint` và `content` KHÔNG nằm đây: chúng do agent nội bộ viết (delivery-lead, chủ namespace), nên injection
    # ở đó là dấu hiệu agent bị chiếm — từ chối chạy mới đúng.
    untrusted_fields=frozenset({"diff", "web", "fetched", "attachments", "text", "description", "feedback",
                                # chuỗi trích từ repo khách hoặc model viết tự do về nó: mô tả PR, tên file đã
                                # sửa, log lint/test (`local_checks.lint_output`), stdout của lệnh
                                "summary", "title", "body", "notes", "message", "comment",
                                "lint_output", "test_output", "changed_files", "files", "logs", "output", "stdout"}),
)
