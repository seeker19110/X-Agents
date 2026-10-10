# Đặc tả triển khai `keeper` — PR theo PR

Ngày lập: 2026-09-09 · Quyết định gốc: `docs/adr/0006-cong-ty-bao-tri-keeper.md` (mã BT0–BT8).
Mọi `file:dòng` đo tại `main@d83c809`; sau mỗi PR merge dòng sẽ trôi — tên hàm và mã mục là mốc, dòng chỉ để
tìm nhanh.

Tài liệu này viết cho **agent thực thi**. Mỗi mục BT là một PR giao được: tiêu đề, file đụng, thay đổi cụ thể,
test đo hai chiều, lệnh nghiệm thu, cạm bẫy đã biết. Cách thực thi một PR: đọc mục → mở worktree
(`git worktree add ../Claude-Agents-wt-<mã> -b <type>/<mã> origin/main`) → **viết test trước** → code → chạy
đúng lệnh CI của package → PR tiêu đề `<type>(keeper): BT<n> — <một câu>` → bật auto-merge → dòng CHANGELOG +
nhật ký phiên **trong chính PR đó** → cập nhật bảng theo dõi §11.

Scope PR: `keeper` (một từ chữ thường, đúng regex của `pr-policy.yml`).

---

## 0. Bất biến — đọc trước mọi mục

| # | Bất biến | Vì sao | Ép bằng |
|---|---|---|---|
| I1 | `keeper` **không có quyền ghi** ngoài: tạo nhánh, commit trong worktree của chính nó, mở PR | Nó bảo trì chính cái repo đang chạy nó | `github.py` chỉ có hàm đọc; không hàm nào gọi `gh pr merge`, `gh api -X`, hay `git push origin main` |
| I2 | Mọi patch phải có **bằng chứng đo hai chiều** mới rời pha quality | `AGENTS.md` bắt buộc §4 | `evidence.py:require_two_way()` ném `EvidenceError` khi `before.exit_code == 0` |
| I3 | Đúng **một PR bảo trì mở** tại một thời điểm | `docs/QUY-TRINH-GIT.md` §2c | `budget.py:can_open_pr()` hỏi `gh pr list --state open` thật, không tin state trong RAM |
| I4 | Không hạ `fail_under` (giá trị, không phải dòng), không sửa `.git/` hay `.github/` (CẢ `workflows/`), không push `main` | `AGENTS.md` cấm §6 | `patcher.py:FORBIDDEN_PATHS` + `check_coverage_guard` + test chặn |
| I5 | Không xoá dead code, chỉ báo cáo | `AGENTS.md` cấm §7 | `patcher` không có thao tác xoá file; `drift-detector` chỉ phát signal |
| I6 | Core không biết tên công ty nào | ADR-0001 §1 | `keeper` chỉ điền trường của `CoreConfig`; một `if cfg.prefix == "KEEPER"` trong `xagents_core` là fork mọc lại |
| I7 | `keeper` là khách hàng số 0 của chính nó | Canary | BT8 phải chạy một chu kỳ thật trên X-Agents trước khi mở cho repo khách |

**Cấm trong mọi PR BT**: chạm `software-company/src/`, `Studio-creators/src/`, `xagents-core/src/` — trừ BT1
(thêm `keeper` vào `pyproject.toml` gốc) và BT7 (thêm đúng một trường `CoreConfig` nếu **đo** được là cần).
Đụng ngoài đó là "sửa code cạnh bên" (`AGENTS.md` cấm §7).

---

## 1. Bản đồ package

