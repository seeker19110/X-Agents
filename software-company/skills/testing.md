---
name: testing
standards: [ISO/IEC/IEEE 29119, ISTQB, Test pyramid, Contract testing (Pact), Mutation testing]
---
# Skill: testing

## Tiêu chuẩn tham chiếu
- ISO/IEC/IEEE 29119
- ISTQB
- Test pyramid
- Contract testing (Pact)
- Mutation testing

## Quy tắc
- Mọi Gherkin có test.
- Unit > integration > e2e.
- Mutation ≥ 70% module lõi.
- Perf test so NFR.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] Gherkin phủ 100%
- [ ] Mutation đạt
- [ ] Perf p95 đạt
- [ ] a11y pass

## Ví dụ tốt
Scenario 'refund quá hạn' → test_refund_after_window_rejected.

## Ví dụ xấu
Chỉ có test happy path.
