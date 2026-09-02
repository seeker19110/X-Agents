# ADR-0006: Gộp 4 agent nghiên cứu, thêm account-manager, staging QA và nghiệm thu khách

Trạng thái: Accepted · Ngày: 2026-09-02 · Sửa ADR-0002/0003

## Bối cảnh
Rà soát quy trình sau ADR-0005 cho thấy: (1) bốn agent nghiên cứu (domain, ux-designer, codebase, tech-scout) cùng đọc
và ghi một topic, synthesizer không có tiêu chí biết khi nào đủ; (2) công ty gia công nhưng không có bước nghiệm thu
của khách và kiểm soát thay đổi phạm vi; (3) release candidate đi thẳng ra production, không có staging, không QA trên
bản gộp; (4) `depends_on` có trong schema nhưng không ai lập lịch; (5) review không có thời hạn; (6) bài học trong
`knowledge` không quay lại agent; (7) nhiều agent thiếu skill mà chuẩn bắt buộc (backend không có `api-contract`
dù sở hữu namespace đó, kỹ thuật không có `observability`...).

## Quyết định
1. **Gộp domain + ux-designer + codebase + tech-scout → `researcher`** (yêu cầu của chủ dự án). Một báo cáo 4 mục
   (domain, ux, codebase, tech), sở hữu `glossary` và `design`. Synthesizer chỉ bắt đầu khi có báo cáo intake + researcher.
   Front matter `context_namespace_write` nhận danh sách; delivery-lead nay khai báo cả `architecture` và `api-contract`.
2. **Thêm `account-manager`** (khối vận hành): SOW và kịch bản UAT trong namespace `contract`; topic mới
   `change-requests` (thay đổi phạm vi, có impact và quyết định của khách) và `acceptance-results` (biên bản nghiệm thu,
   người ký của khách). Ticket chỉ `closed` khi khách accepted; rejected → ticket quay lại với hint từ finding.
3. **Staging bắt buộc trước gate 3**: release-engineer deploy staging (`release-events` env=staging) → qa-debugger chạy
   hồi quy + perf + a11y trên bản gộp, ghi `review-results` với `ticket_id = release_id` → pass mới xin gate 3 → production.
   Trạng thái ticket thêm `merged` (approved → merged → released → closed) và `waiting`.
4. **Lập lịch theo `depends_on` và `priority`** trong code delivery-lead; rollback/failed production mở lại ticket.
5. **Review có thời hạn** 2h (`DeliveryLead.overdue_reviews`), supervisor warn rồi escalate.
6. **Vòng học**: runner đưa toàn bộ blackboard (kể cả `knowledge`) vào ngữ cảnh; supervisor có `sprint_report`
   estimate vs actual cho retrospective.
7. **Incident có `root_cause_class`**: requirement → `research-requests`; design → cập nhật architecture/threat-model;
   code/ops → ticket.
8. **Skill mới**: performance-testing, accessibility, i18n, event-driven-architecture, ai-feature-engineering,
   customer-acceptance. **Gán lại**: backend +api-contract/observability/event-driven/i18n/ai; frontend, mobile
   +observability/accessibility/i18n; database +observability; data +event-driven; reviewer +testing; qa-debugger
   +performance-testing/accessibility; release-engineer +observability/incident-management; risk +threat-modeling;
   spec-writer +customer-acceptance; delivery-lead +risk-analysis/release/event-driven.

Tổng: nghiên cứu 6, quản lý 1, kỹ thuật 6, chất lượng 3, vận hành 3, giám sát 1 = 20 agent; 35 skill.

## Hệ quả
- Mọi prompt đổi đều tăng `version` và golden được sinh lại.
- Eval cho researcher cần viết mới (4 mục); eval cũ của 4 agent bị gộp không còn áp dụng.
- Chưa có: giao diện UAT cho khách (hiện qua account-manager + CLI), orchestrator tự động (ADR-0005 còn nợ).
