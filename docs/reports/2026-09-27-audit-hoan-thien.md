# Audit hoàn thiện — 2026-09-27

Căn cứ `origin/main@7eff008` (#365), nhánh `claude/project-audit-bwh88a` — phiên cloud, container riêng, clone nông
50 commit. Hai báo cáo cùng ngày đi trước: `docs/reports/2026-09-27-audit.md` (@220ffe0, #360) và
`docs/reports/2026-09-27-audit-hardening.md` (#365). Phạm vi: tám phép A1–A8 trên `main` mới nhất; săn lỗi ở các
lối quyết định của người (gate, change request); làm nốt việc treo **không cần người quyết và không cần model trả
phí**, mỗi việc một test đỏ đi trước.

## 0. Kết luận một đoạn

Cổng năm gói xanh, phủ 100%, không PR/issue mở. Lỗi thật tìm được nằm ở **lối quyết định của người**: ba lối
(`gate_cli`, console, `orchestrator decide-change`) nhận `by` là chữ tự do mà không kiểm đó là người, trong khi
`keeper gate` và `orchestrator publish` đã chốt đúng chỗ này. Hậu quả không phải vượt quyền gate (`_trusted` bỏ bản
ghi không phải người ở mọi tiến trình), mà là **thất bại im lặng**: lệnh báo "đã duyệt" trong khi gate vẫn chờ —
và riêng `decide-change` thì bản ghi dưới tên agent **được** hành động theo. Việc hoàn thiện làm được ngay: bật phủ
nhánh cho hai gói cuối (gateway, console) và sửa lỗ đếm của sổ `TRAN_SKIP`.

## 1. Cổng máy — mốc trên `main@7eff008`

| Gói | ruff | mypy | pytest | phủ |
|---|---|---|---|---|
| company | ✅ | ✅ 65 file | 1980 passed | 100% dòng + nhánh |
| gateway | ✅ | ✅ 6 file | 274 passed | 100% dòng |
| console | ✅ | ✅ 12 file | 514 passed | 100% dòng |
| core | ✅ | ✅ 22 file | 594 passed | 100% dòng + nhánh |
| keeper | ✅ | ✅ 29 file | 582 passed | 100% dòng + nhánh |

Lệnh: `PYTEST_XDIST_AUTO_NUM_WORKERS=4 scripts/dev-task.sh gate all` → `cổng XANH`, EXIT=0 (3944 pass, 0 skip trên
Linux). PR mở: không có.

## 2. Tám phép A1–A8

| Phép | Claim | Đo được | Chênh | Lệnh |
|---|---|---|---|---|
| A1 | README gốc: 6 agent · 45 skill · 19 topic · 14 template · ADR company 0001–0047 · 10 subagent; company 1980 / gateway 274 / core 594 test | khớp | 0 (có cổng) | `find`, `ls`, `pytest --collect-only` |
| A2 | `platform/gateway/README.md:195` "274 ca (271 chạy, 3 skip quyền file POSIX trên Windows)" | 274; trên Windows 3 skip = 2 `chmod` POSIX + 1 `/proc` chỉ có trên Linux | lệch chữ (1/3 skip không phải quyền file) | `grep skipif platform/gateway/tests` |
| A3 | `xagents_core/observe.py:15` "cả sáu package" | 5 thành viên workspace | **lệch** | `[tool.uv.workspace] members` |
| A3 | `platform/gateway/README.md:200` "cùng cấu trúc với ba package kia" | bốn package kia | **lệch** | như trên |
| A3 | `CONTRIBUTING.md:61` "không package nào bật `branch = true`" | ba gói đã bật từ 2026-09-10 → 13 | **lệch** | `grep -n "branch = true" */*/pyproject.toml` |
| A3 | `xagents_core/__init__.py:3` "Ở K3.0 package này còn rỗng có chủ ý" | K3 xong ở #198 | lệch nhẹ (chép lịch sử, không nói đã xong) | đọc file |
| A3 | `docs/TASK-PACK.md` sổ "Việc để lại", dòng 2026-09-27: B5, B6, B7 còn treo | đã đóng ở #363 (B6.2, B6.4 cố ý giữ) | **lệch** | `docs/sessions/2026-09-27.md` mục #363 |
| A4 | ADR gốc 0024 §bảng lối: mọi lối chỉ-của-người vẫn đóng với reviewer | `gate_cli`, console, `decide-change` nhận `by` bất kỳ | **lệch** — F-A | probe, mục 3 |
| A5 | sổ `TRAN_SKIP` console = 1 | 3 điều kiện skip: `pytestmark = pytest.mark.skipif(...)` (`test_cong_khung.py:77`), `POSIX_ONLY = pytest.mark.skipif(...)` (`test_server.py:384`, dùng 2 lần), `pytest.skip(...)` (`test_static_ui.py:105`) | **lỗ đếm** — regex chỉ bắt `@pytest.mark.skip*` và `pytest.skip(` | F-C, mục 3 |
| A5 | lý do của `pragma`/`omit`/skip còn lại | khớp sổ, lý do còn đúng (skip đều theo nền tảng) | 0 | lệnh A5 của task pack |
| A6 | phủ nhánh | company/core/keeper `branch = true`; gateway 98,80% nhánh (27 nhánh thiếu), console 99,45% (13) | nợ còn 2 gói → làm trong PR này | `pytest --cov --cov-branch` |
| A7 | bản ghi eval | company: builder/qa 2026-09-07, security 09-09, supervisor 09-12, product 09-13, ops 09-14; keeper 4/10 agent, 2026-09-09 | 13–20 ngày; `make eval-record` cần model thật | `recorded_at` trong `evals/recordings/*.json` (clone nông, `git log` không tới) |
| A8 | job CI ↔ `needs` của `quality` | 17 job, cả 17 trong `needs` | 0 | so `ci.yml` |

## 3. Phát hiện

### F-A — lối quyết định của người nhận `by` không phải người

Dò bằng probe trên bus tạm trước khi sửa:

| Lối | `by` | Kết quả trước khi sửa |
|---|---|---|
| console → gate company | `reviewer:x`, `orchestrator` | trả `ok` + `event_id`; gate vẫn chờ ở mọi lần replay (kể cả `collect` của chính console) |
| console → gate company | `qa`, `builder` | `PermissionDenied` của bus — không phải `PermissionError` ⇒ HTTP 500 "lỗi không lường trước" |
| console → gate keeper | `owner`, `reviewer:x`, `orchestrator`, `patcher` | trả `ok`; gate vẫn chờ (bus keeper không có ACL cho `gate.decide`) |
| `gate_cli approve` | `reviewer:x`, `orchestrator` | in "approve …", thoát 0; gate vẫn chờ |
| `gate_cli approve` | `pm` | traceback `PermissionDenied` |
| `orchestrator decide-change` | `ops` (chủ topic `change-requests`) | thoát 0; quyết định **của khách** ghi dưới tên agent, `_cr_accepted_*` chỉ đọc `decision` nên kế hoạch mới chạy tiếp |
| `orchestrator decide-change` | `pm`, `reviewer:x` | traceback `PermissionDenied` |

Gốc: `trusted_decision` (core) chỉ tin bản ghi có `env.actor` là người và bằng `by` (hoặc `orchestrator` đóng
`UAT-*`); `_trusted` của company thêm `code` (ADR-0043) và `reviewer:*` có chữ ký (ADR gốc 0024). Lối của người
không kiểm trước, nên bản ghi hoặc bị ACL chặn bằng traceback, hoặc lọt ACL rồi bị bỏ ở bước replay — đúng khuôn
thất bại im lặng mà `keeper/cli.py::_gate` đã ghi và đã chốt. `orchestrator publish` cũng đã chốt ("giả danh
agent/orchestrator từ đây là vượt quyền producer của bus"); `decide-change` ngay dưới nó thì chưa.

Sửa: `is_human(by)` ở `gate_cli.main` (trước `_pin_profile`, bước đầu có ghi đĩa), `console/decide.py::decide`
(`ValueError` ⇒ HTTP 400, trước khi mở bus) và `orch/cli_cmds.py::decide_change`. Reviewer có chữ ký vẫn đi
`python -m company.gate_reviewer decide`. Hệ quả chấp nhận: `gate_cli`/console không còn đóng gate UAT bằng một
`by` chữ tự do không phải người — không tài liệu hay test nào dùng lối đó; UAT đóng bằng chữ ký khách qua
`acceptance-results` (`gates/checklists.md`). Lõi `PersistentGate.decide(actor=None)` giữ nguyên.

Đo hai chiều: 12 ca đỏ trước khi sửa (company 3 + 3, console 6: "DID NOT RAISE" / `assert 0 == 3` /
`PermissionDenied`), xanh sau. Hai test four-eyes cũ dùng tên agent làm người duyệt được dựng lại bằng gate do
người mở, để four-eyes vẫn được đi qua thật.

Rà cả họ (luật bắt buộc 5) — câu hỏi: *lối nào ghi quyết định thay người mà không kiểm `is_human`?*

| Chỗ | Trạng thái |
|---|---|
| `keeper gate` (`keeper/cli.py::_gate`) | an toàn — đã chốt, thoát 3 |
| `orchestrator publish` | an toàn — đã chốt, thoát 2 |
| `orchestrator comment` / `takeover` / `redeploy` | an toàn — `ValueError` "by phải là human:<tên>" |
| `orchestrator recheck` | an toàn — nhận `human:` hoặc `reviewer:` có chủ đích (ADR-0047) |
| `gate_risk.request_gate` | an toàn — chỉ quyết khi cờ bật, `actor=code` tường minh |
| `orch/gates_flow.py` đóng UAT | an toàn — `actor=orchestrator` tường minh, từ chữ ký khách |
| `gate_reviewer decide` | an toàn — tự kiểm chữ ký + trust trước khi ghi |
| console `submit` | an toàn — bắt `BusError`, schema của công ty |
| `gate_cli` / console decide / `decide-change` | **sửa trong PR này** |

### F-B — `gate_reviewer decide` để lại bus rỗng ở sai đường dẫn

`--db` trỏ file chưa có ⇒ `SQLiteBus(ns.db)` tạo `company.sqlite` 20 KB rỗng rồi mới từ chối (thoát 1). Cùng họ B3
của #362 (`missing_bus` ở `gate_cli`/`orch/cli.py`), sót ở CLI thứ ba. Sửa: kiểm `missing_bus` trước khi mở bus,
thoát 2. Đỏ trước khi sửa: `assert 1 == 2`. Rà họ: `runner.main` cũng tạo bus ở đường dẫn chưa có — công cụ dev
ghi output nên để nguyên; `trace`/`gate_brief` mở `open_read_only`; `quality_execution` kiểm `is_file`.

### F-C — sổ `TRAN_SKIP` không đếm marker skip gán vào biến

`_SKIP = (?:@pytest\.mark\.|pytest\.)(?:skip|xfail)` chỉ bắt decorator viết thẳng và lời gọi `pytest.skip(`.
`pytestmark = pytest.mark.skipif(...)` bỏ qua **cả một module** mà sổ không đếm; marker gán biến rồi dùng lại
(`@POSIX_ONLY`) cũng vậy. Hôm nay cả hai đều hợp lệ (skip theo nền tảng), nhưng sổ sinh ra để thêm lối thoát là
phải đi qua review — lỗ này cho thêm một lối thoát mà cổng không đỏ.

## 4. Việc để lại

| Việc | Vì sao chưa làm ở đây |
|---|---|
| A7: ghi lại bản ghi eval (company 13–20 ngày; keeper 6/10 agent chưa có bộ ca) | `make eval-record` cần model thật (luật cấm 4 và CONTRIBUTING §3) |
| B2, B4, S2, O1–O4 và A3.1–A3.5 của `docs/reports/2026-09-27-audit.md` | cần đo trên bus vận hành thật hoặc người quyết (ADR/`agents/`) |
| ADR Proposed mà mã đã merge (gốc 0019, 0026; company 0045) | đổi trạng thái ADR là quyết định của người |
