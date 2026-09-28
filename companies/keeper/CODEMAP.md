# CODEMAP.md — keeper: muốn đổi X thì sửa ở đâu

Mỗi module trong `src/keeper/` có tên trong bảng dưới (cổng `platform/console/tests/test_cong_tai_lieu.py` đỏ khi
thêm module mà quên dòng ở đây). Cột "Kiểm" trỏ test chính; `docs/DAC-TA-KEEPER.md` là đặc tả đầy đủ nếu cần hiểu
sâu hơn bảng này.

| Muốn | Sửa | Kiểm |
|---|---|---|
| Vòng lặp chính: watch → triage → patch → verify → gate? → release | `orchestrator.py` — resume qua `SQLiteBus`, chạy lại không làm lại việc đã xong | `tests/test_orchestrator.py` |
| Phát hiện tín hiệu dependency (uv.lock + dependabot alert) | `dependency-scout` (`scout.py`) | `tests/test_scout.py` |
| Phát hiện tín hiệu bảo mật (gitleaks, audit, Scorecard) | `security-auditor` (`audit.py`) | `tests/test_audit.py` |
| Phát hiện tín hiệu drift (bản dẫn xuất lệch nguồn) | `drift-detector` (`drift.py`) — ba phép so cục bộ, không gọi mạng, chỉ phát Signal (I5: không tự xoá) | `tests/test_drift.py` |
| Phát hiện tín hiệu sức khoẻ CI | `health-monitor` (`health.py`) — flake rate, thời gian CI p50/p95, tuổi PR mở, độ trôi coverage | `tests/test_health.py` |
| Gộp tín hiệu trùng | `signals.dedupe()` — khoá `(kind, subject)`, giữ bản theo thứ tự xuất hiện | `tests/test_signals.py` |
| Tín hiệu → ticket | `triager` (`triage.py`) — khoá chống trùng theo THẾ HỆ (số vòng đời ticket đã đóng), không chỉ theo id | `tests/test_triage.py` |
| Bậc rủi ro → tự động vá hay cần người | `risk_tier()` (`risk.py`) — bảng `RISK_RULES` tra theo tên hàng, khớp hàng ĐẦU TIÊN, `high` luôn trước `low` | `tests/test_risk.py` |
| Ba thao tác vá hợp lệ | `patcher.py` — `bump_dependency`, `regen_derived`, `fix_docs`; `FORBIDDEN_PATHS` chặn `.git/`+`.github/` (I4) | `tests/test_patcher.py` |
| Bằng chứng đo hai chiều | `evidence.require_two_way()` — ném `EvidenceError` nếu chưa từng đỏ hoặc chưa xanh (I2) | `tests/test_evidence.py` |
| Ngân sách PR/tuần | `budget.can_open_pr()` — LUÔN hỏi GitHub thật, không đếm RAM (I3) | `tests/test_budget.py` |
| Sổ nợ kiến trúc, hạn đáo | `ledger.py` — `DebtEntry(due_at=...)`, cơ chế RIÊNG của keeper, không dùng `debt_due` của core | `tests/test_ledger.py` |
| Soạn dòng CHANGELOG + điền số PR | `release-clerk` (`release.py`) — `compose()` soạn với `PR_PLACEHOLDER`; `fill_pr_number()` điền `(#n)` sau khi có PR thật | `tests/test_release.py` |
| Push nhánh ticket + `gh pr create` THẬT | `publish.py` (`push_branch`, `create_pr`) — capability ghi thứ ba của I1, tách khỏi `github.py` (giữ nguyên "chỉ đọc") | `tests/test_publish.py` |
| Biến ý định PR thành PR thật cho một ticket | `KeeperOrchestrator.publish()` (`orchestrator.py`) — push + tạo PR + `fill_pr_number`, qua CLI `keeper publish <ticket_id>` | `tests/test_orchestrator_publish.py`, `tests/test_cli_publish.py` |
| Đọc GitHub chỉ đọc (không ghi) | `GitHubReader` (`github.py`) — `_run()` ném `GitHubWriteAttempt` khi argv có cờ ghi (I1) | `tests/test_github.py` |
| Worktree riêng mỗi ticket | `worktree.py` — luật tuyệt đối: không bao giờ `reset --hard`/`clean` trên checkout CHUNG | `tests/test_worktree.py` |
| Gate của keeper | `gates.py` — bọc `HumanGate`/`PersistentGate` của lõi | `tests/test_gates.py` |
| Client model (offline mặc định) | `llm.py` — tiền tố env `KEEPER_*`, provider mặc định `fake` | `tests/test_llm.py` |
| Runner một agent | `runner.py` — nạp AgentSpec → build prompt (envelope+blackboard) → gọi model → ép JSON → publish → audit | `tests/test_runner.py` |
| Nạp danh sách agent | `registry.load_agents()` — `AgentSpec` của lõi (không lớp con riêng); `check_owners=False` vì `keeper/skills/` chưa tồn tại | `tests/test_runner.py`, `tests/test_golden_agents.py` |
| Blackboard giữa các agent | `blackboard.py` — lớp con mỏng của `xagents_core.blackboard`, `store=None`; chưa agent nào ghi namespace, tồn tại vì `EvalSuite.run_eval` dựng một cái cho mỗi ca | `tests/test_runner.py` |
| Eval prompt: ghi/phát lại, ngưỡng điểm | `evals.py` — `python -m keeper.evals <agent>` (hoặc `all`), `--record` (model thật) / `--replay --strict` (CI); đỏ khi BẤT KỲ ca nào `errored`, cộng `evals/thresholds.yaml` gác điểm; bộ ca `evals/<agent>.yaml` chỉ 4/10 agent (lý do trong docstring) | `tests/test_evals.py` |
| Bus/envelope riêng của keeper | `bus.py` (`KeeperBus`/`KeeperMemoryBus`), `events.py` (`Topic`, `PAYLOAD_MODELS`, `NAMESPACE_OWNERS`) | `tests/test_bus.py`, `tests/test_events.py` |
| Cấu hình gốc/tên công ty | `core.py` — `CORE = CoreConfig(prefix="KEEPER", ...)`, MỘT chỗ duy nhất | `tests/test_core.py` |
| Test không chạm mạng thật | `fakes.FakeGitHub` — JSON cố định, mọi test dùng | — |
| Báo cáo "rà cả họ lỗi" | `family.py` — bắt buộc có cả `hits` VÀ `safe` (kèm lý do); `safe` rỗng là báo cáo không hợp lệ | `tests/test_family.py` |
| CLI | `cli.py` — `keeper run --dry-run` mặc định (chỉ đọc, in kế hoạch) | `tests/test_cli.py` |

Trạng thái lộ trình (BT1–BT8, `docs/DAC-TA-KEEPER.md`): BT1–BT7 đã merge (#210, #211, #213, #215, #217, #218,
#221/#239). **BT8 (canary): chờ người** — điều kiện là một chu kỳ thật trên chính X-Agents, keeper tự mở một PR
bảo trì và người merge nó (I1 cấm keeper tự merge); cần `gh auth login` trên máy thật trước.
