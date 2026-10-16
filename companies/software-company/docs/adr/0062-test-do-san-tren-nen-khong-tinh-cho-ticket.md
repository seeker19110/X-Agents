# ADR-0062: test đỏ sẵn trên nền không tính là ticket trượt

## Bối cảnh — số đo
Trong `orch/worktree_flow.engineer`, `local_checks.tests=false` thì PR không đi qua review mà quay thẳng về ticket
(`DeliveryLead.rework`, retry+1). Lệnh test chạy cả suite của repo khách. Vì vậy test đã đỏ sẵn trên nhánh tích
hợp cũng bị tính cho ticket đang làm, dù ticket không chạm tới.

Hub thật (QLKH-DD-CSV, 2026-10-16). DDCSV-110 merge làm 10 test trong `tests/dpia/` đỏ trên `company/integration`.
Từ đó:
- DDCSV-111 hết 3 lượt (`agent_error=3`). DDCSV-132 hết 3 lượt (`agent_error=2`, `turn_limit=1`). Cả hai bị REPLAN
  thay, kéo 4 ticket phụ thuộc vào `blocked` và 4 gate escalation.
- DDCSV-138 (compose secret, không chạm `tests/dpia`) bị trả về lúc 12:05Z với đúng 10 test đó, và đang đốt tiếp
  lượt thử.
- Product phải tự đoán ra nguyên nhân rồi đặt `depends_on: DDCSV-139` (ticket sửa nền) cho ticket thay thế. Máy
  không biết điều này.

Mỗi lượt trượt là một lượt builder đầy đủ (khoảng 10 phút, hàng trăm nghìn token) mà không đổi được kết quả. Ticket
không thể làm test của người khác xanh mà không đụng phạm vi của ticket khác.

## Quyết định
1. **Máy chứng minh "đỏ sẵn", không đoán.**
   - `stacks.failed_tests(output)` đọc dòng tóm tắt của pytest (`FAILED <id>`, `ERROR <id>`).
   - Số id đọc được phải khớp số `N failed`/`N error` trong dòng tổng. Không khớp (output bị cắt) hoặc không phải
     pytest thì trả `None`, nghĩa là không chứng minh được.
   - `TicketWorkspace.inherited_failures(ids)` dựng một worktree tạm ở **điểm rẽ nhánh** (`merge-base`) và chạy đúng
     lệnh test của stack với các id đó, qua cùng sandbox. Kết quả là tập id cũng đỏ ở nền. Lỗi git, sandbox hay
     output đọc không được đều trả `None`.
2. **Mọi test đỏ đều đỏ sẵn ở nền ⇒ ticket nằm chờ, không làm lại.**
   - Điều kiện: lint xanh và tập đỏ của ticket ⊆ tập đỏ ở nền.
   - Ticket đi `changes_requested → waiting`. Đây là chuyển trạng thái mới trong `TRANSITIONS`.
   - Ticket không đốt `retry`. Hint ghi lại các test đỏ sẵn.
   - Audit `ticket.base_red` gồm `{ticket_id, failed, inherited, base, verified_by: workspace}`.
   - `rehydrate` dựng lại trạng thái chờ từ dòng audit này.
3. **Nhả khi nền đổi.** `mark_integrated` (một ticket merge vào nhánh tích hợp) xoá tập chờ và giao lại các ticket đó
   từ WIP đã giữ. Lượt sau chạy trên nền mới.
4. **Có trần, không treo.**
   - Kiểu dừng `base_red` trong `STOP_POLICY`: `burns_retry=False`, `free_stops=3`, `then=defer`. Quá 3 lần thì xử
     lý như trước (`rework`).
   - Chỉ cho chờ khi cùng dự án còn ít nhất một ticket khác đang chạy (`dispatched`, `in_progress`, `in_review`,
     `changes_requested`, hoặc `approved` chưa tích hợp). Còn như vậy thì nền còn có thể đổi.
   - Không còn ticket nào chạy thì xử lý như trước, để vòng retry/escalation hiện có đưa việc tới người.
   - Ticket cuối cùng đang chạy của dự án bị `blocked` thì cũng nhả tập chờ của dự án đó.
5. **Không đổi bằng chứng của PR.** PR chỉ được publish khi `tests=true`. Sàn chất lượng của release
   (`quality_floor`, mọi PR phải `tests=true`) giữ nguyên.

## Cái giá đã biết
- Thêm một lần chạy test (chỉ các id đỏ) trên worktree tạm mỗi khi PR đỏ. Với `uv run`, worktree tạm phải đồng bộ
  `.venv` của nó.
- Chỉ pytest. Stack khác giữ hành vi cũ cho tới khi có khách cần.
- Test chập chờn (đỏ ở cả hai lần chạy nhưng vì lý do khác) cũng được coi là đỏ sẵn. Nó vẫn bị chặn ở trần 3 lần chờ
  và ở review của ticket sửa nền.

## Phương án đã loại
- **Cho PR đi tiếp với `tests=false` kèm cờ "đỏ sẵn".** Sàn chất lượng release đòi mọi PR `tests=true`. PR đó sẽ chặn
  RC về sau dù nền đã xanh. Reviewer/QA cũng tốn lượt để đọc một PR máy đã biết là đỏ.
- **Bỏ qua test đỏ sẵn rồi coi `tests=true`.** Đây là bằng chứng giả: PR nói "xanh" trên một suite đỏ.
- **Đặt `depends_on` tự động vào ticket sửa nền.** Máy không biết ticket nào sửa test nào. Product đã đoán đúng một
  lần (DDCSV-140/141 → DDCSV-139), nhưng đó là phán đoán, không phải bằng chứng.
- **Miễn retry nhưng giao lại ngay.** Lượt sau gặp đúng nền đó và đốt thêm một lượt builder vô ích.
