# ADR-0048: Ghi bài học ticket khi merge vào nhánh tích hợp

Ngày: 2026-10-05 · Trạng thái: chấp nhận · Liên quan: ADR gốc 0004 quyết định 2, ADR-0007, audit A3.5

## Bối cảnh

`_record_lessons` chỉ ghi estimate so với actual sau khi khách ký nghiệm thu và ticket thành `closed`.
Đợt CAMPUS-UNI đã merge năm ticket nhưng chưa nghiệm thu, nên `knowledge` vẫn rỗng và ticket kế tiếp không
có bài học để tham khảo. Mã tích hợp đã phát `integration.merged` trước khi giao ticket phụ thuộc.

## Quyết định

1. Sau khi merge thành công và `mark_integrated`, orchestrator ghi bài học của ticket đó lên bus dưới
   `knowledge`, một lần theo khoá `lesson:<ticket_id>`. Đường nghiệm thu chỉ bù cho ticket cũ đã đóng mà chưa
   có bài học. Bài học phản ánh chi phí tại mốc merge; review hoặc nghiệm thu sau mốc đó không được ngầm cộng
   vào `actual_tokens` của bài học đã chốt.
2. `Supervisor.lessons_for(ticket)` lọc bài học cùng assignee, giao risk tags hoặc đã retry; lấy tối đa năm
   bản mới nhất. Runner đưa danh sách này vào `related_lessons` của payload prompt và bỏ `knowledge` thô khỏi
   context để tránh chỉ thấy bản cuối cùng. Bản ghi trên bus vẫn là nguồn sự thật, replay được.
3. Prompt supervisor nói đúng mốc merge và đường đọc chọn lọc. Khi đổi prompt, version/golden/eval thật,
   assetscan, assetbudget và subagent dẫn xuất đi cùng một PR theo `CONTRIBUTING.md` §3.

## Kiểm chứng

Test tích hợp dùng repo thật: T1 merge trước khi T2 được giao; trước nghiệm thu đã có bài học T1 và T2;
prompt builder T2 chứa `related_lessons` của T1. Test bộ lọc kiểm ba điều kiện và trần năm bản mới nhất.
Test prompt khóa mô tả mốc merge; eval supervisor ghi bằng model thật và replay nghiêm ngặt.

## Giới hạn

Một ticket merge lần nữa sau rework vẫn giữ bài học đầu theo khoá `lesson:<ticket_id>`; ticket ID hiện là đơn
vị học của ADR gốc 0004. Nếu cần đo nhiều lần merge của cùng ticket, phải đổi khoá sang thế hệ và thêm test
cho cập nhật estimate/actual trước khi ghi nhiều bản.
