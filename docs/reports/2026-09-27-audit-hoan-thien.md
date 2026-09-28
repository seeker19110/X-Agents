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
và riêng `decide-change` thì bản ghi dưới tên agent **được** hành động theo. Phần hoàn thiện làm trong cùng PR: cả
năm gói nay phủ 100% dòng **và** nhánh (gateway thêm 27 nhánh, console 13) — và chính việc phủ nhánh console lộ thêm
một lỗi thật (F-D: tắt backend đang được ưu tiên thì lời trả về nói đã bỏ ưu tiên, nhưng `llm.yaml` vẫn giữ
`routing.prefer` trỏ vào nó); hai sổ lối thoát `TRAN_SKIP`/`TRAN_PRAGMA` đếm đủ các dạng viết (F-C).

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
| A2 | `platform/gateway/README.md:195` "274 ca (271 chạy, 3 skip quyền file POSIX trên Windows)" | 274; trên Windows 3 skip = 2 `chmod` POSIX + 1 `/proc` chỉ có trên Linux | lệch chữ (1/3 skip không phải quyền file) → **đã sửa** (nay 297 ca, ghi đúng hai loại skip) | `grep skipif platform/gateway/tests` |
| A3 | `xagents_core/observe.py:15` "cả sáu package" | 5 thành viên workspace | **lệch** → đã sửa ("mọi package") | `[tool.uv.workspace] members` |
| A3 | `platform/gateway/README.md:200` "cùng cấu trúc với ba package kia" | bốn package kia | **lệch** → đã sửa | như trên |
| A3 | `CONTRIBUTING.md:61` "không package nào bật `branch = true`" | ba gói đã bật từ 2026-09-10 → 13 | **lệch** → đã sửa (nay cả năm gói bật) | `grep -n "branch = true" */*/pyproject.toml` |
| A3 | `xagents_core/__init__.py:3` "Ở K3.0 package này còn rỗng có chủ ý" | K3 xong ở #198 | lệch nhẹ (chép lịch sử, không nói đã xong) → để lại, mục 4 | đọc file |
| A3 | `docs/TASK-PACK.md` sổ "Việc để lại", dòng 2026-09-27: B5, B6, B7 còn treo | đã đóng ở #363 (B6.2, B6.4 cố ý giữ) | **lệch** → đã sửa (`0ad8aaa`) | `docs/sessions/2026-09-27.md` mục #363 |
| A4 | ADR gốc 0024 §bảng lối: mọi lối chỉ-của-người vẫn đóng với reviewer | `gate_cli`, console, `decide-change` nhận `by` bất kỳ | **lệch** — F-A | probe, mục 3 |
| A5 | sổ `TRAN_SKIP` console = 1 | 3 điều kiện skip: `pytestmark = pytest.mark.skipif(...)` (`test_cong_khung.py:77`), `POSIX_ONLY = pytest.mark.skipif(...)` (`test_server.py:384`, dùng 2 lần), `pytest.skip(...)` (`test_static_ui.py:105`) | **lỗ đếm** — regex chỉ bắt `@pytest.mark.skip*` và `pytest.skip(` → đã sửa | F-C, mục 3 |
| A5 | lý do của `pragma`/`omit`/skip còn lại | khớp sổ, lý do còn đúng (skip đều theo nền tảng) | 0 | lệnh A5 của task pack |
| A6 | phủ nhánh | company/core/keeper `branch = true`; bật đo nhánh thì tổng phủ gateway 98,80% (27 nhánh thiếu), console 99,45% (13) | nợ còn 2 gói → **đã đóng**: cả năm gói 100% dòng + nhánh, sổ `CHUA_PHU_NHANH` rỗng — F-E | `pytest --cov --cov-branch` |
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
phải đi qua review — lỗ này cho thêm một lối thoát mà cổng không đỏ. Cùng họ: `# pragma: no branch` không vào sổ
nào — khi cả năm gói đo nhánh, nó là lối thoát ngang hàng với `no cover`.

