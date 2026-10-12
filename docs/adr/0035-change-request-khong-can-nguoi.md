# ADR gốc 0035: change request không cần người — phạm vi `toan-bo` gồm cả nộp và quyết change request

Ngày: 2026-10-12 · Trạng thái: **được chấp nhận** 2026-10-12 (chủ dự án quyết trong chat, xem Bối cảnh) · Sửa: ADR gốc
0033 (phạm vi `toan-bo` thêm một việc) · Liên quan: ADR gốc 0024 (đường chữ ký), ADR gốc 0034 (agent duyệt tự động),
ADR-0051 của software-company (replan qua change request)

## Bối cảnh

- Sau ADR gốc 0033/0034, **mọi gate** của software-company do `reviewer:*` ký. Nhưng hai cửa vẫn chỉ nhận `human:*`:
  nộp change request (`orchestrator publish change-requests`, console) và quyết nó (`decide-change`). Đo hub thật
  2026-10-12, dự án `QLKH-DD-CSV`: REL-001→011 đều máy giữ vì smoke trần chết ở `QLKH_DB_DSN`; lối ra là một change
  request thêm compose (ADR-0053) — phiên chính soạn xong, không nộp được, phải đưa JSON cho người gõ tay. CR replan
  `REPLAN-DDCSV-02-1` cũng nằm chờ `human:*` dù lệnh `lock` (ADR-0054) đã thay cho thứ nó đòi.
- Chủ dự án: *"bạn duyệt hết"*, rồi *"bỏ human"*.
- Ranh giới hiện có: bus ACL `change-requests` cho `ops`, `delivery-lead`, người; `cli_cmds.publish`/`decide_change`
  đòi `is_human` (audit 2026-09-27 F-A: `--by ops` lọt ACL mà vai khác nổ traceback); orchestrator tin `decision`
  trong payload mà không hỏi ai ghi (`guards._cr_accepted_*`).

## Quyết định

1. **Phạm vi `toan-bo` (ADR gốc 0033) nay gồm cả NỘP và QUYẾT change request.** Không có phạm vi mới; `rong` và S2 giữ
   nguyên (CR vẫn của người ở hai phạm vi đó).
2. **Bus**: `TOPIC_PRODUCERS["change-requests"]` thêm họ `reviewer:*` (`core.REVIEWER_FAMILY`). Core `producer_allowed`
   hiểu mục đuôi `:*` là một họ actor — cùng quy ước `human:*` mà company đã dùng ở `rehydrate.TRUSTED_WRITERS`. Chỉ
   topic này; `reviewer:*` không phát được topic người nào khác.
3. **Một chỗ cho cả hai chiều** (như `refusal()` của ADR gốc 0024): `gate_reviewer.cr_actor_refusal(actor)` — người
   luôn được; `reviewer:*` chỉ khi `COMPANY_GATE_REVIEWER=1` **và** `COMPANY_GATE_REVIEWER_SCOPE=toan-bo`, đọc lại mỗi
   lần. Chiều ghi: `publish change-requests --actor reviewer:<id>` và `decide-change --by reviewer:<id>` dùng nó; topic
   khác vẫn chỉ nhận người. Chiều tin: `cr_trusted(env)` trong `guards._cr_accepted_*` — CR `accepted` do `reviewer:*`
   ghi mà cờ/phạm vi hub không bật thì **không đi route nào**, audit `change.untrusted` một lần nói vì sao.
4. **Replan do reviewer `accepted`**: ticket cũ vẫn đóng, kế hoạch mới vẫn lập (ADR-0051), nhưng `decide-change` **không**
   đóng gate escalation của ticket dưới tên reviewer — `gate.decide` trần của `reviewer:*` không ai tin (ADR gốc 0024).
   Gate để lại cho `gate_reviewer decide <ticket> --decision reject` có chữ ký; CLI in đúng lệnh đó.

## Hệ quả

- Phiên chính (và `/gate-review`) nộp CR thay khách bằng `publish change-requests --actor reviewer:phien-chinh` với
  `requested_by` là chính nó, **không** ghi `human:*` vào `requested_by`. Lý do nộp phải nêu lệnh của chủ dự án trong
  `description`.
- CR của reviewer không có chữ ký Ed25519 như `gate.decide` — tin ở mức cờ hub + ACL bus, ngang với `human:*` hôm nay
  (ai gõ `--by human:x` cũng được). Trần đã biết: muốn chữ ký cho CR thì ký `impact` như `sign_decision`, quay lại khi
  hub có nhiều hơn một máy chạy CLI.
- `DeliveryLead.replan_open` vẫn rút khi thấy CR replan có `decision` khác `pending` bất kể actor (checklist gate mất
  nhắc `replan:<cid>`); không đóng ticket, không lập kế hoạch — chỉ mất một dòng nhắc. Chấp nhận.
- Console (`submit.py`, `decide.py`) **không đổi**: vẫn là cửa của người.

## Cách đo

`tests/test_change_request_khong_can_nguoi.py` (company, 8 ca) và `test_producer_allowed_muc_duoi_hai_cham_sao_la_mot_ho_actor`
(core): không cờ hay `rong` → `publish`/`decide-change` trả 2, không ghi gì; `toan-bo` → ghi như người; orchestrator
bỏ qua CR `accepted` của reviewer khi cờ tắt (ticket vẫn `blocked`, không có plan mới, có `change.untrusted`); replan
do reviewer accepted → ticket đóng, plan mới, gate còn chờ chữ ký.
