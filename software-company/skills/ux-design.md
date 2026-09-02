---
name: ux-design
version: 1
standards: [ISO 9241-210, WCAG 2.2 AA, Nielsen 10 heuristics, Material 3 / HIG, Design tokens W3C]
---
# Skill: ux-design

## Tiêu chuẩn tham chiếu
- ISO 9241-210 (thiết kế lấy người dùng làm trung tâm)
- WCAG 2.2 AA
- Nielsen 10 heuristics
- Material 3 / Apple HIG (nền tảng)
- W3C Design Tokens Community Group format

## Quy tắc
- Mỗi flow bám một user story; mỗi màn hình có 4 trạng thái: empty, loading, error, success.
- Wireframe mức thấp (text/mermaid) đủ để frontend code, không cần Figma.
- Design tokens (màu, chữ, spacing, radius) là nguồn duy nhất; frontend/mobile không hard-code.
- Accessibility đo được: contrast ≥ 4.5:1, focus visible, target ≥ 24×24, label cho mọi input, không phụ thuộc màu.
- Copy chính viết sẵn trong flow; lỗi nói người dùng làm gì tiếp.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] 100% story Must có flow
- [ ] Mọi màn hình đủ 4 trạng thái
- [ ] Tokens có version trong `design`
- [ ] Tiêu chí a11y đo được
- [ ] Giả định người dùng đã liệt kê

## Ví dụ tốt
Flow "Thanh toán" US-07: 5 bước, trạng thái lỗi "Thẻ bị từ chối → Thử thẻ khác / Liên hệ ngân hàng", contrast nút 7.2:1.

## Ví dụ xấu
"Làm giống Shopee" — không flow, không trạng thái lỗi, không tiêu chí.
