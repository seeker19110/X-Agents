# Audit, nâng cấp, tối ưu — 2026-10-10 (lượt hai)

Căn cứ `origin/main@1220e59` (#403, audit toàn diện cùng ngày), nhánh `claude/wizardly-feynman-smgz3t`. Lượt này làm
ba việc mà #403 để lại hoặc chưa đo: **nâng phụ thuộc** (5 PR dependabot đang kẹt), **audit nốt** 11 file lượt đọc 1
chưa quét cùng G4/K9 của bảng §3 #403, và **tối ưu** thời gian cổng theo số đo — không theo cảm giác.

Nguyên tắc giữ nguyên của #403: chỉ vá cái đã tái hiện, vá theo luật 4 (test đỏ trước, đo hai chiều); phần còn lại
ghi lý do chưa sửa (luật cấm 7).

## 0. Kết luận một đoạn

`uv lock --upgrade` nâng 32 gói, phủ cả năm PR dependabot đang mở (#397, #398, #404, #405, #406 — mỗi bản trong lock
bằng hoặc mới hơn bản PR đề xuất); cổng năm gói xanh **không phải sửa dòng mã nào** cho ruff 0.17 / mypy 2.4 /
pydantic 2.14, `pip-audit --strict` sạch. Audit nốt tìm ra **một họ lỗi trải ba gói**: hàm bọc subprocess hứa "không
ném"/"trả `(ok, lý do)`" nhưng chỉ bắt `FileNotFoundError`, nên binary **có trên máy mà không chạy được** (thiếu
quyền thực thi, không phải binary) thoát ra thành `OSError` thô — sáu chỗ, vá cả sáu; cộng K9 (keeper sửa cả văn
xuôi khi bump phụ thuộc), G4 (danh tính `by`/`actor` không trần, xuống dòng giả được dòng log) và nhãn Prometheus
không thoát. Tối ưu: **cổng company cục bộ chạy bộ test chậm gần gấp đôi CI** vì bước mypy `--extra graph` để lại
`langsmith` trong `.venv` chung và plugin pytest của nó nạp ở mọi pytest con của test e2e (pytest company 370 s →
207 s khi `.venv` khớp CI); thêm hai test ngủ thật 30 s và 10 s.

## 1. Cổng máy

| Gói | Lần đo đầu (lock cũ, cây đang vá) | Sau nâng lock, trước tối ưu | Cuối (nhánh này) |
|---|---|---|---|
| company | 450 s (đỏ phủ — file sửa giữa lúc chạy, không phải lỗi `main`) | ✅ 2057 passed, 1 skipped — 447 s | ✅ 2057 passed, 1 skipped — **267 s** (pytest `--cov` 260 s) |
| gateway | ✅ 38 s | ✅ 312 passed — 26 s | ✅ 312 passed — 17 s |
| console | 134 s (đỏ: README số test lệch sau khi thêm test) | ✅ 739 passed — 127 s | ✅ 744 passed — 117 s |
| core | ✅ 26 s | ✅ 676 passed, 2 skipped — 23 s | ✅ 676 passed, 2 skipped — 28 s |
| keeper | ✅ 74 s | ✅ 835 passed — 64 s | ✅ 835 passed — 56 s |

Mọi ô ✅ là `scripts/dev-task.sh gate <gói>` (ruff → mypy, company thêm `--extra graph` → pytest `--cov`, phủ 100%
dòng + nhánh). `uvx pip-audit --strict` trên `uv export --no-dev --all-packages` (đúng lệnh job `audit`): **No known
vulnerabilities found**. Cột "Cuối" chạy tuần tự năm gói trên cùng máy (4 lõi), `.venv` khớp `uv sync --locked` và
mypy lần hai đã `--isolated`: cổng company 447 s → 267 s (§5a, §5b). Chênh vài giây ở các gói khác là nhiễu của máy,
không phải do nhánh này.

## 2. Nâng phụ thuộc — 32 gói, không gói nào thêm/bớt

