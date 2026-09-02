# ADR-0007: Orchestrator — vòng lặp tự động topic → agent → topic

Trạng thái: Accepted · Ngày: 2026-09-02 · Bổ sung ADR-0005/0006

## Bối cảnh
Sau ADR-0005 runner chạy được model thật nhưng mỗi bước phải gọi tay (`company.runner <agent> <topic_out> input.json`).
Cần một vòng lặp tự nối các bước theo bảng topic (`docs/architecture.md`) và front matter `reads`/`writes`, nhưng
vẫn giữ nguyên ba nguyên tắc: human gate không bao giờ tự đi tiếp, supervisor có quyền dừng, khách là người ký.

## Quyết định
1. **Bảng route tường minh** (`orchestrator.ROUTES`): `(topic_in, agent, topic_out, điều kiện)`. Không suy luận mù từ
   `reads` (vì một topic có nhiều consumer và vài agent đọc/ghi cùng topic — researcher, risk); bảng được kiểm tra lúc
   khởi tạo phải khớp front matter (`check_routes`), lệch là lỗi. Khối kỹ thuật chọn theo `tasks.assignee`;
   security-engineer chỉ chạy khi `DeliveryLead.required_reviews` đòi.
2. **Delivery-lead lập kế hoạch bằng một lượt sinh nhiều ticket** (`AgentRunner.generate(many=True)` → `{"items": [...]}`),
   kết quả KHÔNG publish thẳng: code kiểm (`estimate_tokens`, budget ≥ ×1.5, `depends_on`, ticket_id chưa tồn tại) →
   ghi `audit-log` `plan.proposed` → xin gate `plan` → khi duyệt mới `DeliveryLead.dispatch` từng ticket theo thứ tự
   phụ thuộc. Cùng đường cho `approved-specs`, `incidents` (root_cause_class code/ops/design) và `change-requests` accepted.
3. **Ba điểm dừng bắt buộc**: `approved-specs` xin gate `spec` (`SPEC-<project>`); plan xin gate `plan`
   (`PLAN-<project>-<n>`); production chỉ chạy khi gate `release` (`REL-xxx`) approve — release-engineer nhận RC kèm
   `target_env`, đầu ra sai env/release_id bị coi là `invalid_output`, không publish. Event chờ gate hoặc chờ ticket
   bị supervisor pause/budget_cut/escalate được **hoãn** (không đánh dấu đã xử lý) và thử lại khi có `gate.decide`
   hoặc `resume`.
4. **Việc của người không được tự sinh**: `clarification-answers`, `acceptance-results`, `change-requests.decision`,
   `external-feedback` vào bus qua `company.orchestrator publish` (hoặc bất kỳ producer nào). Orchestrator chỉ đọc.
5. **Trạng thái nằm trong log**: mỗi event xử lý xong ghi `audit-log` (actor=orchestrator, action=orchestrated,
   evidence={event_id, actions}); mở lại bus SQLite thì replay dựng lại DeliveryLead/Supervisor (chế độ `replaying`:
   đổi state, không phát lại event), PersistentGate và danh sách plan, rồi xếp hàng các event chưa xử lý. Event từ
   tiến trình khác (gate CLI, publish) vào qua `SQLiteBus.poll()` ở mỗi nhịp `--watch`.
6. **Không retry lời gọi model** (giữ ADR-0005): lỗi ghi audit rồi vòng lặp đi tiếp; delivery-lead retry theo hint,
   supervisor xử lý hạn mức, `tick()` nhắc gate/review quá hạn qua audit (`gate.remind`, `review.overdue`).

## Hệ quả
- Một lệnh `make run` (hoặc `--watch 5`) chạy cả công ty; con người chỉ dùng `gate_cli` và `publish`.
- Thêm bước mới = thêm một dòng ROUTES + test; sai front matter là lỗi khởi tạo chứ không phải lỗi âm thầm lúc chạy.
- Review một PR chạy tuần tự trong một tiến trình; chạy song song nhiều máy cần bus Redis/Kafka (chưa có).
- Chưa nối: security-engineer làm threat model từ `approved-specs` (ghi blackboard, không phải topic), support-docs
  từ `release-events`/`external-feedback`, incident `root_cause_class=requirement` → `research-requests`.
