# Kiến trúc

## Nguyên tắc

1. **Event-driven, không gọi trực tiếp**: agent chỉ nói chuyện qua topic. Mỗi topic có
   JSON Schema trong `topics/schemas/`, message không hợp lệ bị từ chối ở bus.
2. **Key = ticket ID**: mọi message thuộc một ticket đi cùng partition, giữ thứ tự.
3. **Blackboard có chủ**: `shared-context` chia theo namespace, mỗi namespace chỉ một
   agent được ghi (bảng trong `topics/README.md`). Ai cũng đọc được.
4. **Tính xác định ở đâu có thể**: lint, test, scan, build, đóng vòng review là code trả
   kết quả cứng; LLM chỉ diễn giải và quyết định bước tiếp theo.
5. **Hạn mức mọi nơi**: retry, timeout, token đều có ngưỡng; hết ngưỡng thì escalate
   chứ không âm thầm đi tiếp.
6. **Truy vết**: mọi artifact có `requirement_id` gốc; mọi hành động ghi `audit-log`.
7. **Prompt là code** (ADR-0004): agent/skill có version, đi qua PR, rollback bằng revert.
8. **Ước lượng trước khi làm** (skill cost-estimation): ticket không có `estimate_tokens`
   không được dispatch; budget = estimate × 1.5.
9. **Bảo mật đi trước code** (ADR-0003): threat model trước ticket đầu; ticket có
   `risk_tags` cần review của security-engineer, tách khỏi reviewer.

## Topic

| Topic | Producer | Consumer | Key |
|-------|----------|----------|-----|
| research-requests | human / support-docs / account-manager | intake | project_id |
| research-findings | intake, researcher | synthesizer, researcher | project_id |
| requirements-draft | synthesizer | risk, clarifier, researcher | project_id |
| clarification-questions | clarifier | human gate | project_id |
| clarification-answers | human gate | intake | project_id |
| approved-specs | human gate | delivery-lead, security-engineer, account-manager | project_id |
| tasks | delivery-lead | engineering (6 agent) | ticket_id |
| pull-requests | engineering | reviewer, qa-debugger, security-engineer (khi risk_tags) | ticket_id |
| review-results | reviewer, qa-debugger, security-engineer | delivery-lead | ticket_id (hoặc release_id cho QA staging) |
| release-candidates | delivery-lead | release-engineer, security-engineer | release_id |
| release-events | release-engineer | delivery-lead, qa-debugger (staging), support-docs, account-manager (production), human gate | release_id |
| incidents | support-docs | delivery-lead | incident_id |
| external-feedback | human (khách, người dùng) | support-docs, account-manager | project_id |
| change-requests | account-manager | delivery-lead, intake | change_id |
| acceptance-results | account-manager | delivery-lead | release_id |
| shared-context | theo namespace | tất cả | namespace |
| audit-log | tất cả | supervisor | actor |
| supervisor-actions | supervisor | tất cả | target |

## Vòng đời một ticket

```
delivery-lead:      tasks(ticket, assignee, estimate_tokens, risk_tags?)
engineering:        đọc shared-context → code trên branch → pull-requests(ticket)
reviewer:           review-results(source=reviewer, verdict=pass|block, findings[])
qa-debugger:        review-results(source=qa, verdict=pass|fail, root_cause?)
security-engineer:  review-results(source=security) — chỉ khi ticket có risk_tags
delivery-lead:      đủ review bắt buộc và tất cả pass → approved → release-candidates
                    có fail/block → tasks(ticket, retry+1, hint); retry ≥ 3 → blocked
                    ticket có depends_on chưa xong → waiting; tự dispatch theo priority khi phụ thuộc approved
release-engineer:   gộp branch → build/test/scan/sign → release-events(env=staging) → ticket merged
qa-debugger:        hồi quy + perf + a11y trên staging → review-results(ticket_id=release_id, source=qa)
delivery-lead:      QA staging pass → xin human gate 3; fail → ticket quay lại với hint
release-engineer:   gate 3 approve → release-events(env=production) → ticket released; rolled_back → ticket quay lại
account-manager:    UAT với khách → acceptance-results(accepted → closed | rejected → ticket quay lại | conditional)
supervisor:         retry > MAX_RETRY, token > budget, review quá 2h → supervisor-actions(warn, pause, escalate)
```

Review bắt buộc: `{reviewer, qa}` ∪ `{security nếu risk_tags}` — code trong
`DeliveryLead.required_reviews`.

## Trạng thái ticket

`draft → (waiting) → dispatched → in_progress → in_review → changes_requested → approved → merged → released → closed`
cộng `blocked` và `escalated` có thể vào từ bất kỳ trạng thái nào.

## Human gate

Ba điểm bắt buộc của công ty: `approved-specs`, plan sau delivery-lead (kèm threat model), release production
(chỉ sau khi QA staging pass). Điểm thứ tư thuộc về khách: nghiệm thu (`acceptance-results`, người ký của khách,
account-manager ghi nhận). Timeout 24h, supervisor nhắc ở 12h. Không bao giờ tự đi tiếp. Checklist trong
`gates/checklists.md`.

## Thành phần dùng chung (đứng độc lập, không phụ thuộc repo khác)

- **Đo token**: mỗi agent phát `audit-log.tokens`; supervisor cộng dồn theo ticket
  (`Supervisor.budgets`). Không cần thư viện usage bên ngoài.
- **Workspace**: mỗi engineering agent làm trên branch `ticket/<id>` trong worktree riêng;
  reviewer chỉ đọc diff của branch đó.
- **Guardrail review**: `DeliveryLead.max_retries` (mặc định 3) và `Supervisor.max_retries`
  dùng cùng một giá trị.
- **Bus**: `InMemoryBus` cho test/demo; đổi sang Redis Streams/Kafka bằng cách giữ nguyên
  interface `publish/subscribe/replay`.
- **Checkpoint**: LangGraph (tùy chọn, `graph.py`) — checkpointer do người triển khai chọn.

## Orchestrator (ADR-0007)

`company.orchestrator` là vòng lặp nối các dòng trong bảng topic ở trên: mỗi event → tra `ROUTES` → gọi runner →
publish → event mới. Bảng route phải khớp front matter `reads`/`writes` (kiểm lúc khởi tạo). Ba chỗ vòng lặp dừng và
chờ người: gate `spec` (`SPEC-<project>`), gate `plan` (`PLAN-<project>-<n>`, sau khi delivery-lead sinh ticket và
code kiểm estimate/budget/depends_on), gate `release` (`REL-xxx`, production). Ticket bị supervisor pause/budget_cut/
escalate thì event của nó bị hoãn đến `resume`. Đầu vào của người (`clarification-answers`, `acceptance-results`,
`change-requests` decision, `external-feedback`) đi qua `orchestrator publish`. Mỗi event xử lý xong ghi
`audit-log` action=orchestrated; mở lại bus SQLite thì replay dựng lại trạng thái và xếp hàng phần chưa xử lý.