```
keeper/
├── pyproject.toml            # dist `keeper`, import `keeper`, fail_under = 100
├── README.md
├── docs/
│   ├── DAC-TA-KEEPER.md      # tài liệu này
│   └── adr/                  # ADR chỉ trong package
├── agents/                   # 8 system prompt, 6 khối (nguồn của `make subagents`)
│   ├── watch/{dependency-scout,health-monitor,drift-detector}.md
│   ├── triage/triager.md
│   ├── engineering/{patcher,refactorer}.md
│   ├── quality/{regression-guard,security-auditor}.md
│   ├── release/release-clerk.md
│   └── supervisor/keeper-supervisor.md
├── skills/
├── gates/checklists.md       # checklist human gate `keeper`
├── topics/schemas/*.json
├── evals/recordings/         # bản ghi eval offline (provider fake)
├── src/keeper/
│   ├── core.py               # CORE = CoreConfig(prefix="KEEPER", db_name="keeper.sqlite")
│   ├── events.py             # Topic Literal, PAYLOAD_MODELS, NAMESPACE_OWNERS
│   ├── github.py             # adapter `gh` CHỈ ĐỌC
│   ├── signals.py            # Signal + gộp trùng
│   ├── scout.py health.py drift.py            # khối watch
│   ├── risk.py triage.py ledger.py budget.py  # khối triage
│   ├── patcher.py worktree.py                 # khối engineering
│   ├── evidence.py family.py audit.py         # khối quality
│   ├── release.py                             # khối release
│   ├── gates.py orchestrator.py cli.py
│   └── fakes.py demo.py
└── tests/
```

**Topic của `keeper`** (bảng `TOPIC_PRODUCERS` trong `core.py`):

| Topic | Producer | Nội dung |
|---|---|---|
| `maintenance-signals` | `dependency-scout`, `health-monitor`, `drift-detector`, `adapter:github` | một quan sát thô, chưa phán xét |
| `maintenance-tickets` | `triager` | signal đã gom + `risk_tier` + hạn |
| `patch-proposals` | `patcher`, `refactorer` | nhánh + diff + phạm vi |
| `verification-reports` | `regression-guard` | **bằng chứng hai chiều** + kết quả rà họ lỗi |
| `security-findings` | `security-auditor` | gitleaks / audit dependency / Scorecard |
| `debt-ledger` | `triager`, `keeper-supervisor` | thứ đã hoãn + ngày đáo hạn |
| `release-notes` | `release-clerk` | dòng CHANGELOG + mục nhật ký phiên |
| `supervisor-actions` | `keeper-supervisor` | dừng, hạ hạn mức, escalate |
| `audit-log`, `shared-context` | mở | như hai công ty kia |

`human_topics = {"maintenance-signals"}` — người nạp tay một việc bảo trì được, nhưng **không** nạp tay ticket:
ticket phải đi qua `triager` để có `risk_tier`.

Bảng `TOPIC_PRODUCERS` phải **đo ra, không suy ra** — cùng lý do đã ghi ở `Studio-creators/src/studio/core.py:10-19`:
quá nửa event do CODE phát (`adapter:github`, `orchestrator`, `release`), không do agent. Cách đo: bọc
`InMemoryBus.publish`, chạy toàn bộ suite, ghi lại `(actor, topic)` kèm khung ngăn xếp.

---

## 2. BT0 — ADR + đặc tả · 1 PR (**PR này**)

`docs(keeper): BT0 — ADR-0006 đổi tên keeper + đặc tả triển khai`

| File | Thay đổi |
|---|---|
| `docs/adr/0006-cong-ty-bao-tri-upkeep-crew.md` → `0006-cong-ty-bao-tri-keeper.md` | `git mv`; `Upkeep-crew`→`keeper`, `upkeep-supervisor`→`keeper-supervisor`, gate `upkeep`→`keeper`; lộ trình 5 PR → 9 PR trỏ tài liệu này |
| `keeper/docs/DAC-TA-KEEPER.md` (mới) | tài liệu này |
| `keeper/README.md` (mới) | công ty này là gì, chạy gì, trạng thái "chưa có mã" |
| `CHANGELOG.md`, `docs/sessions/2026-09-09.md` | tên mới + dòng cho PR này |

Nghiệm thu: `grep -ril upkeep . --include="*.md"` rỗng. Chưa có mã → không có test hai chiều.

---

## 3. BT1 — Khung package · 1 PR

