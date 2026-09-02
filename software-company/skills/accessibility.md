---
name: accessibility
standards: [WCAG 2.2 AA, ISO 9241-210, EN 301 549, ARIA Authoring Practices]
---
# Skill: accessibility

## Tiêu chuẩn tham chiếu
- WCAG 2.2 AA
- ISO 9241-210
- EN 301 549
- ARIA Authoring Practices

## Quy tắc
- Mọi màn hình đủ 4 trạng thái (loading, empty, error, success) đều đạt WCAG 2.2 AA.
- Điều hướng bàn phím và screen reader cho luồng chính; focus order và focus visible rõ.
- Tương phản ≥ 4.5:1 chữ thường, ≥ 3:1 chữ lớn/thành phần UI; không truyền thông tin chỉ bằng màu.
- Kiểm tra tự động (axe/Lighthouse) chỉ là sàn; luồng Must phải test thủ công với screen reader.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] axe không lỗi critical/serious
- [ ] Luồng Must đi hết bằng bàn phím
- [ ] Ảnh/nút có tên tiếp cận được
- [ ] Form có label, lỗi đọc được bởi screen reader

## Ví dụ tốt
Nút icon-only có aria-label="Xóa đơn hàng", thông báo lỗi dùng aria-live="polite".

## Ví dụ xấu
Lỗi chỉ tô đỏ viền input, không có text.
