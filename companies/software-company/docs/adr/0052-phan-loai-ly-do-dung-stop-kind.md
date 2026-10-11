# ADR-0052: Một bảng phân loại lý do dừng (`StopKind`) — mọi audit dừng mang `stop_kind`, `ticket.blocked` nói rõ retry đã đếm cái gì

Ngày: 2026-10-11 · Trạng thái: được chấp nhận · Nguồn ý tưởng: blocker có kiểu của session goal trong DeerFlow 2.0
(`missing_evidence | needs_user_input | run_failed | external_wait | goal_not_met_yet`, đối chiếu ở
`docs/reports/2026-10-11-doi-chieu-deerflow.md`) · Giữ nguyên ADR-0012 (retry là của `DeliveryLead`), ADR-0034 (tách
`orch/`), ADR-0051 (replan khi hết retry), luật "model quyết định – code hành động".

## Bối cảnh

`TRAPS.md` dòng "Tính hết lượt là làm sai" (CAMPUS-UNI 2026-09-24) kết bằng câu hỏi kiểm: *"bộ đếm retry này đang
đếm lỗi của agent, hay đếm trục trặc của hạ tầng/trần?"*. Mỗi lần trả lời câu đó, repo thêm **một bộ đếm riêng, một
hằng riêng, một audit riêng** — đo trên `main@db96a3a` (#425) + ADR-0051:

| # | Lý do dừng | Quyết định ở | Bộ đếm / trần | Audit |
|---|---|---|---|---|
| 1 | hết lượt tool mà worktree có tiến độ | `orch/error_flow.py::_continue_after_turn_cap` | `turn_continuations` / `MAX_TURN_CONTINUATIONS=3` (`routes.py`) | `ticket.continued` |
| 2 | CLI ép schema hỏng | `error_flow.py::_autoretry_once` | khoá `once` một lần / `AUTORETRY_SUBTYPES` | `llm.autoretry` |
| 3 | transport chập chờn | `orchestrator.py` `except TransientError` → `scheduler._defer` | `transient_since` / `transient_limit()` | `defer.until`, rồi `agent_error_unhandled` |
| 4 | xung đột merge | `orch/worktree_flow.py` | `conflict_retries` / `MAX_CONFLICT_RETRIES=6` (`routes.py`) | `integration.conflict` |
| 5 | nội dung sai (test đỏ, review block, khách từ chối) | `delivery.py::_retry` | `Task.retry` / `max_retries=3` | `ticket.blocked` |
| 6 | lỗi không nhánh nào nhận, chuỗi nghiên cứu chết | `error_flow.py::_mark_unhandled`, `_stall` | `unhandled_count`, `stall_count` | `agent_error_unhandled`, `project.stalled` |
| 7 | cùng chữ ký lỗi ≥ 2 | `supervisor.py` | `error_signatures` | `supervisor-actions escalate` |

Hệ quả đo được: `ticket.blocked` chỉ nói `retry=3`, không nói ba lần đó là ba lần test đỏ hay hai lần xung đột merge
+ một lần hết lượt. Hồ sơ gate escalation (`gate_brief`) phải lần ngược 40 dòng `history` để đoán. Người thêm trần mới
không có chỗ nào để xem "các trần đang có là gì, trần nào đốt retry".

## Quyết định

1. **Một module, một bảng.** `src/company/stop_kind.py` khai `STOP_KINDS` (`agent_error`, `turn_limit`,
   `infra_transient`, `merge_conflict`, `budget`, `needs_human`, `no_progress`) và `STOP_POLICY: dict[StopKind, Policy]`
   với `Policy(burns_retry, free_stops, then)`: `burns_retry` = có đốt `Task.retry` không; `free_stops` = số lần dừng
   kiểu này được miễn trước khi tính như `agent_error` (`turn_limit=3`, `merge_conflict=6`); `then` = việc code làm
   (`retry | continue | defer | escalate`). Hai hằng `MAX_TURN_CONTINUATIONS`, `MAX_CONFLICT_RETRIES` ở `routes.py`
   nay **đọc từ bảng**, không còn là hai số rời.
2. **Một chỗ phân loại.** `classify_error(error) -> StopKind` đọc `TransientError`, `LLMError.head` (`cli_subtype`,
   chuyển từ `error_flow.py` sang đây cùng `AUTORETRY_SUBTYPES`); không soi chữ của model (giữ nguyên lý do ở
   docstring `cli_subtype`). `error_flow` rẽ nhánh theo `classify_error`, không theo chuỗi `subtype` rải rác.
3. **Mọi audit dừng mang `stop_kind`.** `ticket.continued`, `llm.autoretry`, `integration.conflict`,
   `agent_error_unhandled`, `project.stalled`, `ticket.blocked` thêm trường `stop_kind` vào evidence.
4. **`DeliveryLead._retry(tid, hint, kind)` đếm theo kiểu.** `self.stops[tid]: Counter[kind]`; `ticket.blocked` mang
   `stop_kind` (lần cuối) và `stops` (đếm theo kiểu) — câu hỏi của `TRAPS.md` trả lời bằng chính dòng audit. `reopen`
   xoá `stops[tid]` cùng `retry`. CR `REPLAN-*` (ADR-0051) mang `stops` trong `impact` để planner biết ticket chết vì gì.
5. **Hồ sơ gate escalation hiện `stops`.** `gate_brief` đọc `stops` từ `ticket.blocked` mới nhất của ticket vào
   `extra.ticket.stops`; golden đổi đúng một trường.

## Phương án đã loại

- **Gộp `turn_continuations` + `conflict_retries` thành một `stop_counts[tid][kind]`**: đúng hướng nhưng chạm 5 file
  test (22 tham chiếu), `state.py` ledger nguồn audit, `rehydrate`. Để lại, điều kiện quay lại: xuất hiện kiểu dừng
  thứ ba có `free_stops` (lúc đó bộ đếm thứ ba là bằng chứng bảng chưa đủ).
- **Evaluator model chấm "đã đạt goal chưa" như DeerFlow** (`goal_not_met_yet`, trần 8 lần tiếp tục): model chấm model
  là lời khai (luật cấm 8); ở đây tiêu chí xong là code (`_check_plan`, review, smoke `verified_by=orchestrator`).
- **Đổi `max_retries` theo kiểu ngay** (vd `infra_transient` không bao giờ đốt): hành vi hiện tại đã đúng cho từng kiểu
  qua các đường riêng; ADR này chỉ làm nó **đọc được ở một chỗ**, không đổi số nào. Đổi số là PR riêng có đo.

## Hệ quả

- `status`/`gate_brief`/`trace` đọc `stop_kind` ngay trong evidence, không đoán từ chuỗi lỗi.
- Thêm một kiểu dừng = thêm một dòng bảng + một chỗ gán `kind`, không phải thêm hằng ở `routes.py`.
- Test: `tests/test_stop_kind_adr0052.py`; `tests/golden/gate_brief/escalation.json` đổi một trường (`UPDATE_GOLDEN=1`).
- `TRAPS.md` dòng "Tính hết lượt là làm sai" trỏ về ADR này ở cột "Phòng".
