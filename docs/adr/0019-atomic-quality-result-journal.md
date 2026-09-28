# ADR-0019: lưu quyết định chất lượng và trạng thái trong một giao dịch

Ngày: 2026-09-25. Trạng thái: **Accepted** 2026-09-28, code trong PR #335; mở rộng ADR-0018 theo yêu cầu chủ dự án.
Chủ dự án giao phiên chính chốt các ADR mà mã đã merge, theo tiêu chí đơn giản + chất lượng.

## Hiện trạng và mục tiêu

Kernel có journal nhưng `append` chỉ chèn event, không kiểm transition dưới cùng khóa ghi SQLite.
Adapter đánh giá trả TaskResult trong RAM; caller phải tự ghép trạng thái và kết quả. Khi mất phản hồi,
gửi lặp hoặc hai coordinator cùng tiếp tục, có thể ghi lịch sử không replay được hoặc mất lý do nghiệm thu.
Đây là phần gia cố cùng hạng mục product excellence, không dựng scheduler hay worker pool mới.

## Quyết định

- Thêm `ExecutionJournal.transition(event, expected_count=...)`: BEGIN IMMEDIATE, đọc RunSpec/events,
  kiểm phiên bản theo số event của chính run, apply_event và ghi trong một giao dịch ngắn.
- Cùng event_id + cùng nội dung ngữ nghĩa là ACK lại, không thực thi lại; timestamp gửi lại không thay
  timestamp gốc. Cùng ID nhưng khác nội dung hoặc run là lỗi. ACK trả trạng thái hiện tại, không duyệt mới.
- `register` cũng khóa ghi trước SELECT để đăng ký lặp trên nhiều kết nối không tranh INSERT.
- Giữ `append` làm API low-level tương thích/import lịch sử; runtime mới phải dùng transition. Quyền OS,
  người ghi DB, lease và driver kiểm chứng vẫn là ranh giới riêng; đây không phải exactly-once cho Git/deploy.
- Thêm `commit_quality_result` ở company: kiểm graph/contract và attempt được start trong journal,
  gọi assessor trước transaction, lưu TaskResult + receipt metadata/signatures (KHÔNG keys) + fingerprint
  của đầu vào với terminal event. CAS chặn state thay đổi trong lúc kiểm. Retry chỉ ACK kết quả đã ghi.
- Thiếu bằng chứng sinh FAILED có lý do, không SUCCEEDED; không đổi sàn quality_floor/authority cũ.
- Retry sau khi bằng chứng hết hạn chỉ đọc lại quyết định cũ, KHÔNG là chứng nhận candidate hiện vẫn đạt.

## Kiểm chứng và phạm vi

TDD trước code: unknown run, sai transition, CAS stale, ID collision, hai kết nối ghi đồng thời,
restart/retry, rollback khi INSERT lỗi; domain result thiếu/stale, attempt lệch, contract lệch và mất ACK.
Đo cả SQLite thật, không chỉ mock. Không tăng trần skip/xfail hoặc giảm coverage.
Bộ kiểm symlink giữ test thực trên hệ hỗ trợ và mô phỏng resolution rõ ràng khi OS không cấp quyền;
không bỏ cả test bằng pytest.skip. CI console trước đó đã chặn đúng trường hợp thêm skip.

Nguồn cơ chế: https://www.sqlite.org/lang_transaction.html ;
https://docs.python.org/3.13/library/sqlite3.html#how-to-use-the-connection-context-manager
Không gọi model hoặc kiểm filesystem trong transaction. H3–H7 và thực thi goal đầu-cuối vẫn cần tích hợp riêng.