Sửa (`platform/console/tests/test_cong_repo.py`): `_SKIP` bắt `pytest.mark.skipif|skip|xfail` ở mọi dạng viết và
`pytest.skip(`/`pytest.xfail(`/`pytest.importorskip(`; marker gán vào biến thì đếm **chỗ dùng** (`@TEN`, mỗi chỗ bỏ
một ca) thay cho chỗ gán; riêng `pytestmark` đếm một, vì chính phép gán bỏ cả module. `TRAN_PRAGMA` đếm chung
`no branch` với `no cover`. Sổ đổi theo số thật: console skip 1 → 4, company pragma 10 → 13 (ba `no branch` có
sẵn ở `mcp_bridge.py:181/183`, `llm.py:497`, mỗi chỗ có lời đo tracer ngay trên dòng). Đỏ trước khi sửa: ghi số
thật vào sổ khi bộ đếm còn cũ ⇒ `đếm được 10 … sổ ghi 13`, `đếm được 1 … sổ ghi 4`; test của chính bộ đếm
(`test_bo_dem_loi_thoat_bat_du_cac_dang_viet`: sáu dạng skip, hai dạng pragma) đỏ `NameError`. Xanh sau khi sửa.
Trần đã biết, ghi bằng marker `no-ky-thuat` tại chỗ: chỉ đếm `@TEN` trong cùng file với phép gán — marker skip
dùng chung qua `conftest`/import thì chưa đếm.

### F-D — tắt backend đang được ưu tiên: `llm.yaml` vẫn giữ `routing.prefer` trỏ vào nó

Lộ ra khi phủ nhánh console (nhánh 215->217 của `console/settings.py::update_settings`). Hàm sửa một **bản sao**
của khoá `routing` (`settings.py:187`) rồi chỉ gán lại khi bản sao còn khác rỗng (`if routing: data["routing"] =
routing`). Tắt backend `b` khi `routing` chỉ có `prefer: {standard: b}` ⇒ bản sao rỗng ⇒ không gán ⇒ file ghi ra
vẫn còn `routing.prefer.standard: b`, trong khi lời trả về báo `bỏ ưu tiên standard (backend đã tắt)`. Người trực
tin là đã bỏ; lần đọc sau (`read_settings`, router của công ty) vẫn thấy ưu tiên trỏ vào backend đã tắt.

Đỏ trước khi sửa: `assert 'prefer' not in {'prefer': {'standard': 'b'}}`. Sửa: bản sao rỗng thì
`data.pop("routing", None)`. Xanh sau khi sửa; đột biến bỏ nhánh `else` ⇒ đỏ lại (bảng đột biến ở F-E).

Rà cả họ (luật bắt buộc 5) — câu hỏi: *chỗ nào sửa BẢN SAO của một khoá con rồi chỉ gán lại khi bản sao khác rỗng?*

| Chỗ | Trạng thái |
|---|---|
| `console/settings.py:187` `update_settings` — `routing` | **sửa trong PR này** |
| `console/settings.py` — `disabled_backends`, `routing.prefer` | an toàn — đã có nhánh `else` gỡ khoá khi rỗng |
| `console/truth.py:419` | an toàn — chỉ đọc để hiển thị |
| `xagents_core/evals.py:213` | an toàn — luôn gán lại |
| `gateway/manage.py:319` `cmd_setup` — `models` | an toàn — gán lại vô điều kiện (dòng 322) |
| `xagents_core/llm.py:357/367` | an toàn — chỉ nạp cấu hình, không ghi file |
| `gateway/client.py:423`, `xagents_core/trace.py:70` | an toàn — dữ liệu trong bộ nhớ, không ghi lại |

### F-E — phủ nhánh cho hai gói cuối (A6 đóng)

