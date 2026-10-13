# ADR-0032: Supervisor đếm "nợ kiến trúc treo" — cùng mã nợ nhắc ≥ N review liên tiếp thì escalation cấp dự án

## Bối cảnh
QLKH (2026-09-06, `docs/reports/2026-09-06-ban-giao-khong-chay-duoc.md`, đề xuất 5): threat-model, schema review và
code review nhắc đi nhắc lại cùng một việc chưa quyết — DB thật, framework, cloud — dưới dạng finding `warn` với cùng
mã (`DEF-xx`, `SD-xx`). Không finding nào chặn merge, nên ticket vẫn approved, 25 release ra mà không có server. Quyết
định kiến trúc bị **né qua từng ticket**, và không ai đọc finding thứ n vì finding thứ 1 đã "được ghi nhận".

Supervisor đã đếm ngân sách theo đúng cách cần ở đây: cộng dồn từ bus, ngưỡng cấu hình, chạm ngưỡng thì mở gate cho
người. Nợ kiến trúc chỉ là một đại lượng nữa để cộng dồn — nhưng nó phải là **code đếm**, không phải model: model
supervisor không có tool đọc bus (bẫy "agent không có tool đọc bus", `TRAPS.md` §4) và "≥ N lần liên tiếp" là phép
đếm, không phải phán đoán.

## Quyết định
1. **Mã nợ** = `DEF-\d+`, `SD-\d+` (không phân biệt hoa thường) hoặc `debt: <mã>` trong `findings[].text` /
   `root_cause` của `review-results` (`supervisor.DEBT_RE`, `debt_ids()`). Không bắt buộc reviewer đổi prompt: mã đã có
   sẵn trong finding của security/reviewer; `debt:` là cách viết tự do cho nợ chưa có mã.
2. **Đếm theo (dự án, nguồn review, mã nợ)** — `Supervisor._count_debt`: review của một nguồn nhắc mã → chuỗi +1; cùng
   nguồn không nhắc nữa → chuỗi về 0 (nợ đã trả hoặc đã có ADR); nguồn khác không ảnh hưởng. Ngưỡng
   `debt_threshold` (mặc định 3) cấu hình cùng chỗ với trần ngân sách: `llm.yaml debt_reviews` /
   `COMPANY_DEBT_REVIEWS`. Chạm bội số của ngưỡng → một mục `debt_due` mang `times` (lần thứ mấy), số lần liên tiếp,
   tổng lần nhắc, danh sách ticket, nguồn, và hint cố định *"cần ticket ADR + người ký"*.
3. **Sống qua restart bằng replay, không bằng state mới.** Mọi bộ đếm là hàm thuần của bus: `Supervisor.replay`
   đi qua cùng `_count_debt`, nên mở lại bus cho ra đúng `debt_due` (khuôn 2, `TRAPS.md`; bất biến
   `test_moi_trang_thai_nghiep_vu_song_sot_qua_restart` phủ cả thuộc tính mới). Review thiếu `project_id` lấy dự án
   từ `tasks` đã thấy (`ticket_project`); không suy được thì bỏ qua, không đoán.
4. **Orchestrator mở gate, xác định** — `_check_debt` chạy trong `_check_escalations` mỗi lô: gate `escalation`
   **subject = project_id**, `created_by=supervisor`, checklist = danh sách nợ (`debt:DEF-01×3 liên tiếp (security;
   T1,T2)` + các mã khác của dự án), `decision:adr|waive`, `hint:…`; audit `debt.escalated` mang cả bảng. Khoá once
   `debt:{project}:{debt}:{times}` — restart không mở trùng (`once` dựng lại từ audit), nợ tăng tới bội số kế tiếp là
   lần mới → gate mới (khuôn 3). Dự án đang có gate escalation khác (stall, mã nợ khác) thì đợi nhịp sau, không
   `remember` để không nuốt. **Sửa 2026-10-14:** mốc dồn trong lúc đợi chỉ mở mốc MỚI NHẤT của mỗi (dự án, mã nợ) —
   hub QLKH-DD-CSV: SD-14 dồn ×3..×12 sau một gate chờ 16 giờ, mỗi lần ký thì mốc cũ kế tiếp mở ngay (cùng nợ, cùng
   hồ sơ, mỗi gate một lượt agent duyệt và một chữ ký).
5. **Không pause dự án.** Khác `_stall`: nợ treo là quyết định bị né, không phải sự cố — việc khác vẫn chạy trong
   lúc người quyết. Người `approve` (đã có ticket ADR + người ký) hay `reject` (chấp nhận treo) đều chỉ sinh audit
   `debt.decided`; không `resume`, không "reopen" ticket ma (`_on_escalation_decided` rẽ nhánh nợ trước mọi nhánh khác).
6. **Người và model phải thấy bảng.** `status.architecture_debt`, `sprint_report.architecture_debt`
   (`Supervisor.debt_table`). Prompt supervisor v12 nói rõ: nó **nhận bảng đã đếm sẵn**, không tự đếm, và mọi
   `sprint_report` phải liệt kê nguyên bảng; eval mới `no-kien-truc-treo-da-dem-san-phai-escalate-dung-du-an`.

## Hệ quả
- Một quyết định bị né sẽ hiện ra như một gate có tên, có danh sách ticket, có hint — sau đúng N review, không đợi
  người tình cờ đọc. Cái giá: một gate thêm mỗi khi nợ chạm ngưỡng; người phải trả lời "ADR hay chấp nhận treo".
- "Liên tiếp" đo theo nguồn, nên hai nguồn mỗi nguồn nhắc 2 lần không kích (4 lần nhắc nhưng chưa nguồn nào ba lần
  liền). Đó là chủ ý: một nguồn nhắc ba lần liền là nó đang bị bỏ ngoài tai; hai nguồn mỗi nguồn hai lần còn có thể
  là hai góc nhìn. Tổng lần nhắc vẫn có trong bảng để người tự xét.
- Chưa làm: B6 (DoD "khởi động bằng một lệnh") và `open_decisions` trong plan (đề xuất 2) — nợ được *đếm* ở đây, chưa
  được *ngăn* từ lúc lập kế hoạch.
