---
name: frontend
version: 1
standards: [WCAG 2.2 AA, Core Web Vitals, CSP, OWASP client-side]
---
# Skill: frontend

## Tiêu chuẩn tham chiếu
- WCAG 2.2 AA
- Core Web Vitals
- CSP
- OWASP client-side

## Quy tắc
- LCP<2.5s, INP<200ms, CLS<0.1.
- Mọi tương tác có keyboard và ARIA.
- Không secret trên client.
- Thao tác gửi form: disable nút + loading để chặn double-submit; lỗi thì giữ nguyên dữ liệu đã nhập.
- Test UI truy vấn bằng `getByRole`/`getByLabel` (ép a11y đúng), không bám class hay test-id thị giác.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] axe 0 critical
- [ ] CWV đạt
- [ ] CSP có
- [ ] Test dùng role/label, không selector thị giác

## Ví dụ tốt
Button có aria-label, focus ring, contrast ≥ 4.5:1.

## Ví dụ xấu
div onClick không focusable.