`feat(keeper): BT1 — khung package, CoreConfig và topic`

| File | Thay đổi |
|---|---|
| `keeper/pyproject.toml` | theo khuôn `Studio-creators/pyproject.toml`: dist `keeper`, `packages = ["src/keeper"]`, `fail_under = 100`, ruff `line-length = 120` + ignore `E701,E702,RUF001-003`, mypy **không** bật `warn_unused_ignores` (lý do phụ thuộc nền, `Studio-creators/pyproject.toml:44-52`) |
| `pyproject.toml` gốc | thêm `keeper` vào `dependencies`, `[tool.uv.workspace] members`, `[tool.uv.sources]` |
| `keeper/src/keeper/__init__.py` | docstring luật của package + `__version__` |
| `keeper/src/keeper/core.py` | `CORE = CoreConfig(prefix="KEEPER", root=Path(__file__).resolve().parents[2], db_name="keeper.sqlite", topic_acl=…, payload_models=…, namespace_owners=…)` |
| `keeper/src/keeper/events.py` | `Topic` Literal **10** giá trị (8 topic riêng + `audit-log` + `shared-context`; bản BT0 đếm 9 là sai); model `Signal`, `Ticket`, `PatchProposal`, `VerificationReport`, `DebtEntry`, `SecurityFinding`; `PAYLOAD_MODELS`, `NAMESPACE_OWNERS` |
| `keeper/topics/schemas/*.json` | 10 schema **viết tay** rồi ép khớp bằng test `set(get_args(Topic)) == set(bus._schemas)` (`Studio-creators/tests/test_bus.py:46`). Đo 2026-09-09: **không có script sinh schema nào** trong repo — "sinh từ pydantic" ở hai công ty kia là mô tả nguồn gốc khái niệm, không phải một lệnh chạy được |
| `.github/workflows/ci.yml` | job `keeper-static` + `keeper-unit` (3.11, 3.13; ubuntu + windows) theo khuôn `core-static`/`core-unit` |

Đo hai chiều: bỏ `keeper` khỏi `members` → `uv sync` không thấy package → `pytest` đỏ `ModuleNotFoundError`;
thêm lại → xanh.

Nghiệm thu: `cd keeper && uv run ruff check src tests && uv run mypy src/keeper --ignore-missing-imports && uv run pytest -q --cov`

**Cạm bẫy**: `prefix` bám tên **import** chứ không tên dist (`Studio-creators/src/studio/core.py:6-8`) — ở
`keeper` hai tên trùng nhau nên rất dễ quên lý do; ghi comment. `root` là `parents[2]` vì file nằm ở
`src/keeper/`, `parents[1]` sẽ trỏ vào `src/`.

---

## 4. BT2 — Cầu GitHub chỉ đọc · 1 PR

`feat(keeper): BT2 — adapter gh chỉ đọc, có fake và bộ đệm`

| File | Thay đổi |
|---|---|
| `keeper/src/keeper/github.py` | `GitHubReader`: `open_prs()`, `checks(pr)`, `dependabot_alerts()`, `code_scanning_alerts()`, `pr_age_days()`, `workflow_runs()`, `merged_prs(since)`. Mỗi hàm gọi `gh api` / `gh pr list --json` qua `subprocess.run(..., check=False, timeout=…)`, parse JSON, trả model pydantic |
| | `FORBIDDEN_ARGS` — bảng của BT0 (`-X`, `--method`, `merge`, `close`, `delete`, `edit`) **có lỗ, đo được ở BT2**: `gh api` đổi sang POST ngay khi có `-f/-F/--field/--raw-field/--input`, KHÔNG cần `-X`, nên `gh api repos/o/r/pulls/1/merge -f x=y` là lời gọi GHI mà bảng gốc cho lọt (token `merge` nằm trong đường dẫn, không phải token riêng). Bảng thật thêm năm cờ đó: `_run()` ném `GitHubWriteAttempt` nếu argv chứa. Đây là bất biến **I1** thành mã, không thành lời hứa trong prompt |
| | Bộ đệm TTL 60s theo argv — một chu kỳ watch không được gọi `gh` 40 lần |
| `keeper/src/keeper/fakes.py` | `FakeGitHub` trả bản ghi JSON cố định; **mọi** test dùng nó, không test nào chạm mạng |

