# ADR-0029: cắt ngữ cảnh PRD theo mục có ưu tiên

Ngày: 2026-10-05 · Trạng thái: đề xuất triển khai · Liên quan: ADR-0012, audit A3.4 (2026-09-27)

## Bối cảnh

`xagents_core.context.fit` chia phần blackboard theo namespace rồi gọi `cut_middle` trên chuỗi của từng
namespace. Với PRD dài, dấu cắt có thể nằm giữa tiêu chí nghiệm thu; audit 22/09 đã thấy mất phần này và
`context_trimmed` xuất hiện 692 lần trong số liệu 27/09. PRD ở company là Markdown có các mục `##`; core không
biết mục nào là tiêu chí nghiệp vụ.

## Quyết định

1. `fit` nhận một callback cắt ngữ cảnh tùy chọn, mặc định vẫn dùng `cut_middle` byte-for-byte như hiện tại.
   Callback chỉ nhận namespace, nội dung, hạn mức và nhãn đường dẫn; core giữ phép phân bổ ngân sách.
2. Company cung cấp callback cho namespace `prd`: tách ở heading cấp hai; ưu tiên giữ nguyên các mục tiêu chí
   nghiệm thu/acceptance, user story và yêu cầu phi chức năng khi vừa hạn mức. Các mục được chọn giữ thứ tự gốc;
   mục bỏ được ghi tên và đường dẫn bản đầy đủ. Mục ưu tiên quá dài được cắt có nhãn trong chính mục đó.
   Nội dung không có heading cấp hai dùng lại `cut_middle`.
3. Các namespace khác và lời gọi `fit` không truyền callback giữ hành vi cũ để bản ghi eval không trôi. Mỗi
   chuỗi cắt vẫn phải nằm trong hạn mức được cấp và được tính trong `trimmed_context`.

## Hệ quả và kiểm chứng

Test đỏ trước mã: `fit` chưa nhận callback; company chưa có bộ cắt PRD. Test so PRD thực dạng Markdown có phần
bối cảnh rất dài và tiêu chí nghiệm thu ở giữa: phần nghiệm thu còn nguyên, mục bị bỏ có nhãn, chuỗi không vượt
hạn mức. Test hồi quy mặc định của core giữ nguyên output cũ. Gate core/company và toàn workspace xác nhận
coverage 100%; eval replay chỉ cần nếu prompt agent bị sửa (PR này không chạm `agents/`/`skills/`).
