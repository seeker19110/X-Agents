# ADR gốc 0037: `reviewer:tu-dong` quyết change request do máy nộp

Ngày: 2026-10-13 · Trạng thái: **được chấp nhận** 2026-10-13. Chủ repo chọn trong chat phương án "Cho tu-dong quyết CR
máy" sau khi được báo change request chỉ phiên chính quyết được, nên khi không ai trực thì dự án đứng chờ. · Sửa: ADR gốc
0034 (agent duyệt tự động chỉ ký gate), ADR gốc 0035 (CR do reviewer quyết ở phạm vi `toan-bo`, trước đây chỉ phiên
chính). · Liên quan: ADR-0051/0057/0058 company (`REPLAN-*`, `REWORK-*`, `GATE3-*`).

## Bối cảnh

Hub thật 2026-10-13, dự án `QLKH-DD-CSV`. Ba đường máy tự nộp change request dưới `delivery-lead`:
- `REPLAN-<ticket>-<thế hệ>`: ticket hết retry (ADR-0051).
- `REWORK-<ticket>-<retry>`: làm lại không đổi code (ADR-0057).
- `GATE3-<RC>`: gate release bị từ chối (ADR-0058).

Sau đó product ước lượng impact (`change.impact`). Cả ba đường dừng ở bước `decide-change`. Agent duyệt tự động
(`xagents-reviewer`, ADR gốc 0034) chỉ đi qua `gate.pending`, không đọc `change-requests`. Chỉ phiên chính
(`reviewer:phien-chinh`) hoặc người mới quyết được.

Đo ngày 2026-10-13:
- REPLAN-DDCSV-31-1 chờ từ 06:16 tới 07:18. Nó chỉ chạy tiếp vì có một phiên Claude đang trực và đọc tới.
- CR-DDCSV-OBS-001 cũng phải chờ phiên đó quyết.

Hub chạy 24/7 bằng systemd, còn phiên chính thì không. Các vòng tự sửa của ADR-0051/0057/0058 tự động hoàn toàn cho
tới bước cuối, rồi đứng ở bước cuối đó.

## Quyết định

1. **`run_tick` của agent duyệt tự động xét thêm change request**, sau các gate, trong cùng trần mỗi vòng
   (`COMPANY_GATE_REVIEWER_MAX_PER_TICK`). Nó chỉ làm việc này khi phạm vi là `toan-bo`, vì ngoài phạm vi đó orchestrator
   không tin quyết định CR của reviewer (`cr_trusted`). Một CR chỉ được xét khi thoả **cả bốn** điều kiện:
   - bản mới nhất có `decision` `pending`;
   - actor là `delivery-lead`, tức máy nộp. CR của người hoặc khách không xét;
   - `impact.kind` thuộc `replan`, `rework_no_change` hoặc `release_gate_reject`;
   - product đã ghi `change.impact` cho đúng mã CR, tức audit-log khoá bằng `change_id` và actor `product`.
2. **Hồ sơ (`cr_reviewer.brief`) gồm:** mô tả và impact của CR, impact cùng các ruling của product, và các CR khác của
   cùng dự án (mã, quyết định, mô tả rút gọn) để nhận ra CR trùng. Model được hỏi theo mục "Change request máy nộp"
   trong `gates/reviewer-tu-dong.md` (version 3). Ba đầu ra:
   - `accepted`: kế hoạch không đổi api-contract, kiến trúc hay phạm vi khách đã nêu, và không chấp nhận rủi ro thay
     khách.
   - `rejected`: CR trùng việc của một CR khác đã `accepted` (phải nêu mã), hoặc lý do không phải việc.
   - `hold`: mọi trường hợp còn lại.
3. **Ghi bằng đúng đường `decide-change`.** Logic của `orch/cli_cmds.py::decide_change` tách thành
   `cr_reviewer.publish_decision`, dùng chung cho CLI và agent: payload mang `decision` và
   `impact.decided_by`/`reason`, actor là `reviewer:tu-dong`. Agent không có lối tắt nào khác CLI.
4. **`hold` là audit `reviewer.cr_hold`** (`change_id`, lý do). Mỗi CR được hỏi model một lần. Lỗi model hay đầu ra
   hỏng cũng thành `hold`. `gate_reviewer holds` in cả CR bị giữ để phiên chính xử lý.
5. **Không đổi gì khác.**
   - Không ký gate thay: replan `accepted` thì gate escalation của ticket cũ vẫn đi đường gate thường.
   - CR do người nộp vẫn của người hoặc phiên chính.
   - Ba việc còn lại như ADR gốc 0036 vẫn cần người: copyleft, chuyển dữ liệu ra nước ngoài, A/B test chạm PII.

## Hệ quả

- Vòng tự sửa của ADR-0051/0057/0058 chạy hết mà không cần phiên trực. Phiên chính chỉ còn xét gate và CR bị máy giữ.
- Chi phí: mỗi CR máy nộp thêm một lượt model `strong`. Trần mỗi vòng giữ nguyên, chia chung với gate.
- Cái giá đã biết:
  - Mô tả CR lấy nguyên từ lý do từ chối hay hint, tức là văn bản của agent khác. Model có thể chấp nhận một kế hoạch
    mà người sẽ từ chối. Lưới an toàn: product đã lọc qua impact, mọi thứ chạm contract, kiến trúc, phạm vi hay rủi ro
    phải `hold`, và kế hoạch sinh ra vẫn qua `_check_plan` cùng review hay security như mọi ticket.
  - Quyết định CR không ký Ed25519 như gate. Tin cậy dựa trên ACL bus (`reviewer:*` được phát `change-requests`) và hai
    cờ hub (`cr_trusted`), đúng như ADR gốc 0035 đã chấp nhận cho phiên chính.

## Liên quan

ADR gốc 0024/0034/0035/0036; `companies/software-company/docs/adr/0051-*`, `0057-*`, `0058-*`.