Đo hai chiều: xoá kiểm `FORBIDDEN_ARGS` → `test_khong_cho_ghi` đỏ. Đặt TTL = 0 → `test_bo_dem_khong_goi_lai` đỏ.

**Cạm bẫy**: `gh` có thể không có trên runner — không sao vì test dùng `FakeGitHub`. Nhưng **không được** viết
test bỏ qua theo biến môi trường hay theo `os.name`: đó đúng là "cổng đúng-sai theo máy chạy" (`TRAPS.md` §2,
`Studio-creators/pyproject.toml:44-52`). Thay `subprocess`, đừng thay môi trường.

---

## 5. BT3 — Khối watch · 1 PR

`feat(keeper): BT3 — dependency-scout, health-monitor, drift-detector`

| File | Thay đổi |
|---|---|
| `scout.py` | đọc `uv.lock` + alert từ `github.py` → `Signal(kind="dependency", semver_jump="patch|minor|major", is_dev=…)` |
| `health.py` | từ `workflow_runs()`: flake rate (cùng SHA, kết quả khác nhau), thời gian CI p50/p95, tuổi PR mở; đọc `coverage.xml` nếu có → độ trôi coverage giữa các package |
| `drift.py` | ba phép so **thuần cục bộ**: (a) `.claude/agents/sc-*.md` vs `software-company/agents/**` + `skills/**` + `gates/checklists.md` (so hash nguồn ghi trong front matter bản dẫn xuất); (b) `tests/golden/**` vs agent md; (d) dòng `CHANGELOG.md` còn chỗ trống thay cho số PR (`(#PENDING)`, `(#PRNUM)`…). Phép (c) cũ — mỗi PR merged trong `git log` có `(#n)` trong `CHANGELOG.md` không — đã bỏ ở audit 2026-10-10 F1 (`scripts/pr_changelog_check.py` chặn trước merge; sau merge nó chỉ còn báo giả cho PR `no-changelog`) |
| `signals.py` | `Signal` + `dedupe(signals)` theo `(kind, subject)`: giữ cái mới nhất, cộng `seen_count` |

Đo hai chiều: sửa tay một file `.claude/agents/sc-*.md` trong repo fixture → `drift` phải phát signal; hoàn
nguyên → im. Bỏ `dedupe` → `test_gom_trung` đỏ với 3 signal cùng subject.

**Cạm bẫy** (lịch sử — phép (c) đã bỏ ở audit 2026-10-10 F1): phép (c) báo giả cho mọi PR merge **trước
khi** luật `AGENTS.md` §10 có hiệu lực. Từng chặn dưới bằng một mốc ngày là hằng số có comment giải thích —
**không** lọc bằng danh sách số PR (danh sách sẽ mục ngay tuần sau).

---

## 6. BT4 — Triage, rủi ro, sổ nợ, ngân sách · 1 PR

`feat(keeper): BT4 — risk_tier, sổ nợ có đáo hạn, ngân sách thay đổi`

