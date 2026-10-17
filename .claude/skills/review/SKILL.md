---
name: review
description: Review diff/PR theo checklist của khung (đúng nghiệp vụ, ca biên, bảo mật, lỗi logic, thống nhất, test) — phát hiện là CLAIM phải có đường tái hiện; reviewer khác model với người viết. Dùng trước khi merge, khi người dùng hỏi "có bug không", "rà nhanh diff", hoặc gõ /review.
argument-hint: "[PR number | branch | path]"
---

# /review — review như người gác cổng, không như người viết

`<FW>` = `.xtemplates/framework` trong dự án đích, hoặc `framework` trong repo khung. `<XT>` = `python3 .xtemplates/scripts/xt.py` (hoặc `python3 scripts/xt.py`).

Giao cho subagent `reviewer` (model khác với executor) khi diff > 200 dòng; phiên chính tổng hợp.

## Thứ tự rà
1. **Đúng việc:** diff làm đúng SPEC/task? có sửa nhầm chỗ khác? phạm vi phình?
2. **Lỗi logic & ca biên:** rỗng/null vs 0, off-by-one, race/idempotency, thời gian (UTC, DST, cuối tháng), tiền (số nguyên, làm tròn), Unicode/tiếng Việt, giới hạn kích thước, lỗi mạng/timeout có nhánh xử lý.
3. **Bảo mật:** input validate ở biên, quyền kiểm ở server cho mọi hành động, không secret/PII vào log, SSRF/injection/XSS, phụ thuộc mới (license, trạng thái).
4. **Thống nhất:** cùng cách xử lý lỗi/phân trang/đặt tên như phần còn lại; không trùng lặp logic đã có (tìm trước khi viết mới).
5. **Test:** có test cho nhánh mới + ca biên; test có assert thật, không test "cho có"; không skip/disable.
6. **Vận hành:** migration có đường lùi; cấu hình mới có default an toàn; log/metric đủ để debug sự cố.
7. **Tài liệu:** CHANGELOG/ADR/README cập nhật khi đổi hành vi/API.

## Cách báo
Mỗi phát hiện: `file:dòng` · mức (🔴 chặn merge / 🟠 nên sửa / 🟢 gợi ý) · **đường tái hiện cụ thể** (input → kết quả sai) · đề xuất sửa ngắn. Không có đường tái hiện → ghi là "nghi ngờ", không phải phát hiện. Phát hiện của công cụ AI khác cũng là claim cần verify. Kết luận: APPROVE / REQUEST CHANGES + lý do.
