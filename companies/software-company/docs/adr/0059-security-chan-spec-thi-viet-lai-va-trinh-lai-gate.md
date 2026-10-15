# ADR-0059: security chặn spec ở threat model → product viết lại, bản viết lại trình lại gate spec

## Bối cảnh
Spec đã qua gate `SPEC-<key>` còn một cửa: `security` chạy threat model (`ticket_fsm._threat_model`). Verdict `block`
trước ADR này đi `_mark_unhandled` → gate `escalation` `decision:reopen|close` trên key của chuỗi. Duyệt = chạy lại
đúng event spec cũ, nên security chấm lại ĐÚNG bản đã bị chặn và block y hệt; đóng = bỏ chuỗi. Không đường nào đưa
finding tới người viết spec.

Hub thật 2026-10-15 (QLKH-DD-CSV): SPEC-CR-DDCSV-SEC-006 và SPEC-CR-DDCSV-DPIA-001 qua gate rồi bị block
(threat-model v138: TM-SEC6-01/05; v139: TM-DPIA-02). `reviewer:tu-dong` giữ cả hai escalation vì "lịch sử thất bại
trống". Phiên chính phải đóng hai chuỗi và nộp CR-DDCSV-SEC-007/DPIA-002 chép tay finding — thêm một vòng intake,
research, câu hỏi làm rõ cho một việc vốn chỉ là "sửa spec theo finding".

## Quyết định
1. **Block → viết lại.** `_threat_model` gặp `verdict=block` mà chuỗi còn lượt (`SPEC_SECURITY_REWORKS = 2`) và có event
   nguồn (`_spec_source`) → `_spec_rework` (cùng đường với `request_changes` của người, ADR-0031 §3) với `hint` là
   toàn văn mọi finding `block`/`warn` (trần `HINT_MAX`). Audit `spec.security_rework` mang `chain`, `attempt`,
   `review_event`. Không escalation.
2. **Bản viết lại trình lại gate.** Chuỗi được đánh dấu `spec_regate`; spec kế tiếp của chuỗi mở một thế hệ gate
   `SPEC-<key>` mới (audit `spec.regate`) thay vì đi thẳng tới threat model. Người ký đã duyệt bản cũ, không phải
   bản viết lại.
3. **Gate spec tính theo quyết định MỚI NHẤT.** `_plan` coi chuỗi là đã duyệt khi thế hệ gate gần nhất là `approve`
   và không có thế hệ nào đang chờ (`spec_approved_now`), không phải "từng có một lần approve"
   (`GateQueue.is_approved`). Reject ở thế hệ trình lại thì dừng, như mọi reject khác.
4. **Quá trần** → giữ nguyên đường cũ: `spec_blocked_by_security` + `_mark_unhandled` → escalation. Không có event
   nguồn (spec publish tay) cũng đi đường cũ.
5. **Supervisor không escalate key `SPEC-*`** khi đếm "cùng lỗi lặp ≥ 2 lần" ở `review-results`: key threat model trùng
   subject gate spec, escalation ở đó ĐÈ thế hệ gate đang chờ (sổ `pending` theo subject). Chuỗi spec đã có trần ở mục 1.
6. **Dựng lại từ audit** (khuôn 2 `TRAPS.md`): `spec.security_rework` cộng bộ đếm và đánh dấu chuỗi, `spec.regate`
   gỡ dấu; `event.retried`/`event.abandoned` của chuỗi xoá bộ đếm như `spec_runtime_reworks`.

## Hệ quả
- Finding của security tới product nguyên văn, trong cùng chuỗi CR; không cần CR thay thế.
- Mỗi lượt viết lại tốn một lượt `product[spec]` + một lần duyệt gate + một lượt threat model.
- `GateQueue.is_approved` (core) giữ nghĩa cũ cho các chỗ khác (`_runtime_da_duyet`, hồ sơ gate); chỉ `_plan` đổi.

## Liên quan
ADR-0031 §3 (`_spec_rework`, khuôn đếm theo chuỗi), ADR-0037 (threat model trước kế hoạch), ADR gốc 0033/0034 (reviewer
ký gate spec, reject kèm hint).
