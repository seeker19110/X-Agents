# ADR-0017: Nghiệm thu của khách là một human gate thật

Trạng thái: Accepted · Ngày: 2026-09-02 · Bổ sung ADR-0001

## Bối cảnh
Tài liệu luôn nói công ty có bốn điểm con người duyệt, nhưng trong code chỉ có ba: `GateKind` gồm spec, plan, release
(cộng escalation cho bất thường). Nghiệm thu chỉ là một dòng `uat.pending` trong `audit-log` rồi chờ ai đó publish
`acceptance-results`. Nghĩa là điểm dừng quan trọng nhất với khách hàng lại là điểm duy nhất không có hạn, không có
nhắc, không có four-eyes — và cũng không ai biết nó đang treo.

## Quyết định
`acceptance` là `GateKind` thứ năm. Khi `release-events` báo đã deploy production, orchestrator mở gate
`UAT-<release_id>` với checklist `uat-script`, `acceptance-criteria`, `known-issues`, `signed_by`.

Chữ ký của khách trong `acceptance-results` đóng gate: `accepted` → approve, `rejected` → reject, `conditional` →
request_changes (phần còn lại đi qua change request như cũ). Vì `HumanGate.decide` cưỡng chế `decided_by != created_by`
và gate do account-manager tạo, công ty không thể tự ký thay khách.

Gate quá hạn ở mọi loại nay được supervisor escalate, không chỉ ghi audit. Quá hạn vẫn không tự đi tiếp — nhưng cũng
không còn im lặng.

## Hệ quả
- `gate_cli list` hiển thị cả gate nghiệm thu, nên trạng thái "đang chờ khách ký" nhìn thấy được cùng chỗ với các gate khác.
- Timeout 24h áp cho khách là mặc định kỹ thuật, không phải điều khoản hợp đồng; hạn thật nằm trong SOW.
- `gates/checklists.md` mô tả Gate 4 theo đúng khoá code gửi, thay vì mô tả một quy trình không có gì cưỡng chế.
