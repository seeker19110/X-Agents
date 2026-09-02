# ADR-0003: Mở rộng 18 → 22 agent (con số gốc; thực tế 20)

Trạng thái: Accepted · Ngày: 2026-09-02 · Bổ sung ADR-0002 · Đã đính chính bởi ADR-0009

> Đính chính: `ux-designer` cuối cùng KHÔNG được tách (ADR-0009). Thực tế là 20 agent, khối nghiên cứu 6 — không phải 22 và 9 như bảng dưới. Ba agent còn lại đã được tạo đúng.

## Bối cảnh
Rà soát sau khi tách khỏi MEP-Agents cho thấy 4 lỗ hổng: không ai sở hữu thiết kế UX,
security bị gộp vào reviewer (vi phạm separation of duties và threat model chỉ xảy ra sau
khi có code), không ai xây hạ tầng dài hạn (release-engineer chỉ deploy), không ai sở hữu
dữ liệu phân tích/PII trong analytics.

## Quyết định
| Agent | Khối | Lý do tách |
|---|---|---|
| ux-designer | research | Nguồn dữ liệu khác (người dùng, heuristics), đầu ra khác (flow, tokens); frontend/mobile đang tự đoán giao diện |
| security-engineer | quality | Separation of duties với reviewer; threat model phải có TRƯỚC ticket đầu; DAST/license/DPIA là việc riêng |
| platform | engineering | Skill và tool khác hẳn (IaC, policy, cloud); release-engineer dùng hạ tầng chứ không xây |
| data | engineering | Event/analytics khác OLTP; PII trong kho phân tích cần chủ riêng |

Tổng (con số gốc, nay sai): nghiên cứu 9, quản lý 1, kỹ thuật 6, chất lượng 3, vận hành 2, giám sát 1, human gate.
Thực tế: nghiên cứu 6, quản lý 1, kỹ thuật 6, chất lượng 3, vận hành 3, giám sát 1 = 20 agent.

## Giữ nguyên, không tách
- Reviewer vẫn chạy SAST/SCA/license scan tự động mỗi PR; security-engineer chỉ vào khi ticket có `risk_tags` hoặc trước release.
- Không tách "prompt engineer": quy ước prompt-là-code (ADR-0004) do supervisor giữ, mọi agent tuân.
- Không tách "product manager": intake + spec-writer + delivery-lead đã phủ.

## Hệ quả
- `Assignee` thêm platform, data; `ReviewResult.source` thêm security; namespace thêm design, threat-model, infra, analytics.
- Delivery-lead chờ đủ review theo `risk_tags` (reviewer; cộng qa + security khi có tag — ADR-0021).
- Ticket có thêm `estimate_tokens`, `risk_tags`.
