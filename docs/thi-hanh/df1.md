# DeerFlow 2.0 — một thứ lấy ngay, sáu thứ ghi sổ lấy sau

Ngày lập 2026-10-11 · căn cứ `main@db96a3a` (#425) + nhánh `claude/blissful-dirac-if7wwx` (cm1, PR #426) · báo cáo đầu vào
`docs/reports/2026-10-11-doi-chieu-deerflow.md`. Đề bài: *"nghiên cứu repo này giúp ích được gì"* → *"ok triển khai,
những cái tốt ghi nhận lại sau này lấy sau"*.

## A. Hiện trạng

### A1. Kết luận

- DeerFlow là harness cho **một siêu agent trò chuyện** (manager là LLM); X-Agents là **dây chuyền công ty** (manager
  là code, human gate, bus có ACL). 80 % DeerFlow là sản phẩm khác, không phải cơ chế thiếu.
- Một cơ chế đáng lấy có sự cố ở đây: **blocker có kiểu**. `TRAPS.md` "Tính hết lượt là làm sai" (CAMPUS-UNI 2026-09-24)
  để ngỏ câu hỏi retry đang đếm cái gì; repo trả lời bằng năm bộ đếm rời. Lấy phần *kiểu do code gán*, bỏ phần
  *evaluator model* (luật cấm 8).
- Sáu thứ còn lại tốt nhưng chưa có sự cố: ghi sổ ở báo cáo §4, mỗi dòng một điều kiện quay lại và một lệnh đo.

### A2. Bảng đối chiếu

Ở báo cáo §2–§4 (ba cột, `file:dòng`).

## B. Kế hoạch

| Mã | Việc | Mảng | Hạng mục | Mức | Ưu | Nhược | Khi nào |
|---|---|---|---|---|---|---|---|
| S1 | ADR-0052: `StopKind`, `STOP_POLICY`, `classify_error` một chỗ; hai hằng cũ đọc từ bảng | company | df1-stopkind | C3 | Thêm kiểu dừng = một dòng bảng | Dời `cli_subtype` khỏi `error_flow` (giữ tên cũ) | xong (commit này) |
| S2 | `stop_kind` vào sáu audit dừng; `DeliveryLead.stops`; `ticket.blocked` + `REPLAN-*` mang `stops`; `reopen` xoá | company | df1-stopkind | C2 | Câu hỏi `TRAPS.md` trả lời bằng audit | Evidence `ticket.blocked` dài thêm một trường | xong (commit này) |
| S3 | Hồ sơ gate escalation hiện `stops`; golden đổi một trường | company | df1-stopkind | C1 | Người duyệt thấy ngay | — | xong (commit này) |
| R1 | Báo cáo đối chiếu §H + sổ "lấy sau" có lệnh đo | docs | df1-report | C1 | Không mất ý | — | xong (commit này) |
| D1 | CODEMAP, TRAPS trỏ ADR, CHANGELOG, README số liệu, nhật ký, file này | docs | df1-docs | C1 | — | — | xong (commit này) |
| L1 | Gộp `turn_continuations` + `conflict_retries` thành `stop_counts[tid][kind]` | company | — | C2 | Một bộ đếm | 22 tham chiếu test, `state.py` ledger | **lấy sau**: khi có kiểu dừng thứ ba có `free_stops` |
| L2–L6 | Compaction LLM · loop detection tool call · nạp skill muộn · sandbox allowlist · batch bền | company/core | — | C2–C3 | — | — | **lấy sau**: điều kiện và lệnh đo ở báo cáo §4 |

**Cố ý không làm**: evaluator model chấm goal; DeerMem/SOUL.md; prompt overlay; đổi bất kỳ số trần nào trong ADR này.

## C. Gói việc

### df1-stopkind — ADR-0052
`src/company/stop_kind.py`; `orch/routes.py` (hằng đọc bảng), `orch/error_flow.py` (phân loại, `stop_kind`, `rework(kind=)`),
`orch/scheduler.py::_defer` (`error_kind=infra_transient`), `orch/worktree_flow.py` (`merge_conflict`), `delivery.py`
(`_retry(kind)`, `stops`, evidence), `gate_brief.py` (`stops`); `tests/test_stop_kind_adr0052.py` 15 ca;
`tests/golden/gate_brief/escalation.json`. Hai chiều: đỏ trước (`ModuleNotFoundError`), xanh sau.

## D. Điều phối

Phiên chính làm cả gói (một package, test ≤ 4 phút). Không hỏi người: không có thao tác không đảo ngược, không
đổi quyền, không đổi số trần.

## F. Lệnh thi hành

```bash
scripts/dev-task.sh gate company && scripts/dev-task.sh gate console
cd companies/software-company && uv run python -c "from company.stop_kind import STOP_POLICY; print(STOP_POLICY)"
```
