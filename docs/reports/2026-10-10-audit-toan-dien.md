# Audit toàn diện code và quy trình — 2026-10-10

Căn cứ `origin/main@8d40dd1` (#401), nhánh `claude/epic-hamilton-rvuuu7`. Audit lần trước cùng khuôn: 2026-09-27
(`docs/reports/2026-09-27-audit.md`). Phạm vi: cổng máy năm gói, săn lỗi im lặng trong mã nguồn (ba lượt đọc
song song: core + company, gateway + console, keeper), và quy trình (CI, ruleset, sổ sách, dependabot).

Nguyên tắc của báo cáo: mỗi phát hiện ghi rõ **đã tái hiện** hay **chỉ đọc**; chỉ cái đã tái hiện mới được vá, và
vá theo luật 4 (test đỏ trước). Phần còn lại ghi lý do chưa sửa và điều kiện quay lại — không "tiện tay" (luật cấm 7).

## 0. Kết luận một đoạn

Mã nguồn khoẻ ở bề mặt (cổng năm gói xanh, phủ 100%), nhưng có **bốn lỗi im lặng thật** cùng một khuôn đã ghi
trong `TRAPS.md`: (1) company — duyệt retry rồi agent lỗi lại cùng event thì không gate nào mở (khuôn 3, khoá
once thiếu thế hệ); (2) company — đăng ký khoá reviewer khi registry hỏng thì xoá sạch reviewer cũ; (3) console —
request bị chặn Host/Origin để lại thân chưa đọc trên keep-alive, thân thành request thứ hai và lộ token phiên;
(4) keeper — đẩy nhánh tự động chạy `pre-push` của repo khách. Cả bốn đã vá đo hai chiều. Quy trình: job
`protection-guard` chỉ so **loại** rule, không so tham số, nên #374 và #399 vào `main` bằng merge commit mà job vẫn
xanh — nay so cả `allowed_merge_methods`. Sổ sách: bảng "Việc để lại" của `TASK-PACK.md` vỡ (6 dòng rơi xuống
mục khác), một dòng CHANGELOG nằm trên header, `dependabot.yml` còn nói "sáu pyproject".

## 1. Cổng máy

| Gói | ruff | mypy | pytest | phủ |
|---|---|---|---|---|
| company | ✅ | ✅ (cả `--extra graph`) | 2053 passed, 1 skipped (251 s) | 100% dòng + nhánh |
| gateway | ✅ | ✅ | 312 passed | 100% dòng + nhánh |
| console | ✅ | ✅ | 727 passed (96 s) | 100% dòng + nhánh |
| core | ✅ | ✅ (strict) | 675 passed, 2 skipped | 100% dòng + nhánh |
| keeper | ✅ | ✅ | 830 passed | 100% dòng + nhánh |


Lệnh: `scripts/dev-task.sh gate all` sau khi vá. Lần 1 đỏ ở `ruff` (RUF043 trong test mới); lần 2 company và gateway
xanh, console đỏ vì stub `Ghi` của `test_es_module.py` thiếu `close_connection` và `log_error` mất phủ (xem §2); sửa rồi
chạy `gate console`, `gate core`, `gate keeper` riêng (company/gateway không đổi file sau lần 2).

## 2. Lỗi mã đã tái hiện và vá (4)

| # | Gói | Lỗi | Tái hiện | Vá | Test đỏ → xanh |
|---|---|---|---|---|---|
| 1 | company | `_mark_unhandled` khoá once `unhandled:{event_id}:{agent}` không thế hệ; `_retry_unhandled` phát lại **cùng** event_id nên lỗi lần hai bị `escalate_gate` nuốt: `unhandled` ghi, audit ghi, `gate.pending == {}`, `status` xanh | `_flaky_lead(2)` + duyệt một lần: `gate.pending == {}` | `unhandled_count` (Counter, dựng lại từ `agent_error_unhandled`), khoá mang `n` như `_stall` | `test_retry_unhandled.py::test_loi_lan_hai_sau_khi_duyet_van_mo_gate_moi` |
| 2 | company | `gate_reviewer.new_key` nuốt `OSError, ValueError` khi đọc registry rồi **ghi đè** bằng registry chỉ có khoá mới | registry `['reviewer:a']` hỏng một ký tự → sau `new_key("reviewer:b")` còn `['reviewer:b']` | chỉ `FileNotFoundError` mới là "chưa có"; hỏng/không phải object → `ValueError`, không sinh khoá, không ghi | `test_gate_reviewer.py::test_new_key_khong_ghi_de_registry_hong` (2 ca) |
| 3 | console | `_guard` trả 404/403 rồi `return` khi thân POST chưa đọc; `protocol_version = "HTTP/1.1"` giữ keep-alive nên thân được đọc thành request thứ hai, không qua `_guard` với header thật | nhồi `GET /` vào thân POST `Host: evil` → 2 phản hồi, phản hồi hai mang token phiên | `_error` đặt `close_connection = True`, `_send` kèm `Connection: close` — phủ mọi nhánh lỗi trả trước khi đọc thân (401, 403, 404 của `do_POST`) | `test_server.py::test_request_bi_chan_thi_dong_ket_noi_khong_doc_tiep_than` |
| 4 | keeper | `push_branch` gọi `subprocess.run` không mang `NO_HOOKS` trong khi `_git` của worktree luôn mang — `pre-push` của repo khách chạy trong lần đẩy không ai xem | hook `pre-push` ghi dấu vết + `exit 1` → push đỏ, dấu vết có | `*NO_HOOKS` trong argv push | `test_publish.py::test_push_branch_khong_chay_hook_pre_push` |

Rà cả họ (luật bắt buộc 5):

- Khoá once của supervisor trong `src/company/orch/`: `stall:{event_id}:{n}` ✅ thế hệ; `unhandled:…:{n}` ✅ (vá
  này); `plan_rejected:{event_id}` và `spec_runtime:{event_id}` **không thế hệ nhưng an toàn** — cả hai tự
  `request_gate` khi subject chưa pending (đo lại: từ chối kế hoạch lần hai sau duyệt vẫn có gate `P1`);
  `integration.failed:{tid}:{before}:{error}` mang `before` (sha nhánh) làm thế hệ; `review.escalate:{key}` và
  `gate:{sid}` của scheduler đã rà ở #127. Ghi vào `TRAPS.md` §1 khuôn 3.
- Mọi nhánh lỗi của console đi qua `_error` → một chỗ đóng kết nối là đủ; `_api_stream` đã tự `Connection: close`.
  Phủ 100% của console lộ một chỗ phủ *tình cờ*: `log_error` trước đây chỉ chạy nhờ thân request bị chặn được đọc
  thành request sai cú pháp (400); nay thêm `test_dong_request_sai_cu_phap_tra_400_khong_dut_ket_noi` phủ thật.
- Keeper: `_git` (worktree) ✅ `NO_HOOKS` + `git_env()`; `push_branch` ✅ `git_env()` + `NO_HOOKS` (vá này);
  `create_pr` chạy `gh` với `clean_env()` — `gh` không chạy hook git. `evidence.run_command` dùng `clean_env()` cho
  lệnh đo (pytest, `git stash`): xem §3 mục K7.

## 3. Phát hiện chỉ đọc, chưa sửa (13) — lý do và điều kiện quay lại

Company / core (lượt đọc 1; **chưa quét**: core `context.py`/`observe.py`/`tools.py`/`llm.py`, company `web.py`,
`metrics.py`, `trace.py`, `supply_chain.py`, `github_pr.py`, `orch/rehydrate.py`, `orch/release_fsm.py`):

| Mã | Mức | Ở đâu | Lỗi | Vì sao chưa sửa |
|---|---|---|---|---|
| C3 | trung bình | `company/deploy.py` teardown | mã trả về của lệnh `down` bị bỏ, `DeployRecord` không có chỗ ghi lỗi teardown | cần quyết định kiến trúc nhỏ (trường mới trong record + audit); mọi test stub `down` = `(0,"","")` nên vá cần fixture thật. Quay lại khi deploy thật gặp "port in use" sau teardown |
| C4 | thấp | `company/gate_brief.py:590` | `diagnose` ném → `None`, người duyệt không phân biệt "không có vòng lặp" với "chẩn đoán hỏng" | thêm vào danh sách `unavailable` của brief là vá đúng; chưa làm vì chạm hợp đồng `API.md` của console (hồ sơ brief) |
| C5 | thấp | `company/stacks.py` | `package.json`/`pyproject.toml` hỏng đọc thành "không có lệnh test" | test hiện pin đúng fallback này; đổi thông điệp là đổi hợp đồng với agent |
| C6 | thấp, chưa tái hiện | `xagents_core/sqlite_bus.py poll` | `_seq` tiến trước `model_validate_json`; hàng hỏng bị bỏ qua vĩnh viễn trên instance đó | chưa có kịch bản thật ghi được hàng hỏng vào bus (schema kiểm lúc publish) |
| C7 | thấp, chưa xác minh | `company/quality_floor.py project_bar` | bản ghi `quality.bar_set` của người không parse được bị bỏ, sàn rơi về mặc định | chỉ đọc, chưa dựng repro |

Gateway / console (lượt đọc 2):

| Mã | Mức | Ở đâu | Lỗi | Vì sao chưa sửa |
|---|---|---|---|---|
| G2 | thấp | `console/server.py _serve_index` | token trả cho mọi client loopback qua `GET /` → file token 0600 không chắn được user OS khác | cố ý theo ADR console 0001 và `SECURITY.md` (máy là ranh giới); việc còn lại là câu chữ trong docstring/`__main__.py` nói quyền 0600 bảo vệ gì |
| G3 | thấp | gateway `server.py:50`, `manage.py:171`; console `engine.py:189` | file log tạo theo umask mặc định (0644) trong khi token 0600 | máy nhiều user ngoài phạm vi `SECURITY.md`; quay lại nếu chạy trên máy dùng chung |
| G4 | thấp | `console/server.py:560`, `engine.py:195` | `by`/`reason` không giới hạn độ dài, không chặn `\r\n` → giả dòng log | `submit.py` đã có `MAX_ACTOR_LEN`; nên dùng chung cho decide/engine — việc nhỏ nhưng chạm ba route, để PR riêng |
| G5 | thấp | `console/server.py` | handler không có `timeout`, client im lặng giữ thread vô hạn | `/api/stream` phải miễn; cần đo trước với SSE thật |
| G6 | thấp | gateway `POST /auth/login` | không xác thực, gọi lặp chiếm cổng callback 300 s | cố ý theo ADR gateway 0003 §3; tuỳ chọn: khoá + 409 |

Keeper (lượt đọc 3; K8 = `push_branch` thiếu `NO_HOOKS`, đã vá ở §2 #4):

| Mã | Mức | Ở đâu | Lỗi | Vì sao chưa sửa |
|---|---|---|---|---|
| K1 | cao (nếu publish là bước có người) | `keeper/orchestrator.py publish` | không hỏi lại `pr_blockers()` (ngân sách I3 + gate) lúc publish, chỉ hỏi lúc `open_pr`; ticket khác mở PR ở giữa thì thành hai PR mở | thiết kế: ADR keeper ghi "ghi ý định rồi người chạy publish" — phải quyết **ở đâu** hỏi lại; chưa có bằng chứng xảy ra thật (canary mới một PR) |
| K2 | trung bình | `keeper/family.py` | `scan_family`/`grep_repo` không chỗ nào trong `src` gọi; "rà họ lỗi" là lời khai của patcher | là lỗ hổng luật 5 ở mức sản phẩm; cần ADR nhỏ: orchestrator chạy grep rồi so với `family_hits` |
| K3 | trung bình | `keeper/signals.py dedupe` | giữ bản ghi **cuối**, chỉ cộng `seen_count`; severity cao ở bản ghi trước bị hạ | cần quyết luật gộp (max severity?) — ảnh hưởng tier → gate |
| K4 | thiết kế | `keeper/budget.py weekly-quota` | đếm **mọi** PR merge của repo, không chỉ của keeper | tuỳ ý định I3; repo này merge nhiều PR người nên quota hết sớm |
| K5 | thấp-trung bình | `keeper/evidence.py` | pytest thoát 1 vì `fail_under` (1 passed) vẫn được tính là "đỏ trước" | đo được: `--cov` trên một file test luôn đỏ coverage; cần tách "test đỏ" khỏi "coverage đỏ" (đọc summary) |
| K6 | trung bình | `keeper/worktree.py refuse_shared_checkout` | nhận **mọi** worktree phụ, kể cả của phiên khác | thêm kiểm "worktree của đúng ticket/nhánh" — cần đổi chữ ký hàm |
| K7 | thấp | `keeper/evidence.py run_command` | lệnh đo (kể cả `git stash`) chạy với `clean_env()`, không bỏ `GIT_*` như `git_env()` | lệnh đo là lệnh tuỳ ý (pytest…), bỏ `GIT_*` là hợp lý nhưng chưa có ca thật; báo cáo lượt 3 nói `publish.py:72` cũng vậy — **sai**, dòng đó là `gh pr create`, `push_branch` đã dùng `git_env()` |
| K9 | thấp | `keeper/patcher.py bump_dependency` | regex thay version không neo vào dòng requirement, sửa cả văn xuôi nhắc tên gói | tái hiện được trong scratchpad; vá cần test với pyproject có comment — PR riêng, nhỏ |
| K10 | thấp | `keeper/cli.py _run` | coi `ticket.subject` là đường dẫn file; subject drift (`changelog-L12`, `sc-builder.md`) không phải đường dẫn | lỗi hiện ra là outcome chung, không phải "sai đích"; chờ K2/K3 định lại hợp đồng ticket |

Mã chết ở `keeper/risk.py` (`_PR_SUBJECT_RE`, `_is_doc`, hàng `docs-only-drift`) — câu hỏi để lại từ phiên trước:
**không producer nào chạm tới**. Sau khi bỏ phép (c) `changelog_drift` (#400), subject `pr-N` chỉ còn ở `health.py`
với `kind="health"` (hàng đòi `kind == "drift"`); `sc_agent_drift`/`golden_drift` có evidence `agents/…` nên dính
hàng `touches-agents-or-skills` trước; `changelog_placeholder_drift` có subject `changelog-LN` không phải doc. Hai test
đi tới `low` qua hàng này đều dựng tín hiệu tay (`test_risk.py:47`, `:99`). Chưa xoá (luật cấm 7); điều kiện xoá: một
test chạy output thật của ba producer qua `risk_tier` xác nhận high/high/medium, rồi PR riêng gỡ hàng + hai test tay.

Đã kiểm và **an toàn** (ghi để người sau khỏi rà lại): keeper `GitHubReader` chặn cờ ghi và trả `None` khi không
biết (budget fail-closed); I3 hỏi GitHub mỗi lần `open_pr`; bus replay dựng lại intent/verification; `SELF_CLAIM_FIELDS`
do orchestrator ghi đè; `require_two_way` ném khi before = 0 hoặc after ≠ 0; `FORBIDDEN_PATHS` có `.git/`,
`.github/`. Company: `once` của orchestrator dựng lại từ bus; `_retry_unhandled`/`_retry_stalled` ghi audit trước khi
xếp hàng; `HumanGate.request` ghi đè `pending` nhưng mọi caller đều `not in pending`.

## 4. Quy trình

| # | Phát hiện | Bằng chứng | Đã làm |
|---|---|---|---|
| Q1 | `protection-guard` so loại rule, không so tham số: `allowed_merge_methods` thật `["merge","squash"]` vs file `["squash"]` mà job xanh | #374, #399 vào `main` bằng merge commit; mô phỏng jq với `live-bad.json`/`live-ok.json` phân biệt được | ci.yml so `allowed_merge_methods` hai chiều; `test_cong_repo.py::test_protection_guard_so_ca_allowed_merge_methods` đỏ → xanh; `QUY-TRINH-GIT.md` §8 |
| Q2 | Ba PR dependabot (#396–#398) đỏ chỉ ở job `audit` (multidict CVE), lỗi có sẵn trên `main`, #399 đã vá | CI của từng PR | **chưa** cập nhật nhánh — merge là việc người; `gh`/MCP cập nhật nhánh được khi được bảo |
| Q3 | `TASK-PACK.md` bảng "Việc để lại" vỡ: 6 dòng rơi xuống sau "## Khi nào không cần gói việc", 12 dòng cho việc đã đóng ở #390–#395 | `grep -c '^| 2026-'` | gộp còn 2 dòng (BT8 đóng #395; S1/S2/O1/O3 đóng #392/#394/#390/#393 kèm phần vận hành còn lại) |
| Q4 | Dòng CHANGELOG của #395 nằm **trên** header | `CHANGELOG.md` dòng 1 | về đúng vị trí theo thời điểm merge |
| Q5 | `dependabot.yml` nói "sáu `pyproject.toml` con" — repo có năm thành viên + một gốc | | sửa câu |
| Q6 | README gốc khai số test thấp hơn thật sau khi thêm test (cổng `test_so_test_trong_readme_khop_dia` bắt được) | 2050→2054, 725→727, 829→830 | cập nhật cùng PR |

## 5. Việc để lại (xếp theo giá trị / chi phí)

1. **K1 + K2** (keeper publish hỏi lại blocker; orchestrator tự chạy `scan_family`) — hai lỗ hổng luật ở mức sản
   phẩm, cần ADR keeper mới trước khi code.
2. **K3 + K5** — luật gộp tín hiệu và tách "test đỏ" khỏi "coverage đỏ"; cả hai đổi tier/bằng chứng, nên đi cùng
   bản ghi eval mới.
3. **G4** (`MAX_ACTOR_LEN` + chặn `\r\n` cho `by`/`reason` ở decide/engine) và **K9** (neo regex `bump_dependency`) —
   nhỏ, mỗi cái một PR, test đỏ trước.
4. **C3** (teardown ghi lỗi) khi có deploy thật gặp lại; **C4** cùng lúc đổi hợp đồng brief.
5. Quét nốt các file lượt 1 chưa đọc (danh sách ở đầu §3).