Đáng kể: `anthropic` 1.8.0 → 1.13.0, `langchain-core` 1.6.1 → 1.6.9, `langgraph` 1.2.12 → 1.2.14, `langsmith` 0.12.1 →
0.14.7, `pydantic` 2.13.5 → 2.14.0 (`pydantic-core` 2.46.5 → 2.50.0), `mypy` 2.3.1 → 2.4.0, `ruff` 0.16.9 → 0.17.0,
`cryptography` 50.0.1 → 50.0.2, `aiohttp` 3.14.3 → 3.14.4, `coverage` 7.16.0 → 7.16.2. Danh sách đủ: `git diff
origin/main -- uv.lock`.

- **Phủ năm PR dependabot**: #397 (anthropic → 1.11.0; lock có 1.13.0), #398 (cryptography 50.0.2), #404 (aiohttp
  3.14.4), #405 (langgraph 1.2.14), #406 (nhóm dev: mypy 2.4.0, ruff → 0.16.10 — lock có 0.17.0, types-jsonschema
  20261006). Merge PR này thì dependabot tự đóng năm PR kia (bản trên `main` đã ≥ bản đề xuất).
- **Vì sao gộp thay vì merge từng PR**: `open-pull-requests-limit: 5` đã đầy nên dependabot **không mở thêm** PR nào
  — bản nâng mới hơn (ruff 0.17, pydantic 2.14…) bị chặn sau năm PR cũ; mỗi PR lại tốn một vòng CI ~32 job. #397/#398
  còn đỏ ở job `audit` vì nhánh của chúng chưa có bản vá multidict của #399.
- **Rủi ro biết trước**: vài bản ra 2026-10-08/09 (anthropic 1.13.0, ruff 0.17.0, pydantic 2.14.0, langsmith 0.14.7)
  — dưới hai ngày tuổi lúc nâng. Repo không có chính sách cooldown (`[tool.uv]` không `exclude-newer`, dependabot
  không `cooldown`); cổng năm gói + `pip-audit` xanh là bằng chứng đủ cho repo này, không thêm chính sách mới ở đây.
- **Đề xuất, chưa làm**: nhóm cả phụ thuộc runtime trong `dependabot.yml` (hiện chỉ nhóm `dev`) để một tuần là một
  PR — giới hạn 5 không còn kẹt. Đổi nhịp cập nhật bảo mật là quyết định của chủ repo.

## 3. Lỗi mã đã tái hiện và vá

### 3a. Họ `OSError`: "có trên máy mà không chạy được" (6 chỗ, 3 gói)

Câu hỏi kiểm tra rút từ lỗi (luật bắt buộc 5): *hàm bọc subprocess nào hứa không ném / trả lý do đọc được, mà chỉ bắt
`FileNotFoundError`?* Tái hiện: file thật mode 0644 tên `*.exe` (đuôi `.exe` để Windows không tự thêm đuôi rồi đọc
thành "không có") với `subprocess.run` thật ở #1, #3, #4, #5; `gh` cố định trong argv nên #2, #6 giả `subprocess.run`
ném `PermissionError(13)`. Thông điệp dùng `e.strerror or e` để không lộ đường dẫn tuyệt đối.