| File | Thay đổi |
|---|---|
| `risk.py` | `risk_tier(signal) -> "low" | "medium" | "high"` — **bảng dữ liệu**, không chuỗi `if` (bài học K1.7: bảng chuyển trạng thái tra cứu được thì test được). `high`: semver major · chạm `xagents-core/` · chạm `*/agents/` hay `*/skills/` · chạm `.github/` · chạm mục coverage của `pyproject.toml` · security ≥ high. `low`: patch/minor của dev-dependency · lệch tài liệu thuần. `semver_jump is None` (pre-release, đo ở BT3) KHÔNG rơi vào `low` — chưa biết bậc nhảy thì là `medium` |
| `ledger.py` | `DebtEntry(subject, reason, due_at, tier)`, `overdue(now)` → escalate. **Cơ chế MỚI, KHÔNG dùng lại `debt_due`** — xem "Đo lại: `debt_due` không dùng lại được" ngay dưới bảng. `now` tiêm được, không gọi `datetime.now()` trong thân hàm |
| `budget.py` | `can_open_pr()` = `len(GitHubReader.open_prs()) == 0` **và** `len(merged_prs(7 ngày)) < KEEPER_MAX_PR_PER_WEEK` (mặc định 5). Hàng đợi FIFO theo `risk_tier` rồi tuổi signal |
| `triage.py` | `triager` biến `maintenance-signals` → `maintenance-tickets`; tier `high` đính kèm yêu cầu gate `keeper` |

