# ADR-0051: Coordinator hết retry thì nộp change request `REPLAN-*` cho planner lập lại — leo thang retry → replan → người

Ngày: 2026-10-11 · Trạng thái: được chấp nhận · Nguồn ý tưởng: `Workforce` của CAMEL-AI (planner tách khỏi
coordinator; coordinator hết cách thì xin lập lại kế hoạch, không tự cắt việc) · Đối chiếu ở `docs/thi-hanh/cm1.md` ·
Giữ nguyên ADR-0037 (một `product` bốn pha, `_check_plan` là guard code), ADR-0008/0011 (gate escalation là của người),
ADR-0043 (máy không ghi `gate.decide` ngoài sàn tự duyệt), luật "model quyết định – code hành động".

## Bối cảnh

Đo trên `main@db96a3a` (#425):

| # | Hiện trạng | Chỗ |
|---|---|---|
| 1 | Repo **đã** tách planner (`product[plan]`, model) khỏi coordinator (`DeliveryLead`, code xác định) — khác với lời đánh giá ban đầu "gộp hai vai" | `orch/ticket_fsm.py::_plan`, `delivery.py` |
| 2 | Nhưng coordinator chỉ có **hai** nấc khi một ticket hết `max_retries`: `blocked` → gate `escalation` cho người (`reopen` với hint, hay `close`). Không có nấc "việc này cắt sai, lập lại" — người muốn thế phải tự `publish` một change request bằng tay | `delivery.py::_retry`, `orch/gates_flow.py::_check_escalations`, `_on_escalation_decided` |
| 3 | Đường "CR → planner lập kế hoạch thẳng" đã có sẵn và đã có test: `change-requests` `accepted` không đổi yêu cầu → `product[plan]` → `_check_plan` → dispatch | `orch/routes.py::PLAN_INPUTS` (`_cr_accepted_direct`), `tests/test_orchestrator.py::test_change_request_impact_then_human_decision_then_plan` |
| 4 | ACL bus: chỉ `ops` được phát `change-requests`; `audit-log` mở nhưng `gate.decide` chỉ người/`code`(sàn)/`orchestrator`(UAT) — máy không đóng được gate escalation | `core.py::TOPIC_PRODUCERS`, `bus.py::_extra_publish_checks`, `gate_cli._trusted` |

Vòng thật đã đo (`docs/reports/`, QLKH 2026-09-05/06): ticket cắt sai bị `reopen` 7 lần, mỗi lần agent làm lại cùng
một việc không làm được; người chỉ có nút "làm lại" và "bỏ", không có nút "cắt lại".

## Quyết định

1. **Nấc thứ ba do code nộp, người quyết.** `DeliveryLead._retry` khi chạm `max_retries` (sau audit `ticket.blocked`)
   gọi `_request_replan`: phát `change-requests` `REPLAN-<ticket>-<thế hệ>` dưới actor `LEAD_ACTOR`, `decision=pending`,
   `affects_requirements=[]` (đi đường `_cr_accepted_direct`), `impact={"kind": "replan", "ticket_id", "generation",
   "retry", "hint", "dependents"}`, `description` nêu lỗi cuối, requirement, ticket đang chờ và yêu cầu **id mới**
   (`_check_plan` từ chối id đã tồn tại, kể cả ticket đã đóng). ACL: `"change-requests": {ops, LEAD_ACTOR}`.
2. **Đi đúng đường CR thường, không đường riêng.** `product[plan]` ước lượng impact (`change.impact`), người
   `decide-change <cid> accepted|rejected|deferred --by human:*`. Gate escalation của ticket vẫn mở song song; checklist
   của nó thêm mục `replan:<cid>` khi CR đang chờ (`DeliveryLead.replan_open`), để người thấy cả ba lựa chọn một chỗ.
3. **Chấp nhận = ticket cũ đóng như bị từ chối ở escalation.** `orch/gates_flow.py::_retire_replanned` (gọi từ `_plan`
   TRƯỚC lượt planner): ticket còn `blocked`/`escalated` → `close_escalated` (ticket phụ thuộc không âm thầm chạy trên
   nền thiếu — chúng `blocked` và có gate riêng), audit `ticket.replanned {ticket_id, change_id, by, dependents_blocked}`;
   ~~ticket đã được người `reopen` trước đó và đang chạy → **không đóng sau lưng ai**, chỉ lập kế hoạch mới
   (`replan:<tid>:not_blocked`)~~. `rehydrate` dựng `ticket.replanned` như `ticket.abandoned`.
   **Sửa 2026-10-14** (đo hub QLKH-DD-CSV): DDCSV-35 được `reviewer:tu-dong` mở lại trước khi CR được quyết, rồi CR
   được chấp nhận → `not_blocked`, ticket cũ chạy song song DDCSV-51..53 tách từ chính nó (cùng một middleware, hai lần
   ngân sách). Chấp nhận replan là quyết định **sau cùng** về ticket: ticket **chưa xong** (mọi trạng thái trước
   `approved`, kể cả đang chạy lại) → đóng như trên; ticket đã `approved`/`merged`/`released`/`closed` → giữ (code đã có,
   đóng là bỏ việc thật), action `replan:<tid>:done`. Sổ `DeliveryLead.replan_accepted` (dựng lại từ bus) +
   `retire_accepted_replans` ở đầu mỗi `tick()` đối soát lại, nên ticket bản cũ bỏ sót cũng đóng sau khi deploy; sổ ghi mọi event `accepted` nhưng đối soát
   chỉ tin event qua `cr_trusted` (cùng luật route `_cr_accepted`, ADR gốc 0035).
4. **Gate escalation đóng dưới chữ ký người, ngay trong `decide-change`.** Máy không ghi `gate.decide` được (bus chặn,
   `_trusted` không tin khi replay — cố ý, ADR-0043); nên `cli_cmds.decide_change` khi CR là replan và `accepted` ký
   `reject` gate escalation của ticket cũ **dưới tên người vừa gõ lệnh**, reason mang `cid`. Nhánh `reject` của
   `_on_escalation_decided` gặp ticket đã đóng thì ghi `closed:<tid>:already`, không `close_escalated` lần hai.
5. **Trần thế hệ.** `replan_rounds=1` (ctor `DeliveryLead`): thế hệ tính theo **chuỗi nhân quả** (`cause` của ticket là CR
   replan → thế hệ `impact.generation + 1`), không theo id vì planner đặt id mới. Ticket sinh từ replan lại hết retry →
   thế hệ 2 > trần → không nộp nữa, chỉ còn gate escalation. Cùng (ticket, thế hệ) chỉ nộp **một** CR (`replans_filed`
   dựng lại từ bus): người `reopen` rồi ticket block lần nữa không sinh CR trùng. `replan_rounds=0` tắt hẳn.

## Phương án đã loại

- **Coordinator tự cắt lại ticket** (như Workforce khi không có planner riêng): vi phạm "model quyết định – code hành
  động" ở chiều ngược — code bịa kế hoạch. Planner là model, giữ nguyên.
- **Replan là một `decision` mới của gate escalation** (`reopen|close|replan`): đẹp hơn một bước nhưng phải sửa
  `gate_reviewer.SCOPE_CHECKLIST`, console, `gate_cli`, golden hồ sơ escalation và khuôn Ruling — trong khi đường CR
  đã có đủ ước lượng impact + chữ ký người + planner. Chọn tái dùng; khi `/gate-review` cần quyết replan thì mở lại.
- **Máy đóng gate escalation khi CR được chấp nhận** (`gate.decide` by `delivery-lead`): bus chặn, và nới `_trusted`
  cho một actor máy nữa là mở đúng lỗ hổng sc-security 2026-09-23 đã đóng. Để người ký, ngay trong lệnh họ đang gõ.
- **Đếm thế hệ theo dự án**: một dự án 20 ticket chỉ được một lần replan — quá chặt; theo chuỗi nhân quả đúng hơn và
  đã có sẵn (`cause`, ib1-quansat Q1).

## Hệ quả

- Người vận hành thấy ở gate escalation một mục checklist `replan:REPLAN-T1-1`; chấp nhận bằng
  `decide-change REPLAN-T1-1 accepted --by human:<tên> --reason "<vì sao cắt lại>"` — lệnh in thêm dòng gate đã ký.
- Ticket phụ thuộc ticket bị thay vẫn `blocked` + gate riêng (hành vi `abandon` cũ). Planner được báo danh sách này
  trong `description` để lập lại cả chúng nếu cần; chưa tự động đóng chúng theo — **còn mở**, đo vài vòng thật rồi mới quyết.
- Không đụng prompt `agents/product.md` (không cần `eval-record`): CR replan là đầu vào JSON như CR thường, description
  nói rõ yêu cầu id mới. Nếu đo thấy planner hay dùng lại id cũ thì sửa prompt ở PR riêng theo 7 bước.
- Test: `tests/test_replan_adr0051.py` (10 ca, hai chiều); golden `tests/golden/gate_brief/escalation.json` đổi đúng
  một mục checklist.
