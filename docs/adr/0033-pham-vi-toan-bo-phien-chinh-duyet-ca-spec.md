# ADR gốc 0033: phạm vi `toan-bo` — phiên chính duyệt cả spec

Ngày: 2026-10-12 · Trạng thái: **được chấp nhận** 2026-10-12 (chủ dự án quyết trong chat, xem Bối cảnh) · Sửa: ADR gốc
0025 §Quyết định 5 (thêm một phạm vi, không đổi `rong`) · Liên quan: ADR gốc 0024 (đường chữ ký), 0021 (`BusApprovalLookup`)

## Bối cảnh

- ADR gốc 0025 cho phiên chính quyết mọi gate **trừ spec** (`COMPANY_GATE_REVIEWER_SCOPE=rong`), vì chủ dự án lúc đó
  giữ lại đúng một quyết định: duyệt spec ban đầu.
- 2026-10-12, hub chạy bằng systemd trên máy chủ dự án (ADR gốc 0032), dự án thử `QLKH-DD-CSV` đứng ở gate
  `SPEC-QLKH-DD-CSV`. Chủ dự án nói ba lần: *"phiên chính duyệt mà"*, rồi *"tự duyệt spec, tiếp tục vận hành đi"*, rồi
  chọn **"Bật lâu dài"** khi được hỏi giữa bật lâu dài và chỉ cho một dự án.
- Đo hiện trạng: chặn spec nằm ở **một** chỗ — `gate_reviewer.refusal` (chiều ghi CLI lẫn chiều tin khi replay).
  Ngoài nó, chỉ `spec_approval.BusApprovalLookup` (pha Ready của dự án CÓ profile chất lượng, ADR gốc 0021) đòi actor
  người; luồng spec → plan → dispatch của orchestrator không đọc `decided_by`.
- Như ADR gốc 0025: đây là quyết định giá trị của chủ dự án, không phải câu hỏi kỹ thuật. Việc của repo là làm nó
  thành cấu hình tường minh, có dấu vết trung thực, tắt được.

## Quyết định

1. **Giá trị mới `COMPANY_GATE_REVIEWER_SCOPE=toan-bo`**: mọi thứ của `rong` **cộng** gate `spec` (approve và reject).
   `rong` giữ nguyên nghĩa cũ (trừ spec); không đặt = S2 như ADR gốc 0024. Đọc lại mỗi lần kiểm như cờ: bỏ `toan-bo`
   rồi mở lại tiến trình thì quyết định spec của reviewer không được tin khi replay — gate hiện lại chờ người.
2. **Vẫn đường chữ ký ADR gốc 0024**: actor `reviewer:phien-chinh`, Ed25519, không bao giờ `human:*`. Lịch sử gate nói
   đúng là máy duyệt spec.
3. **`BusApprovalLookup` không đổi**: pha Ready của dự án có profile chất lượng vẫn chỉ tin spec do người duyệt và
   profile do chính người đó ghim. Dự án có profile mà spec do reviewer duyệt thì Ready báo thiếu — hỏng thì đóng.
   Nới chỗ đó là một quyết định riêng (profile là hợp đồng chất lượng với khách).

## Phương án đã loại

- **Phiên chính ký `human:<chủ dự án>` theo lệnh** — không đổi code. Loại, cùng lý do ADR gốc 0025: lịch sử gate nói
  dối về người đã đọc spec; về sau không phân biệt được spec nào người thật đã đọc.
- **Đổi nghĩa `rong` thành "kể cả spec"** — ít chữ hơn. Loại: hub khác đang đặt `rong` với nghĩa "trừ spec" sẽ đổi hành
  vi âm thầm khi `git pull`. Thêm giá trị mới thì ai muốn mới bật.
- **Bật `toan-bo` rồi tắt ngay sau một dự án** — chủ dự án đã chọn bật lâu dài.

## Hệ quả

- **Đổi code**: `gate_reviewer.py` (`SCOPE_TOAN_BO`, `scope_rong()` đúng cho cả hai giá trị, `refusal` cho spec khi
  `toan-bo`). Tài liệu: skill `/gate-review`, `CLAUDE.md`, `SECURITY.md`, `docs/TRUC-VA-DUNG-KHAN.md`.
- **Mất**: điểm dừng bắt buộc cuối cùng của người trước khi code được viết. Người vẫn đọc được mọi spec ở console/
  `gate_brief`, vẫn `reject`/đổi qua change request, nhưng không còn gì chờ họ.
- **Trần đã biết** (ADR gốc 0024/0025 F1): khoá reviewer cùng user OS với mã khách chạy trong sandbox subprocess.
  `toan-bo` nâng giá của lộ khoá thêm một bậc (mã khách tự duyệt được cả spec). Hub này chạy sandbox container
  (`sandbox_mode: container:python:3.12-slim`), nên F1 đóng ở đây; hub chạy subprocess thì không nên bật `toan-bo`.
- **Dấu hiệu quyết định này sai**: khách từ chối nghiệm thu vì sai yêu cầu (`acceptance.overridden` do spec), hoặc
  change request sửa đúng thứ spec đã duyệt ngay sau release đầu. Gặp thì bỏ `toan-bo`, về `rong`.

## Sửa đổi 2026-10-14 — reject của reviewer ở gate spec là yêu cầu sửa

Reviewer chỉ được approve/reject (`gate_reviewer.refusal`), nhưng `_plan` chỉ coi `request_changes` là viết lại; `reject`
làm mọi spec sau của cùng chuỗi bị bỏ qua. Hub 2026-10-14: `reviewer:tu-dong` reject SPEC-CR-DDCSV-INFRA-002 kèm hint cụ
thể, CR kẹt vĩnh viễn. Từ nay `reject` do `reviewer:*` ký ở gate spec chạy đúng đường `request_changes` (ADR-0031 §3,
`gates_flow.spec_changes_asked`): product viết lại với lý do làm hint, trình lại gate thế hệ mới. `reject` của người giữ
nghĩa cũ: dừng.
