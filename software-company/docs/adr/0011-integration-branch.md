# ADR-0011: Nhánh tích hợp — ticket rẽ từ đâu và merge vào đâu

Trạng thái: Accepted · Ngày: 2026-09-02

## Bối cảnh
ADR-0010 cho khối kỹ thuật sửa code thật trên branch `ticket/<id>`, nhưng branch đó không đi đâu cả: release-engineer
mô phỏng deploy, ticket phụ thuộc rẽ từ `base` cố định nên không thấy code của ticket trước, và "merged" trong máy
trạng thái của delivery-lead không tương ứng với một merge git nào.

## Quyết định
1. **Một nhánh tích hợp của công ty** (`company/integration`, đổi bằng `--integration`), rẽ từ `--base` lần đầu và
   sống trong worktree riêng `.worktrees/_integration`. Nhánh của khách (`main`) không bao giờ bị orchestrator chạm;
   đưa `company/integration` lên `main` là việc của release-engineer/người ở gate release.
2. **Ticket rẽ từ nhánh tích hợp** tại thời điểm dispatch (worktree tạo khi agent bắt đầu), nên ticket phụ thuộc
   thấy code của ticket đã tích hợp trước đó.
3. **Merge xảy ra khi release-candidate xuất hiện** (mọi review bắt buộc pass — chỗ delivery-lead đặt `approved`):
   orchestrator `merge --no-ff` từng branch ticket của RC vào nhánh tích hợp, audit `integration.merged` kèm sha,
   rồi mới cho release-engineer nhận RC (đầu vào có `integration_branch`, `integration_sha`).
4. **Xung đột thì không có merge nửa vời**: `merge --abort`, RC bị huỷ (`release.void`, nhớ qua replay), ticket về
   `changes_requested` với hint là danh sách file xung đột (tính một retry — hết retry thì blocked → gate escalation
   như thường), worktree của ticket xoá và tạo lại từ nền mới. Chuyển trạng thái `approved → changes_requested`
   được thêm vào máy trạng thái cho riêng trường hợp này.
5. Không có `--repo` thì không có nhánh tích hợp; luồng mô phỏng như cũ.

## Hệ quả
- "merged" của delivery-lead vẫn đặt ở staging deployed (giữ máy trạng thái), nhưng giờ mọi ticket ở trạng thái đó
  đã thật sự nằm trong `company/integration`.
- Ticket độc lập chạy song song trong tương lai (bus nhiều tiến trình) có thể xung đột nhiều hơn; chiến lược "làm lại
  trên nền mới" đơn giản và đúng, đổi lại tốn token — supervisor thấy qua retry và `stats.conflicts`.
- Chưa có: release-engineer đẩy nhánh tích hợp lên `main`/tag phiên bản thật; rebase tự động thay vì làm lại.