| # | Gói | Chỗ | Hậu quả trước khi vá | Vá | Test đỏ → xanh |
|---|---|---|---|---|---|
| 1 | core | `llm.CodexClient._subprocess` | `OSError` thô đi qua `RoutingClient` (không phải họ `LLMError`) → orchestrator xếp `handler_error` thay vì `llm_error`, sai khuôn trong `diagnose`; `ClaudeCodeClient` bên cạnh đã bắt `OSError` — Codex lệch | `except OSError` → `LLMError("không chạy được …")` | `test_llm_clients.py::test_codex_binary_khong_chay_duoc_la_llmerror_khong_phai_oserror_tho` |
| 2 | company | `github_pr._gh` | docstring hứa "không ném"; `OSError` xuyên qua `open_pr` vào lượt giao hàng thay vì thành `PrResult` lỗi | `(False, "gh: không chạy được (…)")` | `test_delivery_real.py::test_gh_co_that_ma_khong_chay_duoc_thi_khong_nem` |
| 3 | company | `deploy._process_cmd` | docstring hứa "không ném"; `OSError` xuyên qua `deploy()` vào lượt verify thay vì `DeployRecord(ok=False, error=…)` | `(False, "<prefix>: không chạy được (…)")` | `test_deploy_process.py::test_binary_co_that_ma_khong_chay_duoc_thi_ly_do_doc_duoc` |
| 4 | company | `deploy._compose` | như trên, mode compose | `(False, "<binary>: không chạy được (…)")` | `test_deploy_compose.py::test_binary_co_that_ma_khong_chay_duoc_thi_ly_do_doc_duoc` |
| 5 | keeper | `evidence.run_command` | `OSError` thô làm vỡ cả lượt đo hai chiều | mã mới `UNRUNNABLE_EXIT = -3` — **không** gộp vào `MISSING_EXIT`: `audit.py` coi "không có trên máy" là bỏ qua, gộp vào là đọc "chưa quét" thành "sạch" | `test_evidence.py::test_run_command_cong_cu_co_that_ma_khong_chay_duoc_thi_khong_nem` |
| 6 | keeper | `github.GitHubReader._run` | `OSError` thô giết lượt đọc thay vì `ok=False`; nay `open_prs()` trả `None` (không biết ⇒ I3 đóng) như khi vắng `gh` | `ok, out = False, "gh: không chạy được (…)"` | `test_github.py::test_gh_co_that_ma_khong_chay_duoc` |

Đã rà và **an toàn**: company `workspace._git_ok` (git là điều kiện bắt buộc, ném có chủ ý), keeper `worktree._git` /
`publish` (ném lỗi riêng của module, caller bắt), gateway `_probe_cli` (`shutil.which` trước, rồi bắt chung), core
`sandbox` (fail-closed theo ADR-0010 — ném là đúng), core `ClaudeCodeClient` (đã bắt `OSError` từ trước).

### 3b. K9 — keeper `bump_dependency` sửa cả văn xuôi (bảng §3 #403)

Regex cũ chỉ neo ranh giới tên gói, nên comment `# pydantic>=2 vì …`, mô tả `description = "Dùng pydantic để …"` và
khoá TOML `[tool.uv.sources] pydantic = {…}` đều bị thay thành `new_spec`. Nay chỉ khớp **chuỗi requirement**: tên
gói ngay sau nháy mở, spec kết thúc ở nháy đóng / `;` (marker) / `,` (ràng buộc kế). Extras (`pkg[x]`) bị bỏ qua có
chủ ý: `new_spec` không mang extras, thay là mất chúng. Ba test đỏ trước: `test_patcher.py::test_bump_dependency_chi_sua_chuoi_requirement_khong_sua_van_xuoi_hay_khoa_toml`,
`…_khong_cat_extras_thanh_requirement_hong`, `…_spec_co_khoang_trang_thay_tron`. Bản vá đầu (chưa có lookahead kết
thúc) vẫn sửa mô tả bắt đầu bằng tên gói — test siết lại bắt được, rồi mới thêm `(?=[ \t]*["',;])`.
Giới hạn mới, có chủ ý: vì neo nháy, regex chỉ hợp với file có requirement trong chuỗi (TOML). Mọi caller hiện
có (CLI `keeper`, test) chỉ đưa `pyproject.toml`; ai đưa `requirements.txt` sẽ nhận `ValueError` "không tìm thấy",
không ghi gì (hỏng ồn ào chứ không sửa sai im lặng).

### 3c. G4 — danh tính `by`/`actor` của console không trần, giả được dòng log (bảng §3 #403)