Mốc khi bật đo nhánh (`--cov-branch`): tổng phủ gateway 98,80% (27 nhánh thiếu: `auth` 4, `client` 15, `manage` 7,
`server` 1), console 99,45% (13: `collect` 6, `settings` 5, `__main__` 1, `server` 1). Mỗi nhánh một test tả
**hành vi** của nhánh ấy, trừ ba chỗ đổi cấu trúc thay cho `# pragma: no branch` (tiền lệ company #279/#280):

- `gateway/auth.py::_atomic_write`: vòng thử `os.replace` luôn thoát bằng `break`/`raise` nên arc `->exit` không bao
  giờ tới. Viết lại: `REPLACE_ATTEMPTS - 1` lần thử trong vòng, lần cuối ngoài vòng (lỗi đi ra `except` dọn file tạm
  như cũ). Hành vi giữ nguyên — các test thử lại/bỏ cuộc có sẵn vẫn xanh.
- `_utf8_stdio` (gateway `manage.py`, console `__main__.py`): tách vòng `reconfigure` khỏi `main()` để test bằng
  stream giả truyền vào — thay `sys.stdout` toàn cục làm lệch chính phép đo phủ. Đỏ trước: `AttributeError`.
- `console/settings.py::_atomic_write`: `if path.exists()` rồi `if mode is not None` bên trong là một điều kiện
  viết hai lần (`mode` là `None` đúng khi chưa có file) — gộp làm một, nhánh không tới được biến mất.

Hai nhánh phòng thủ của `client.translate_gemini_to_openai_response` (bộ trích lời gọi tool từ văn bản trả rỗng;
`arguments` rỗng khi `as_content`) không tới được bằng đầu vào thật với mã hiện tại — test bơm hàm giả và ghi lý do
ngay trên test. CI chạy cả `windows-latest`: mô phỏng Windows chỉ trong module của gateway (đổi `os.name` toàn cục
làm vỡ pathlib của chính pytest) tìm thêm arc `manage.py` 162->164 — trên Windows mọi test spawn đều đi nhánh
`win32` thật — nên thêm test ép nhánh POSIX. Đo phủ trên ba biến thể 3.11, 3.13, mô phỏng Windows: cả ba 100%.

Chiều ngược (tắt hành vi của nhánh ⇒ test đỏ) đo bằng đột biến từng nhánh, mỗi ca một thư mục pycache mới. Lần chạy
đầu vấp đúng `TRAPS.md:133`: hai đột biến cùng kích thước file ghi trong cùng một giây, `.pyc` của đột biến trước
được dùng lại, một ca báo xanh giả.

| Gói | Đột biến | Đỏ | Sống — vì sao tương đương |
|---|---|---|---|
| gateway | 27 (26 nhánh mốc, trừ `236->exit` đã viết lại; cộng `162->164`) | 25 | `client.py:604` `if text:` — `joined_system` đã lọc chuỗi rỗng; `_utf8_stdio` `if reconfigure is not None` — gọi `None` ném `TypeError`, bị `suppress(Exception)` nuốt |
| console | 12 (13 nhánh; `115`/`117` gộp một điều kiện) | 10 | `collect._routing_status` `if not cfg.backends: continue` — `RoutingClient([])` ném `LLMError`, bị `except` ngay dưới bắt; `_utf8_stdio` — như gateway |

Bốn chỗ sống là lớp phòng thủ thừa (bỏ đi không đổi hành vi quan sát được): ghi ở đây, không xoá (luật cấm 7). Ba
test gateway được siết sau lượt đột biến đầu vì đầu vào cũ không phân biệt được: chữ ký thật thắng `extra_content`;
`tool_calls` là một số (không lặp được); message rỗng nằm giữa hai lượt user.

Kết quả: sổ `CHUA_PHU_NHANH` rỗng, cả năm gói `branch = true`; gateway 274 → 297 test, console 514 → 532.

## 4. Việc để lại

| Việc | Vì sao chưa làm ở đây |
|---|---|
| A7: ghi lại bản ghi eval (company 13–20 ngày; keeper 6/10 agent chưa có bộ ca) | `make eval-record` cần model thật (luật cấm 4 và CONTRIBUTING §3) |
| B2, B4, S2, O1–O4 và A3.1–A3.5 của `docs/reports/2026-09-27-audit.md` | cần đo trên bus vận hành thật hoặc người quyết (ADR/`agents/`) |
| ADR Proposed mà mã đã merge (gốc 0019, 0026; company 0045) | đổi trạng thái ADR là quyết định của người |
| `xagents_core/__init__.py:3` còn tả K3.0 ("còn rỗng có chủ ý", nhắc `studio` đã gỡ) | docstring của gói lõi, không có cổng canh; nên viết lại cùng lần chạm lõi kế tiếp thay vì một PR riêng |
| Marker skip dùng chung qua `conftest`/import chưa được `TRAN_SKIP` đếm | trần ghi bằng `no-ky-thuat` ở `test_cong_repo.py`; hôm nay không có chỗ nào dùng kiểu đó |
| Bốn lớp phòng thủ thừa lộ ra qua đột biến (F-E) | không phải lỗi; xoá hay giữ là chuyện phong cách, luật cấm 7 |
| `gateway/tests/test_account_pool.py::test_atomic_write_takes_posix_chmod_branch` (có từ trước) đổi `os.name` **toàn cục** thành `posix` — cùng họ với test Windows đã viết lại ở F-E | trên Linux là phép gán không đổi gì; trên Windows chỉ vỡ báo cáo khi chính test đỏ (pathlib của pytest, như ca đã gặp ở F-E) — chưa đo trên Windows thật; code cạnh bên, luật cấm 7 |
