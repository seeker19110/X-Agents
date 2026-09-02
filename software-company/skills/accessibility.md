---
name: accessibility
version: 2
standards: [WCAG 2.2 AA, ISO 9241-210, EN 301 549, ARIA Authoring Practices, Section 508]
---
# Skill: accessibility

## Tiêu chuẩn tham chiếu
- WCAG 2.2 AA (bốn nguyên tắc POUR: cảm nhận được, thao tác được, hiểu được, bền vững)
- ISO 9241-210 (thiết kế lấy người dùng làm trung tâm)
- EN 301 549 (bắt buộc với hợp đồng khu vực công EU) và Section 508 (Mỹ)
- ARIA Authoring Practices Guide — mẫu tương tác chuẩn cho từng component
- WAI-ARIA 1.2: luật thứ nhất là đừng dùng ARIA nếu HTML ngữ nghĩa đã đủ

## Quy trình (làm đúng thứ tự)
HTML ngữ nghĩa trước → bàn phím → tên/vai trò/giá trị (accessible name) → tương phản và kích thước → thông báo động (live region) → kiểm tự động (axe) → kiểm thủ công bằng screen reader trên luồng Must.
Không bắt đầu bằng ARIA: mỗi lần định thêm `role=`, hãy hỏi thẻ HTML nào đã có sẵn ngữ nghĩa đó.

## Quy tắc — cấu trúc và ngữ nghĩa
- Dùng phần tử đúng ngữ nghĩa: `button` cho hành động, `a[href]` cho điều hướng, `label` + `input`, `table` có `th[scope]`; `div` gắn `onClick` là lỗi block.
- Mỗi trang có đúng một `h1`, thứ bậc heading không nhảy cấp, có landmark (`header/nav/main/footer`) và liên kết bỏ qua điều hướng.
- Khai báo ngôn ngữ (`lang="vi"`); tiêu đề trang duy nhất và mô tả đúng nội dung; đổi route thì đổi title và chuyển focus về đầu vùng nội dung.
- Mọi phần tử tương tác có accessible name (chữ nhìn thấy, `aria-label`, hoặc `aria-labelledby`); nút chỉ có icon bắt buộc phải có nhãn.

## Quy tắc — bàn phím và focus
- Toàn bộ luồng Must đi hết được bằng bàn phím, không bẫy focus; thứ tự tab khớp thứ tự đọc; không dùng `tabindex` dương.
- Focus visible rõ ở mọi theme, tương phản viền focus ≥ 3:1; không `outline: none` nếu chưa có thay thế.
- Modal/sheet: focus vào bên trong khi mở, giữ focus trong đó, Esc đóng, và trả focus về phần tử đã mở nó.
- Phím tắt một ký tự phải tắt được hoặc đổi được (WCAG 2.2) và không chiếm phím của screen reader.
- Nội dung hiện khi hover phải hiện được bằng focus, giữ được và tắt được (WCAG 1.4.13).

## Quy tắc — cảm nhận và trạng thái
- Tương phản ≥ 4.5:1 cho chữ thường, ≥ 3:1 cho chữ lớn và cho thành phần UI mang thông tin; kiểm ở cả light và dark.
- Không truyền thông tin chỉ bằng màu, chỉ bằng hình dạng, hay chỉ bằng vị trí; luôn kèm chữ hoặc icon.
- Target ≥ 24×24 CSS px (WCAG 2.2 AA); trên mobile theo `ui-ux-design` là 44/48; nhỏ hơn thì phải có khoảng đệm không chồng lấn.
- Zoom 200% và reflow ở 320px không mất nội dung, không cuộn ngang hai chiều; giãn chữ không làm cắt chữ.
- Mọi màn hình đủ 5 trạng thái (loading, empty, error, success, validation) đều phải đạt AA — trạng thái lỗi là chỗ hay bị bỏ quên nhất.
- Thay đổi động thông báo qua live region: `aria-live="polite"` cho thông tin, `role="alert"` chỉ cho lỗi chặn; không phát live region theo từng ký tự.
- Form: label hiển thị, lỗi liên kết bằng `aria-describedby`, `aria-invalid` khi sai; error summary ở đầu form có liên kết tới từng field.
- Không tự động phát media; không nội dung nháy quá 3 lần mỗi giây; video có phụ đề, audio có bản ghi chữ.

## Quy tắc — kiểm chứng
- Kiểm tự động (axe/Lighthouse/pa11y trong CI) là sàn, chỉ bắt được khoảng một phần ba vấn đề; 0 lỗi critical/serious là điều kiện cần.
- Luồng Must phải được kiểm thủ công với ít nhất một screen reader theo nền tảng: NVDA hoặc JAWS (Windows), VoiceOver (macOS/iOS), TalkBack (Android).
- Ghi kết quả vào review-results với vị trí cụ thể và tiêu chí WCAG bị vi phạm (ví dụ 1.4.3), không ghi nhận xét chung chung.

## Checklist (supervisor và human gate dùng để chấm)
- [ ] axe/Lighthouse 0 lỗi critical/serious trong CI
- [ ] Luồng Must đi hết bằng bàn phím; focus visible; không bẫy focus
- [ ] Mọi phần tử tương tác và ảnh có tên tiếp cận được đúng nghĩa
- [ ] Form có label hiển thị, lỗi liên kết ARIA và đọc được bởi screen reader
- [ ] Tương phản đạt ở cả light và dark; không thông tin chỉ bằng màu
- [ ] Zoom 200% và reflow 320px không mất nội dung
- [ ] Đã kiểm thủ công ít nhất một screen reader trên luồng Must, có ghi kết quả
- [ ] Mỗi finding dẫn chiếu đúng tiêu chí WCAG

## Ví dụ tốt
Nút chỉ có icon: `<button aria-label="Xóa đơn hàng">` với focus ring tương phản 3:1; lỗi form `<p id="err-card" role="alert">Thẻ bị từ chối. Thử thẻ khác.</p>` và input có `aria-describedby="err-card" aria-invalid="true"`; NVDA đọc đủ nhãn, lỗi và trạng thái.

## Ví dụ xấu
`<div class="btn" onclick=...>` không focus được; lỗi chỉ tô đỏ viền input, không có chữ; modal mở nhưng focus vẫn ở nền và Esc không đóng; tương phản 3.1:1 vì "nhìn cho dịu mắt".