**Đo lại: `debt_due` không dùng lại được** (bản trước của mục này viết "dùng lại cơ chế `debt_due` của company,
đọc `software-company/src/company/orch/` trước khi viết dòng đầu tiên" — sai hai lần, đã đo):

1. **Sai địa chỉ.** Cơ chế nằm ở LÕI: `xagents-core/src/xagents_core/supervisor.py:82` khai `self.debt_due`.
   `software-company/src/company/orch/gates_flow.py:88` chỉ *tiêu thụ* nó (đọc danh sách rồi mở gate escalation).
   Đọc `orch/` trước khi viết `ledger.py` là đọc chỗ dùng, không phải chỗ có cơ chế.
2. **Sai bản chất.** `supervisor.py:102-123` (`_count_debt`) đếm **chuỗi review liên tiếp** mà một nguồn không
   nhắc lại một mã nợ (`rec["streak"][src]`), và bắn khi chuỗi chạm bội số ngưỡng (`rec["fired"]` → `times`).
   Không dòng nào đọc đồng hồ: quá hạn ở lõi là quá hạn theo **số lần**, không theo **ngày**.

`DebtEntry(due_at=…)` là quá hạn theo **lịch** — một ngữ nghĩa khác hẳn, nên là cơ chế mới trong
`keeper/src/keeper/ledger.py`, không import từ `company` và **không đặt trùng tên khái niệm**: định danh ở
`keeper` là `due_at` / `is_overdue` / `Ledger.overdue`; không ĐỊNH DANH nào trong `keeper/src/` tên `debt_due`
(chỉ có docstring nhắc tới nó để giải thích vì sao hai thứ khác nhau).
Lý do đầy đủ nằm trong docstring của `ledger.py` để người sửa sau đọc được tại chỗ.

**Thế hệ của khoá chống-trùng** (`triage.py`): không phải `GateRequest.seq` (`xagents-core/src/xagents_core/gates.py:84`,
`keeper` chưa có gate lúc triage) cũng không phải `Task.retry` (chưa có `Task`), mà là **số vòng đời ticket đã
ĐÓNG của chủ thể đó**, do orchestrator đếm và truyền vào `triager(generation=…)`. Cùng nguyên tắc với hai cái
kia: thế hệ tăng khi vòng đời trước KẾT THÚC, không theo mỗi vòng quét — thế hệ theo vòng quét thì mỗi vòng ra
một ticket mới và chống-trùng thành vô nghĩa.

Đo hai chiều: `KEEPER_MAX_PR_PER_WEEK=0` → `can_open_pr()` False, orchestrator không mở PR; bỏ kiểm → test đỏ
vì PR được mở. Cho `open_prs()` trả 1 PR → phải chặn.

**Cạm bẫy**: `can_open_pr` **phải** hỏi GitHub mỗi lần (trong TTL), không tin biến đếm trong RAM — đây đúng
khuôn lỗi "state chỉ sống trong RAM" đã mắc nhiều lần ở company. Và khoá chống-trùng phải mang **thế hệ**,
nếu không nó nuốt lần hai hợp lệ (bug `once="no-test-author:{tid}"`, K1.7).

---

## 7. BT5 — patcher trên worktree · 1 PR

`feat(keeper): BT5 — patcher, worktree riêng, chạy khô`

| File | Thay đổi |
|---|---|
| `worktree.py` | `open_worktree(ticket_id)` → `../Claude-Agents-wt-keeper-<id>`, nhánh `chore/keeper-<id>`; `close()` dọn. **Không bao giờ** `reset --hard` trên checkout chung — phiên khác đang mở cùng thư mục; `git_env()` bỏ mọi biến `GIT_*` để môi trường ngoài không lái được phép dò repo của chốt |
| `patcher.py` | ba thao tác: `bump_dependency`, `regen_derived` (`make golden`, `make subagents`), `fix_docs` (dòng CHANGELOG / nhật ký phiên). `FORBIDDEN_PATHS = (".git/", ".github/", "llm.yaml", "media.yaml", "*.sqlite*")` + `check_coverage_guard` cấm HẠ ngưỡng coverage (so **giá trị** `tool.coverage.report.fail_under` đọc bằng `tomllib`, và `--cov-fail-under` ở mọi file khác). Mọi đường GHI đi qua `refuse_shared_checkout(root)` |
| `cli.py` | `keeper run --dry-run` in kế hoạch (ticket → thao tác → file sẽ đụng) mà **không** chạm file nào. `--root` **bắt buộc**, không có mặc định `"."` |

**Sửa bảng chặn so với bản đặc tả đầu (đã đo, 2026-09-09).** Bảng cũ chỉ có `.github/rulesets/`, nên
`apply_edits` GHI ĐƯỢC `.github/workflows/ci.yml` — tức gỡ chính cổng CI đang ép `fail_under`, gitleaks và
ruleset, rồi mọi chốt còn lại trong bảng này thành trang trí. Đây là gap của ĐẶC TẢ, không phải của mã, nên
sửa ở cả hai chỗ: bảng chặn nay là cả `.github/` và `.git/`. `keeper` không có việc gì phải sửa hai thư mục
đó — thay đổi ở đấy là việc của người, qua PR.

Đo hai chiều: ticket đòi sửa `.github/rulesets/x.yml` → `patcher` ném `ForbiddenPath`; xoá bảng chặn → test đỏ
vì file bị sửa thật trong repo tạm. `apply_edits`/`regen_derived`/CLI trên checkout CHUNG → `SharedCheckoutRefused`
và file không đổi; `write_guard=False` → file đổi thật. Hạ ngưỡng bằng đổi mục `[tool.coverage.report]` →
`[tool.coverage.paths]` (dòng `fail_under` y nguyên) vẫn bị chặn — đây là lý do chốt so GIÁ TRỊ chứ không so dòng.

**Cạm bẫy**: patch chạm `agents/`/`skills/` **bắt buộc** đủ bảy bước `CONTRIBUTING.md` §3, mà bước
`make eval-record` cần model thật. Vì thế `patcher` **không được** tự làm nhóm này: nó chỉ mở ticket `high` và
để người quyết. Ghi thành câu cấm ngay trong system prompt của `patcher`, không chỉ trong code.

---

## 8. BT6 — Bằng chứng hai chiều và rà họ lỗi · 1 PR

`feat(keeper): BT6 — bằng chứng hai chiều bắt buộc, rà cả họ lỗi, security-auditor`

| File | Thay đổi |
|---|---|
| `evidence.py` | `TwoWayEvidence(cmd, before: RunOutcome, after: RunOutcome, verified_by)`. `require_two_way(ev)` ném `EvidenceError` khi `before.exit_code == 0` (tắt bản sửa mà vẫn xanh ⇒ test không đo gì), hoặc `after.exit_code != 0`, hoặc `verified_by != "workspace"` |
| | Cách lấy `before`: `git stash` phần diff của patch → chạy lệnh CI → `git stash pop`. Lưu **output thật**, không lưu lời khai |
| `family.py` | từ patch rút "cơ chế" (tên hàm / khoá / mẫu regex) → grep toàn repo → báo cáo `hits` (chỗ cùng cơ chế) **và** `safe` (chỗ đã kiểm là an toàn, kèm lý do). `safe` rỗng ⇒ báo cáo không hợp lệ (`TRAPS.md` §1: phải ghi cả chỗ an toàn và vì sao) |
| `audit.py` | `security-auditor`: gitleaks toàn lịch sử, audit dependency, OpenSSF Scorecard qua `github.py` |

Đo hai chiều: dựng patch giả không sửa gì thật → `before.exit_code == 0` → `require_two_way` ném; nới điều kiện
`== 0` thành `>= 0` → test đỏ.

**Cạm bẫy**: cám dỗ lớn nhất là để agent **tự khai** `verified_by="workspace"`. Trường này chỉ được set bởi
code vừa chạy lệnh, không bao giờ nhận từ JSON model trả về — lọc nó ở `guard` như `untrusted_fields`
(`xagents-core/src/xagents_core/config.py:55`). Đây là `AGENTS.md` cấm §8 ("không tin lời khai") thành mã.

---

## 9. BT7 — release-clerk, gate `keeper`, orchestrator · 1 PR

`feat(keeper): BT7 — release-clerk, human gate keeper, vòng lặp orchestrator`

| File | Thay đổi |
|---|---|
| `release.py` | soạn dòng `CHANGELOG.md` + mục `docs/sessions/<ngày>.md`; điền `(#n)` **sau** khi có số PR rồi commit tiếp vào chính PR đó (`AGENTS.md` §10), không mở PR thứ hai để vá số |
| `gates.py` | gate `keeper` bọc `PersistentGate` của lõi (`xagents-core/src/xagents_core/gate_cli.py:78`); `GateKind = patch\|release\|escalation`; `REQUEST_ACTORS` (allowlist vai được TẠO gate, ADR-0008/#216); `APPROVERS_SOURCE` nêu rõ nguồn danh sách; `approvers()` nhận `CORE.approvers_env` — **không viết cứng** tên biến môi trường (lõi không được biết tên công ty nào, I6); `created_by` không rỗng (ADR-0005, #199); four-eyes giữ nguyên |
| `bus.py` | `KeeperBus`/`KeeperMemoryBus` = bus lõi + `Envelope` của `keeper` (khuôn `company/bus.py`). Không có trong bản đồ §1 nhưng bắt buộc: bus lõi generic theo lớp envelope, để nguyên lớp lõi là mất `topic: Topic` ở lớp kiểu |
| `keeper/gates/checklists.md` | checklist gate `keeper`: `risk_tier`, bằng chứng hai chiều, báo cáo họ lỗi, ngân sách còn chỗ, không chạm đường cấm (bản mã: `gates.CHECKLIST`) |
| `orchestrator.py` | vòng lặp `watch → triage → patch → verify → gate? → release`; resume qua **`SQLiteBus`** (xem sửa 1 dưới); `--watch` như hai công ty kia; `pr_blockers()` là nơi DUY NHẤT nối bốn cổng BT4–BT6: `human-only` (`patcher.HUMAN_ONLY_SEGMENTS`), `evidence` (`require_two_way`), `gate` (tier `high`), `budget` (`can_open_pr`) |
| `topics/schemas/verification-reports.json` | `$defs` phải nằm **cả trong** `properties.payload`: bus dựng validator payload từ `s["properties"]["payload"]` làm gốc riêng (`xagents-core/src/xagents_core/bus.py:74`), nên `$ref: "#/$defs/RunOutcome"` chỉ có `$defs` ở gốc file là `PointerToNowhere` — đo được lần đầu ở BT7 khi có mã publish topic này |
| `keeper/agents/**` (8 file) | system prompt; front matter đủ `model_tier` — mặc định `cheap`, `strong` chỉ cho `refactorer` và cho `triager` khi tier cao |
| `keeper/evals/recordings/` | bản ghi eval provider fake cho **10** agent — **chưa có**: `keeper` chưa có hạ tầng eval, và bước `make eval-record` của `CONTRIBUTING.md` §3 cần model thật ⇒ `chờ người`. Không dựng thư mục rỗng để khỏi trông như đã chạy |

Đo hai chiều: ticket `risk_tier=high` chưa có gate approved → orchestrator **không** mở PR; approve → mở. Tắt
kiểm `created_by` → test bypass four-eyes đỏ (khuôn test đã có ở #199). Mỗi cổng trong bảng `pr_blockers` phải
tắt được riêng và làm đỏ đúng ca của nó.

### Ba chỗ mục này nói SAI — đã đo lại ở BT7, đừng chép lại bản cũ

1. **`SqliteBus` không tồn tại.** Tên thật là **`SQLiteBus`** (`xagents-core/src/xagents_core/sqlite_bus.py:57`).
2. **`HumanGate` không có `approve()`/`reject()`.** Chỉ có `decide(subject_id, decision, by, reason, *, enforce)`
   (`xagents-core/src/xagents_core/gates.py:87`). Thế hệ chống-trùng của một gate là **`GateRequest.seq`**, do
   `request()` gán (`gates.py:84`) — **không** phải `created_at` (`created_at` đổi sau mỗi lần dựng lại từ
   replay, nên khoá `once` lấy nó làm thế hệ sẽ nhắc/escalate lại một gate đã nhắc rồi).
3. **Cạm bẫy "`gate_cli approve` là reopen" viết sai.** `decide()` **ĐÓNG** gate: bỏ `subject_id` khỏi
   `pending` và đẩy bản ghi vào `history`, đúng một lần, bất kể `decision` là gì
   (`xagents-core/src/xagents_core/gates.py:87-94`). "Mở lại" là **nghĩa riêng** mà orchestrator của company
   gán cho một SỐ escalation — nó tự phát `supervisor-actions{action:"resume"}` theo LOẠI subject sau khi gate
   đã đóng (`software-company/src/company/orch/gates_flow.py:110-117`). Câu đúng: **muốn một ticket bảo trì
   được làm lại thì orchestrator phải tự phát `resume`; `approve`/`reject`/`rollback` chỉ khác nhau ở chữ
   `decision` ghi vào `history`, không cái nào mở lại gì cả.**

---

## 10. BT8 — Console, tài liệu, canary · 1 PR

`feat(keeper): BT8 — tab console, hướng dẫn vận hành, canary trên chính repo`

| File | Thay đổi |
|---|---|
| `console/src/console/…` | tab `keeper`: hàng đợi ticket, ngân sách còn lại, sổ nợ quá hạn, gate đang chờ. **Không** hiện số xanh khi rỗng — ghi thẳng "chưa chạy lần nào" (số xanh có thể xanh vì rỗng) |
| `docs/HUONG-DAN-VAN-HANH.md` | mục vận hành `keeper` |
| `docs/TRUC-VA-DUNG-KHAN.md` | cách tắt `keeper` mà không tắt hai công ty kia |
| `keeper/README.md` | cập nhật trạng thái thật |

Nghiệm thu **là một chu kỳ thật**: chạy `keeper` trên chính X-Agents, để nó tự mở đúng một PR bảo trì có bằng
chứng hai chiều, và PR đó merge. Không có PR thật thì BT8 chưa xong — "xong" cần output lệnh trong chính lượt
đó (`AGENTS.md` cấm §8).

---

## 11. Bảng theo dõi

Bảng theo dõi **không nằm ở đây**. Trạng thái từng BT (kèm mức C1/C2/C3, đợt, `sc-*` chấm, và những chỗ tài liệu
này đo lại thấy sai) sống ở một chỗ duy nhất: `docs/thi-hanh/keeper.md` §B.

Hai bảng cùng nói tám việc thì sửa một chỗ là lệch chỗ kia — đúng bệnh `docs/KHUON-THI-HANH.md` §6 mô tả. Cập nhật
trạng thái **trong chính PR** làm ra thay đổi, không để lại cho một PR dọn dẹp.
