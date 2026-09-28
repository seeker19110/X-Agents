# ADR-0045: tiếp thu có chọn lọc Standard Delivery Contract

Ngày: 2026-09-25. Trạng thái: **Accepted** 2026-09-28, code trong PR #335.
Chủ dự án giao phiên chính chốt các ADR mà mã đã merge, theo tiêu chí đơn giản + chất lượng.

## Bối cảnh

Chủ dự án yêu cầu đọc `seeker19110/project-template` và tích hợp điểm hữu ích vào Claude-Agents.
GitHub trả redirect; cùng repository ID 1283493926 có tên hiện tại `seeker19110/projects-template`.
Nguồn được ghim ở commit `23accce8a4b830eb07690cbd39dded8bf3bc94ce`, không theo `main` lúc runtime.
Bản đối chiếu ở `docs/reports/2026-09-25-projects-template-adoption.md` (từ gốc repo).

Claude-Agents đã có kiểm chứng bằng chữ ký, exact-head/context, sàn quality_floor, journal nguyên tử
và chống mất ACK. Thiếu contract máy đọc để phân biệt Ready/Done/Complete và no-op với phép kiểm thật.
TRAPS gốc ghi sự cố “Bốn gate xanh, sản phẩm không chạy”; không nhập nguyên wrapper exit0 khi thiếu lệnh.

## Quyết định

1. Thêm `company.delivery_contract`, chỉ model/policy thuần, không scheduler/journal/agent mới.
2. Profile có `delivery` tùy chọn: spec Approved **chính xác**, record/principal/date, nghiên cứu,
   phương án không thay đổi, baseline brownfield, AC→test và gate theo phạm vi đã chọn. Phiên chính
   điền từ quyết định có thật; metadata hợp lệ KHÔNG chứng thực danh tính hoặc cấp quyền approval.
3. `compile_contract` kiểm Ready cấu trúc; `compile_execution` hiện có dùng hợp đồng này trước register.
   Không tự tạo bằng chứng approved hoặc đổi HumanGate. Không tự parse Markdown bằng tìm chuỗi Approved.
4. Một receipt bổ sung `delivery.definition` trong assessor hiện có kiểm Done/Complete, đích bàn giao,
   gate thực thi và hạng mục còn thiếu. PASS cần checks_executed>0, đúng argv đã ghim và exit0 nếu là command.
   NOT_CONFIGURED/FAIL luôn chặn; NOT_APPLICABLE chỉ khi scope đã khai trước và có lý do. N/A không là PASS.
5. Không thay 33 check cũ. Hợp đồng bổ sung chỉ siết; coordinator hiện có ký/lưu report với context và revision.
   Completion không suy từ backlog trống; công việc ngoài scope không chặn, việc bắt buộc/P0-P1 còn thì chặn.
6. Giữ serialization/hash/signature v2 khi delivery không được chọn. Nguồn và policy adapter được hash
   vào contract khi chọn, nên không âm thầm đổi tiêu chuẩn của run cũ; đổi scope phải tạo revision mới.
7. Tư tưởng thiết kế và sửa lỗi của template được nối vào `/product-goal`, không vendor provider/dataset,
   không copy hook, CLAUDE.md, PROGRESS.md, workflow CI hoặc ép model theo nguồn.

## Hệ quả

Đây là preflight cấu trúc + kiểm semantic report đã xác thực, chưa là identity service/driver thực thi
mọi gate hoặc bằng chứng sản phẩm đạt chuẩn ngành. Một driver được tin cậy vẫn có thể kiểm sai;
checks_executed phải do driver thật thu, không cho worker tự khai rồi ký. Không chạy argv trong module.
Sàn ADR-0043, scope công cụ và authority hiện hữu tiếp tục áp. Journal vẫn là nguồn trạng thái kernel;
trước H7, file A–F của `/thi-hanh` giữ vai trò đã nêu ở ADR gốc 0017.

## Liên quan

- `company.product_quality`, `company.quality_execution`, ADR gốc 0018–0019.
- Nguồn ghim và blob manifest: `docs/integrations/projects-template.lock.json` từ gốc repo.
- TDD: draft/no-op/N/A tự khai/partial completion và compatibility + journal restart trong tests.