`decide.py` không giới hạn `by`; `engine.py` ghi `by` thẳng vào dòng `=== … console bật bởi {by}` của log động cơ;
`submit.py` có `MAX_ACTOR_LEN` nhưng không chặn ký tự điều khiển. Một `by` chứa `\n=== … bởi human:b` giả được một
dòng log khác. Vá: một hàm `decide.actor_problem` (≤ 80 ký tự, `str.isprintable()`), dùng chung cho `decide`
(`by`), `submit` (`actor`, bỏ `MAX_ACTOR_LEN` cục bộ) và `engine.start`/`stop` (`by`, ném `EngineError`). `API.md`
ghi luật mới cùng PR. Test đỏ trước: `test_decide.py::test_by_co_ky_tu_dieu_khien_hoac_qua_dai_bi_tu_choi_truoc_khi_ghi`,
hai ca mới của `test_engine.py::test_start_tu_choi_tham_so_sai`, một ca `stop`, một ca `test_submit.py`. `reason` của
decide không cần trần riêng: thân request đã giới hạn `MAX_BODY_BYTES` (1 MiB) và `reason` chỉ vào audit-log của bus
dạng JSON, không vào dòng log văn bản nào (`grep reason` trong `decide.py`/`engine.py`: không lời gọi log nào).

### 3d. company `metrics` — nhãn Prometheus không thoát

`emit` ghép `f'{k}="{v}"'` thẳng: một `ticket_id` có `"`, `\` hay xuống dòng làm hỏng cả bản text exposition. Vá
`_label_value` đúng ba escape của text format (`\` → `\\`, `"` → `\"`, xuống dòng → `\n`). Test đỏ trước:
`test_adr0012.py::test_prometheus_thoat_nhan_dung_text_format`.

## 4. Đọc, không vá — lý do và điều kiện quay lại

| Mã | Mức | Ở đâu | Phát hiện | Vì sao chưa sửa |
|---|---|---|---|---|
| A1 | thấp | `company/metrics.py diagnose` | mọi `gate.decide` (kể cả **approve**, kể cả subject không phải ticket như `P1`, `REL-001`) cộng `reopen` → `ticket_quay_vong` liệt kê cả gate duyệt một lần | đổi nghĩa "quay vòng" chạm `/gate-brief` và người đọc `diagnose`; cần quyết "reopen" là gì (reject? retry?) trước khi sửa. Quay lại khi `diagnose` được dùng làm tín hiệu tự động |
| A2 | — | `xagents_core/context.py fit(counter=)` | tham số `counter` không caller sản xuất nào truyền | docstring đã nói rõ đây là móc cho tokenizer thật; không phải lỗi |

Đã đọc, không thấy lỗi: core `observe.py`, `tools.py`, `context.py`; company `web.py`, `trace.py`,
`supply_chain.py`, `orch/rehydrate.py`, `orch/release_fsm.py`; console `server.py` (desync đã vá ở #403; đường `by` ra
`logger.info` của `/api/engine` nay đi qua `_check_actor` trước).

## 5. Tối ưu — theo số đo

Đo bằng `pytest -n auto --durations` (company) trên 4 lõi, không `--cov`.

### 5a. Cổng cục bộ khác CI: `.venv` chung nhiễm extra `graph`

- **Triệu chứng**: test e2e company 12–15 s mỗi ca; profile một ca (`test_orchestrator_with_repo_produces_verified_prs_and_reviewers_read_diff`)
  thấy 10/12 s nằm trong 9 lần `sandbox.run` — `python -m pytest` thật trên repo khách (`verified_by=workspace`),
  1,3 s mỗi lần cho một repo vài test.
- **Đo tách biến**: pytest trên thư mục một test: 1,39 s; cùng lệnh với `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`: 0,29 s.
  `-X importtime`: `langsmith` (plugin `langsmith_plugin`, kéo theo bởi `langgraph` của extra `graph`) chiếm ~0,7 s.
- **Cơ chế**: `dev-task.sh typecheck company` chạy `uv run --locked --extra graph mypy …` (khớp job `static`). `uv run`
  cài extra vào `.venv` chung và **không bao giờ gỡ gói thừa**, nên bước pytest ngay sau — và mọi lần chạy về sau — có
  `langsmith`. Job `unit` của CI (`uv sync --locked`, không extra) không có. Tức cổng cục bộ vừa chậm vừa **không
  khớp CI** ở tập plugin pytest.
