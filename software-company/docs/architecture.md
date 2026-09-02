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
| research-requests | human / support-docs | intake | project_id |
| research-findings | domain, ux-designer, codebase, tech-scout | synthesizer | project_id |
| requirements-draft | synthesizer | risk, clarifier, ux-designer | project_id |
| clarification-questions | clarifier | human gate | project_id |
| clarification-answers | human gate | intake | project_id |
| approved-specs | human gate | delivery-lead, security-engineer | project_id |
| tasks | delivery-lead | engineering (6 agent) | ticket_id |
| pull-requests | engineering | reviewer, qa-debugger, security-engineer (khi risk_tags) | ticket_id |
| review-results | reviewer, qa-debugger, security-engineer | delivery-lead | ticket_id |
| release-candidates | delivery-lead | release-engineer, security-engineer | release_id |
| release-events | release-engineer | support-docs, human gate | release_id |
| incidents | support-docs | delivery-lead | incident_id |
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
delivery-lead:      đủ review bắt buộc và tất cả pass → release-candidates
                    có fail/block → tasks(ticket, retry+1, hint); retry ≥ 3 → blocked
supervisor:         retry > MAX_RETRY hoặc token > budget → supervisor-actions(pause, escalate)
```

Review bắt buộc: `{reviewer, qa}` ∪ `{security nếu risk_tags}` — code trong
`DeliveryLead.required_reviews`.

## Trạng thái ticket

`draft → dispatched → in_progress → in_review → changes_requested → approved → released → closed`
cộng `blocked` và `escalated` có thể vào từ bất kỳ trạng thái nào.

## Human gate

Ba điểm bắt buộc: `approved-specs`, plan sau delivery-lead (kèm threat model), `release-events`
production. Timeout 24h, supervisor nhắc ở 12h. Không bao giờ tự đi tiếp. Checklist trong
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
