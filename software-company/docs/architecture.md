# Kiến trúc

## Nguyên tắc

1. **Event-driven, không gọi trực tiếp**: agent chỉ nói chuyện qua topic. Mỗi topic có
   JSON Schema trong `topics/schemas/`, message không hợp lệ bị từ chối ở bus.
2. **Key = ticket ID**: mọi message thuộc một ticket đi cùng partition, giữ thứ tự.
3. **Blackboard có chủ**: `shared-context` chia theo namespace, mỗi namespace chỉ một
   agent được ghi (database ghi `schema`, backend ghi `api-contract`, delivery-lead ghi
   `architecture`, spec-writer ghi `prd`). Ai cũng đọc được.
4. **Tính xác định ở đâu có thể**: lint, test, scan, build là tool trả kết quả cứng;
   LLM chỉ diễn giải và quyết định bước tiếp theo.
5. **Hạn mức mọi nơi**: retry, timeout, token đều có ngưỡng; hết ngưỡng thì escalate
   chứ không âm thầm đi tiếp.
6. **Truy vết**: mọi artifact có `requirement_id` gốc; mọi hành động ghi `audit-log`.

## Topic

| Topic | Producer | Consumer | Key |
|-------|----------|----------|-----|
| research-requests | human / support-docs | intake | project_id |
| research-findings | domain, codebase, tech-scout | synthesizer | project_id |
| requirements-draft | synthesizer | risk, clarifier | project_id |
| clarification-questions | clarifier | human gate | project_id |
| clarification-answers | human gate | intake | project_id |
| approved-specs | human gate | delivery-lead | project_id |
| tasks | delivery-lead | engineering | ticket_id |
| pull-requests | engineering | reviewer, qa-debugger | ticket_id |
| review-results | reviewer, qa-debugger | delivery-lead | ticket_id |
| release-candidates | delivery-lead | release-engineer | release_id |
| release-events | release-engineer | support-docs, human gate | release_id |
| incidents | support-docs | delivery-lead | incident_id |
| shared-context | theo namespace | tất cả | namespace |
| audit-log | tất cả | supervisor | actor |
| supervisor-actions | supervisor | tất cả | target |

## Vòng đời một ticket

```
delivery-lead: tasks(ticket, assignee=backend)
backend:       đọc shared-context → code trên branch → pull-requests(ticket)
reviewer:      review-results(ticket, verdict=pass|block, findings[])
qa-debugger:   review-results(ticket, verdict=pass|fail, root_cause?, repro?)
delivery-lead: cả hai pass → release-candidates; fail → tasks(ticket, retry+1, hint)
supervisor:    retry > MAX_RETRY hoặc token > budget → supervisor-actions(pause, escalate)
```

## Trạng thái ticket

`draft → dispatched → in_progress → in_review → changes_requested → approved → released → closed`
cộng `blocked` và `escalated` có thể vào từ bất kỳ trạng thái nào.

## Human gate

Ba điểm bắt buộc: `approved-specs`, plan sau delivery-lead, `release-events` production.
Timeout 24h, supervisor nhắc ở 12h. Không bao giờ tự đi tiếp.

## Tích hợp với repo MEP-Agents

- Dùng lại `src/usage.py` để đo token theo agent.
- Dùng lại `src/workspace.py` cho branch/worktree riêng mỗi engineering agent.
- Reviewer guardrail dùng cùng cơ chế `MAX_REVIEW_RETRIES`.
- Checkpointer SQLite dùng chung `CHECKPOINT_DB`.
