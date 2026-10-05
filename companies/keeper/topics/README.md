# Topics

Mỗi file JSON Schema (`schemas/<topic>.json`) mô tả envelope + payload của một topic. **Viết tay** — repo
không có script sinh schema nào (đo 2026-09-09); thứ giữ chúng khớp `src/keeper/events.py` là test
`tests/test_bus.py::test_moi_topic_co_schema_dung_khuon_studio`, không phải một lệnh `make`. Bus validate trước khi ghi. Owner ghi của `shared-context` theo namespace (nguồn
sự thật: `NAMESPACE_OWNERS` trong `events.py`):

| namespace | owner | nội dung |
|---|---|---|
| knowledge | keeper-supervisor | bài học bảo trì lặp qua nhiều ticket, không thuộc ticket nào |

## Bảng "Topic của `keeper`" (`DAC-TA-KEEPER.md` §1)

| topic | producer | nội dung |
|---|---|---|
| `maintenance-signals` | `dependency-scout`, `health-monitor`, `drift-detector`, `adapter:github` | một quan sát thô, chưa phán xét |
| `maintenance-tickets` | `triager` | signal đã gom + `risk_tier` + hạn |
| `patch-proposals` | `patcher`, `refactorer` | nhánh + diff + phạm vi |
| `verification-reports` | `regression-guard` | bằng chứng hai chiều + kết quả rà họ lỗi |
| `security-findings` | `security-auditor` | gitleaks / audit dependency / Scorecard |
| `debt-ledger` | `triager`, `keeper-supervisor` | thứ đã hoãn + ngày đáo hạn |
| `release-notes` | `release-clerk` | dòng CHANGELOG + mục nhật ký phiên |
| `supervisor-actions` | `keeper-supervisor` | dừng, hạ hạn mức, escalate |
| `audit-log`, `shared-context` | mở | như hai công ty kia |

`human_topics = {"maintenance-signals"}` — người nạp tay một việc bảo trì được, nhưng **không** nạp tay ticket:
ticket phải đi qua `triager` để có `risk_tier`.

## Quy ước khác trong payload

- `maintenance-signals.semver_jump` chỉ có nghĩa khi `kind="dependency"`.
- `verification-reports.before.exit_code == 0` là báo cáo vô hiệu (bất biến I2, `evidence.py:require_two_way`):
  tắt bản sửa mà lệnh CI vẫn xanh nghĩa là test không đo được gì.
- `verification-reports.verified_by` chỉ được code điền sau khi vừa chạy lệnh; không bao giờ nhận từ JSON model
  trả về (`AGENTS.md` cấm §8).
- `verification-reports.patch_id` là id cây git của nội dung worktree lúc đo (`worktree.content_tree`), do
  `collect_two_way` điền — cùng luật với `verified_by`. Báo cáo thiếu nó (hình dạng trước ADR keeper 0001) bị
  orchestrator từ chối; cổng `evidence` chỉ mở khi worktree của ticket VẪN đúng nội dung ấy.
- `release-notes.pr_number` là `null` cho tới khi PR có số; điền `(#n)` rồi commit tiếp vào chính PR đó
  (`AGENTS.md` §10), không mở PR thứ hai để vá số.