- **Đo**: `uv sync --locked` ở gốc (đưa `.venv` về đúng tập của CI, `langsmith` biến mất) → pytest con 0,5 s; ca e2e trên 12,2 s → 6,0 s; **cả bộ company
  370 s → 207 s (−44 %)**.
- **Vá**: lệnh mypy lần hai chạy `--isolated` (môi trường riêng, `langgraph` vẫn có — đã kiểm `import langgraph`; lần
  đầu ~6 s, sau ~1 s nhờ cache), ở cả `dev-task.sh` và `ci.yml` vì `test_cong_khung.py` đối chiếu nguyên chuỗi lệnh
  mypy hai bên. Test mới `test_dev_task_lenh_co_extra_chay_isolated_khong_de_lai_trong_venv_chung` đỏ trước (lệnh
  company thiếu `--isolated`) → xanh. Máy đã nhiễm từ trước: chạy `uv sync --locked` một lần ở gốc.

### 5b. Hai test ngủ thật

| Test | Trước | Sau | Nguyên nhân | Đo hai chiều |
|---|---|---|---|---|
| `test_deploy_compose.py::test_khong_khai_va_khong_do_ra_compose_thi_skipped_chu_khong_phai_thanh_cong` | 30,13 s | < 0,01 s | `Runtime(("x",))` lấy `timeout_s` mặc định 30 s mà test không thay `http_probe` → smoke gõ cổng 8080 **thật** suốt 30 s (máy dev có gì ở 8080 thì kết quả đổi theo) | assertion chỉ đòi `subs[:1] == ["up"]`, không đổi; thay probe như mọi ca khác của file |
| `test_process_review_fixes.py::test_hai_chu_namespace_ghi_song_song_khong_mat_ban_ghi` | 10,01 s | 1,01 s | `context_key` gọi lại `scope_of` **trong** khoá: với bản đúng, luồng giữ khoá chờ barrier một mình tới hết `timeout=10` — mỗi lần chạy | `timeout=1`; bỏ khoá ở `Blackboard.write` → đỏ 5/5 lần, trả khoá → xanh. Thử trước "chỉ chặn lần gọi đầu mỗi luồng" làm test **mất khả năng bắt lỗi** (bỏ khoá vẫn xanh: cửa sổ tranh chấp thật là lần gọi thứ hai, sau khi đọc version) — đã bỏ |

### 5c. Đã đo, không đổi

- Phần còn lại của company là test e2e 6–11 s (sau 5a), thời gian nằm ở git + pytest con thật trên repo khách — chính
  hành vi các test đó chứng minh; giả lập đi là bỏ bằng chứng `verified_by=workspace`.
- `test_delivery_real.py::test_orchestrator_pr_loi_gh_va_bo_qua_khi_thieu_push_remote` (10,8 s) là hai pipeline e2e
  trong một ca; tách ra không giảm tổng thời gian worker.
- `test_smoke_khong_tra_loi_trong_timeout_thi_ghi_ly_do` (2 s) chờ đúng `timeout_s=2` nó kiểm.
- Console (99 s, 744 ca): không ca đơn lẻ nào bất thường — chậm nhất là `test_so_test_trong_readme_khop_dia` 7,9 s
  (gọi `pytest --collect-only` thật cho năm gói, chính là thứ nó đo), còn lại ≤ 1,1 s; thời gian trải đều trên các
  test hook/subprocess.

## 6. Việc để lại

- Merge PR này → dependabot tự đóng #397/#398/#404/#405/#406; máy cục bộ đã chạy `gate company` trước đây: `uv sync
  --locked` một lần để gỡ extra tồn dư.
- A1 (`diagnose` đếm mọi quyết định là reopen) — quyết nghĩa trước khi sửa.
- Đề xuất nhóm phụ thuộc runtime trong `dependabot.yml` (§2) — quyết định của chủ repo.
- Bảng §3 #403 còn nguyên các mục chưa đụng tới ở lượt này (C3–C7, G2/G3/G5/G6, K1–K7, K10).
