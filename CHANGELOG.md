# Changelog

Theo [Keep a Changelog](https://keepachangelog.com/vi/1.1.0/). Mỗi PR merge vào `main` một dòng, scope trong
ngoặc, số PR ở cuối. Chi tiết và lý do nằm trong PR và ADR; ở đây chỉ trả lời "đã đổi gì, khi nào".
Phiên bản: repo chưa gắn tag phiên bản cho chính nó (tag `v*` là của sản phẩm khách, ADR-0027) — nhóm theo ngày.

## Chưa phát hành

- fix(keeper): **trả ba nợ còn lại sau #381 — mỗi mục một test đỏ trước** (#PR). `publish()` push đúng sha commit đã kiểm (`<sha>:refs/heads/<nhánh>`), không theo tên nhánh — commit chen giữa kiểm và push không còn lên remote, gỡ marker `no-ky-thuat` (ADR keeper 0002); báo cáo `verification-reports` có `env.key` lệch `payload.ticket_id` bị từ chối và thu hồi cả hai ticket, cùng một `_check_report` cho đường ghi lẫn replay; prompt `regression-guard` v3 nói `patch_id`, `before`/`after` do code đo, sửa worktree sau lần đo phải đo lại (bảy bước `CONTRIBUTING.md` §3, eval-record n-a vì vai này cố ý không có bộ ca). Kèm: merge dependabot ruff 0.16.9 (#371).
- fix(no-ky-thuat): **trả nốt bốn nợ "người sau" của #380 — mỗi mục một test đỏ trước** (#381). Keeper: chiều đỏ fail closed — chỉ `pytest` gọi thẳng được tin mã thoát, mọi lệnh khác (tox, `sh -c`, script) phải in dòng tổng kết có `N failed`; `record_verification` lấy `ticket_id` từ route (lệch thì audit `verification.subject_overridden`), payload sai hình vẫn thu hồi `verified` bền qua bus (`payload_error`); `publish()` so cây nhánh sắp push với `patch_id` trước mỗi lần push, sau lần đo chỉ được THÊM đúng dòng release của note, lệch thì `EvidenceError` và CLI thoát 4 (ADR keeper 0002). Company: `graph.py` dùng TypedDict `GraphState` — mypy sạch khi cài extra `graph`, job `static` chạy thêm mypy với extra đó.
- fix(no-ky-thuat): **trả ba nợ cố ý của I2 keeper và cuộc đua chiếm lease của core — mỗi mục một test đỏ trước** (#380). Keeper: lệnh bọc (`make`, `dev-task.sh`) chỉ là chiều đỏ khi dòng tổng kết pytest cuối có `N failed`; bằng chứng hai chiều gắn `patch_id` = cây git nội dung worktree, cổng `evidence` chỉ mở khi worktree vẫn đúng nội dung đã đo; đo lại hỏng vẫn lên bus nên thu hồi bền qua replay; báo cáo không `patch_id` bị từ chối (ADR keeper 0001 — dãy ADR mới `companies/keeper/docs/adr/`). Core: `Lease` chiếm lock bằng khoá OS (`flock`/`msvcrt`) thay đọc-rồi-ghi pid — hai tiến trình thật đua nhau trước đây cùng thắng 10/10 vòng, nay đúng một.
- fix(review): **đóng 11 mục "chỉ báo, chưa sửa" của lượt review #378 — mỗi mục một test đỏ trước** (#379). Company (ADR-0034): ký Gate 3 mà lượt production gặp `TransientError` thì hoãn `gate.decide` qua đường hoãn chung, khoá bền `decide.applied:<eid>` nên lần xử lý lại không đếm hay áp lại tác dụng; hai `gate.decide` cho một gate (console + `gate_cli`) chỉ bản thật sự đóng gate được thi hành (`PersistentGate.closers`) — trước đây deploy production hai lần; ký muộn một gate đã escalate vì quá hạn thì `resume` chủ thể thay vì giam event production và hỏi lại người; `hold` là "chưa quyết": mở lại đúng gate (cùng kind/checklist/người tạo), không còn đá ticket merged về làm lại hay đóng dự án kẹt; supervisor dựng lại `last_seen` từ escalate vì im lặng nên restart không escalate lại; `COMPANY_DEPLOY_RUNTIME` thiếu nháy đóng là `DeployError`; `_retry_con_can` đọc `subject` của bản ghi unhandled thay vì khoá rỗng. Keeper: pytest thoát 2–5 (file test mới bị stash, `-k` không thu được test) không còn là chiều đỏ của bằng chứng hai chiều; `gh` không trả lời thì `audit` báo `dependabot`/`code-scanning:loi-cong-cu` thay vì "không có phát hiện"; báo cáo hỏng đến sau thu hồi `verified`. TRAPS: company 5 dòng mới, mở rộng 2 dòng; keeper 1 dòng mới, cập nhật 3 dòng (một dòng "thế hệ" đã lỗi thời).
- fix(review): **lượt review toàn repo bằng skill và trợ lý có sẵn — 30 lỗi ở năm gói, mỗi lỗi một test đỏ trước** (#378). Khung: hook chặn push bắt cả `HEAD:refs/heads/main` và `+main`. Gateway: một lần đọc file tài khoản hỏng không còn xoá cả pool khi ghi; request đang bay không tạo lại tài khoản vừa logout; regex "thử lại sau" hết backtrack bậc ba (1000 khoảng trắng: 4,4 s); `_pid_is_gateway` khớp chữ ký daemon thay vì chuỗi con; `--host` đi qua argv thay vì nội suy vào `python -c`. Console: bốn thân request dị dạng (token không ASCII, NUL trong `/static/`, `action` là mảng, JSON lồng 100k tầng) trả mã lỗi thay vì đứt kết nối; `.bak`/`.tmp` của `llm.yaml` mở 0600 trước khi có nội dung và bị `.gitignore`/`.dockerignore`/hook bắt. Core: `OSError` của tool và binary thiếu trong sandbox thành dữ liệu cho model thay vì mất lượt; phân loại lỗi "tạm thời" theo cụm có ranh giới từ ("generate", "context limit" không còn làm backend nghỉ); `stop_reason == "max_tokens"` của Anthropic báo rõ. Company: `core.quotepath=false` cho mọi lệnh git (file tên tiếng Việt từng rơi khỏi diff gửi reviewer và khỏi hồ sơ gate release); `request_changes` ở gate spec gọi lại spec-writer kèm hint rồi trình lại gate (ADR-0031 §3), khoá bền qua audit; escalate gate quá hạn khoá bằng `o.once` thay vì set RAM; smoke không đo nhầm tiến trình đã chiếm cổng cố định; lệnh nháy lẻ và lock file khách hỏng thành lý do thay vì ném; đoạn trích DuckDuckGo không mượn của kết quả sau. Keeper: publish ticket lỗi giữa nhịp không còn nuốt signal; `pr.blocked` chỉ ghi khi cổng chặn đổi (trước: một dòng mỗi 5 giây); `drift` thoát 2 trên thư mục không phải git hoặc clone nông thay vì báo "sạch"; lần chạy quá giờ/thiếu lệnh/bị giết không còn được tính là chiều đỏ của bằng chứng hai chiều; khoá dựng từ `audit-log` (topic mở) chỉ tin bản ghi của `keeper-orchestrator`, bản `reject`/`pr.blocked` giả không nuốt được dòng thật. Company (lượt hai): hành động tự `_mark` không còn nuốt `TransientError` — `_spec_runtime_missing` hoãn thay vì ăn mất lượt sửa duy nhất, `_assume_clarifications` ghi sổ sau lời gọi, lượt viết lại spec của `request_changes` hoãn; mọi đường hoãn đi qua `scheduler._defer_transient` giữ mốc `thử lại sau Ns`. Core (lượt hai): lỗi tạm thời dạng snake_case (`insufficient_quota`, `request_timeout`) được nhận lại. TRAPS năm gói thêm 20 dòng, mở rộng 2 dòng, sửa một dòng đã lỗi thời (gateway `stop`/PID).
- feat(khung): **ECC vào repo bằng vendor chọn lọc, bỏ đường plugin** (#377). ADR 0028. 23 mục (12 skill, 3 lệnh, 8 agent) chép vào `.claude/` với tiền tố `ecc-` bằng `scripts/ecc_vendor.py` (`make ecc-vendor`) từ đúng commit ghim trong `docs/integrations/ecc.lock.json`, kèm sha256 từng tệp. Bỏ marketplace, plugin, hook và biến `ECC_*` khỏi `.claude/settings.json`. Cổng offline `test_cong_ecc.py` (sha256, tên, ngân sách mô tả 5 035/6 000 ký tự, `company.assetscan`) và job CI `ecc-check` sinh lại từ nguồn ghim rồi so. Đo bằng `claude -p` thật: phiên web thấy 15 lệnh `/ecc-*` và 8 agent `ecc-*`; ở `--restricted` (company/keeper) thấy 0.
- docs(khung): **ADR 0027 đo được lượt MCP thật có `--restricted` (mục c)** (#376). CLI 2.1.287, `claude-haiku-4-5`: `company.probe --binary claude` → `mode: mcp`, tool công ty được gọi qua cầu MCP, argv ghi lại có `--restricted --strict-mcp-config --tools --allowedTools`; lượt không tool của company và keeper (`--restricted --tools ""`, đổi ở #374) trả JSON đúng schema. Mục (b) đo rò hook bị bộ phân loại auto-mode chặn lần nữa, (a) `/plugin` vẫn cần máy người vận hành — ADR giữ "đề xuất".
- docs(khung): **ADR 0027 ghi kết quả đo ECC bằng `claude` thật: phiên Claude Code on the web không nạp ECC** (#375). CLI 2.1.286 trong container remote: `plugin marketplace list` rỗng, `plugin install ecc@xagents-ecc` → `not_found`, `init` của một lượt `claude -p` chỉ có plugin builtin. Chưa tách được nguyên nhân (chế độ hermetic hay thiếu bước tin tưởng marketplace) vì chạy lại với môi trường đã gỡ biến remote bị từ chối quyền; đo hook có/không `--restricted` và lượt MCP thật vẫn mở.
- feat(khung): **tích hợp ECC (`affaan-m/ECC`) làm plugin ghim commit cho phiên Claude Code, cách ly khỏi runtime công ty** (#374). ADR gốc 0027: `.claude/settings.json` khai marketplace tại chỗ `xagents-ecc` → plugin `ecc` từ `affaan-m/ECC@c70874f` (tag v2.2.2; 293 skill, 94 lệnh, 68 agent tiền tố `ecc:`), tắt bản trôi `ecc@ecc`; lock `docs/integrations/ecc.lock.json`. Hook ECC giữ profile `standard`, tắt đúng hai cái trái luật repo — `pre:bash:block-no-verify` (đo rc=2 với `git commit --no-verify`, chặn đường thoát của `AGENTS.md`) và `pre:edit-write:suggest-compact` (trái auto-compact 300k); không vendor rule/skill nào. Company (chế độ không tool và MCP) và keeper giờ gọi `claude -p --restricted` như `cli_tools` vốn có, để plugin/hook từ settings user/project không chen vào lượt agent. Cổng mới `platform/console/tests/test_cong_ecc.py`. **Đo hai chiều**: trước sửa ba test argv đỏ `'--restricted' in [...]`, cổng ECC 4/5 đỏ; sau sửa xanh; làm lệch sha/`ecc@ecc`/hook tắt → 3/5 đỏ, trả lại → 5/5 xanh. Chưa đo bằng CLI thật: tải plugin từ marketplace `settings`, mức rò thực khi thiếu `--restricted`.
- docs(sessions): **nhật ký 2026-09-28 ghi #367, #368, #369 đã merge và diễn biến CI của #369** (#370). Ba dòng "Đang
  mở" chỉ nối đuôi phần còn thiếu (`main@<sha>`, run CI trên `main` sau merge), không sửa chữ đã ghi. CI của #369
  đo lại từ log job: `console-unit (ubuntu-latest, 3.11)` và `eval-replay` đỏ ở `uv sync --locked` vì PyPI trả 503,
  trước khi test nào chạy; `metadata` đỏ tới khi thân PR tick ô DoD dòng CHANGELOG — cổng đọc thân PR từ payload
  sự kiện, nên commit điền `(#n)` không tự làm nó xanh.
- fix(keeper): **`drift`/`run`/`publish` tự lên gốc git khi được trỏ vào thư mục con**. Ba lệnh CLI đưa cùng một
  đường dẫn cho `git` (tự dò lên gốc) và cho phép ghép đường dẫn file (không dò): từ `companies/keeper`,
  `keeper.cli drift` báo 200 PR "thiếu dòng CHANGELOG" giả mà bỏ sót mọi phép `sc-*`/golden; `run --root <con>` ghi
  `CHANGELOG.md` vào thư mục con; `publish --repo <con>` tìm worktree sai chỗ (`WorktreeError`) hoặc, khi nhánh
  ticket chưa có, dựng worktree mới ngay trong checkout chung (I1). `worktree.repo_root()`
  (`git rev-parse --show-toplevel`; không phải repo git thì giữ nguyên) ở cửa vào cả ba lệnh. Bốn test mới đỏ trên
  code cũ → xanh; đột biến từng dòng về bản cũ → đúng test của dòng đó đỏ. Rà họ: `watch` an toàn;
  `scout.scan`/`health.scan` tiềm ẩn, chưa có chỗ gọi — ghi ở `companies/keeper/TRAPS.md` (#369).
- fix(khung): **ba hook Claude Code sống lại trên Linux/macOS và hết lọt cổng; quy trình một lệnh cổng; tài liệu
  khớp code, có cổng canh; core lọc cấu hình LLM của keeper khỏi lệnh con**. Hook: `.claude/hooks/*.sh` mode `100644` (commit từ Windows), `settings.json` gọi thẳng đường dẫn nên `sh`
  trả 126 "Permission denied" — Claude Code coi là lỗi không chặn, cả ba hàng rào chết im lặng ngoài Windows (đo trên
  phiên cloud Linux: commit 40 file đụng năm gói qua trong 6 giây, cổng năm gói mất 5 phút). Nay `100755`;
  `test_cong_khung.py` canh mode của mọi hook khai trong `settings.json` — đỏ với ba hook `100644`, xanh sau
  `chmod +x`. Cùng họ H6 của #365 (lần đó chỉ sửa `dev-task.sh`), ghi ở `TRAPS.md` §3. Quy trình:
  `scripts/dev-task.sh gate <gói>` là lệnh cổng duy nhất trong `CONTRIBUTING.md`, `docs/QUY-TRINH-GIT.md`,
  `README.md` và năm `CLAUDE.md` package (`make test` ở gốc không đo coverage — xanh ở đó chưa chắc xanh CI); mẫu PR
  mang nguyên văn khối BÁO CÁO XÁC THỰC của `AGENTS.md` và ô CHANGELOG `(#n)`; `QUY-TRINH-GIT` §5 kể đủ bốn bước
  của `metadata`; `CONTRIBUTING` §3 nói đúng khi nào eval đỏ (sàn `thresholds.yaml`; keeper đỏ cả ca `errored`).
  `ARCHITECTURE.md` §CI kể đủ bốn workflow và 18 job (trước: 8/18), required check là `quality` + `metadata`. Cổng
  mới `platform/console/tests/test_cong_tai_lieu.py` thay cổng `../` chỉ đọc `CLAUDE.md` của #275: link markdown và
  dẫn chiếu `../` mở được, `cd` trỏ thư mục thật, `python -m` trỏ module chạy được, `CODEMAP.md` năm package gọi tên
  mọi module, §CI kể đủ job, mẫu PR khớp `AGENTS.md`; `test_readme_goc` đọc dãy ADR trong đúng dòng (dòng gateway
  từng mượn dãy của console). Sửa tài liệu lệch code: `python -m keeper …` (không có `__main__.py`) → `keeper.cli`,
  `cd gateway`/`cd software-company` và `../TRAPS.md` sai cấp còn sót từ #262, 16 module thiếu trong CODEMAP, gate
  `patch` và canary BT8 của keeper, tám màn + SSE của console, Studio và `STUDIO_*` đã rời repo, số file import
  `xagents_core` đo lại (27/15/3). Đo hai chiều: cài lại bảy lỗi cũ → mỗi lỗi đỏ đúng một ca, gỡ ra → 12/12 xanh;
  dòng gateway mất dãy ADR → regex mới đỏ, regex cũ xanh nhầm. Cổng pre-commit hết bốn lỗ (`TRAPS.md` §3): hook
  chạy TRƯỚC lệnh nên `git add … && git commit` gõ một lần thì cả ba phép đọc index cũ; commit chỉ sửa tài liệu bỏ
  qua mọi cổng; sửa core không chạy company/keeper; rename không kéo gói cũ. Nay lệnh tự stage thì xét cả thay đổi
  chưa stage, cổng chạy gói bị đụng + gói import nó + console luôn, `--no-renames`; test dòng `fail_under` của README
  dời từ software-company sang console. `DEV_TASK_DRY_RUN=1` hết in "cổng XANH" khi chưa chạy gì. Core:
  `SECRET_ENV`/`cli_env` lọc `<PREFIX>_LLM_*` của mọi công ty theo hình (`sandbox.LLM_ENV`) thay bản liệt kê
  `COMPANY_LLM|STUDIO_LLM` — `KEEPER_LLM_PROVIDER`/`KEEPER_LLM_BACKENDS` từng đi thẳng vào mọi lệnh con keeper chạy
  bằng `clean_env()`; 5 ca đỏ → xanh, đột biến về bản liệt kê đỏ lại; core hết nhắc `STUDIO_*`/`studio/core.py` như
  thứ đang có. Cổng tài liệu thêm "bảng không hàng nào thừa ô" (GitHub lặng lẽ bỏ ô thừa, `|` trong backtick cũng
  tách ô): 6 hàng mất chữ ở `CODEMAP.md` software-company, `TRAPS.md`, `dac-ta-tro-ly-kiem-duyet.md`; ba đột biến bộ
  lọc đều đỏ. `CONTRIBUTING` §3: `make eval-record AGENT=all --jobs 3` thật ra chạy `--jobs 1` (cờ của `make`) →
  `JOBS=3`; `eval-record.yml` ghi vì sao chỉ nhận `company`. Docstring `console/submit.py` hết trỏ
  `studio.orchestrator`, `KIEN-TRUC-4-LOP.md` trỏ đúng `loops.js` (#368).
- refactor(audit): **dọn "Việc để lại" của audit hoàn thiện theo tiêu chí đơn giản + chất lượng** (chủ dự án giao
  phiên chính quyết, 2026-09-28). Gỡ ba lớp phòng thủ thừa của F-E: `if text:` ở gateway `client.py` (bộ lọc lúc nối
  `systemInstruction` đã lo, test mới ghim ca message system rỗng nằm giữa) và `getattr` + so `None` ở `_utf8_stdio`
  của gateway `manage.py` lẫn console `__main__.py` (còn một `contextlib.suppress`); giữ `if not cfg.backends:
  continue` ở console vì nó nói ý định. Hai test đổi `os.name` **toàn cục** (gateway `test_account_pool.py`, core
  `test_sandbox.py`) nay chỉ đổi `os` của module được test — đổi toàn cục thì test đỏ sập `INTERNALERROR` không in
  tên ca; test nhánh posix giờ kiểm `chmod` 0600 thật sự được gọi (trước đó bỏ `chmod` vẫn xanh). Rà họ: chỉ
  `os.name` phá báo cáo của pytest, các kiểu vá toàn cục khác trong repo đo vẫn đỏ sạch. ADR gốc 0019, 0026 và
  company 0045 thành Accepted; docstring `xagents_core` hết tả K3.0 và studio. Bảng quyết định ở
  `docs/reports/2026-09-27-audit-hoan-thien.md` §4 (#367).
- fix(audit): **audit hoàn thiện trên main #365 — lối quyết định của người không còn nhận `by` không phải người;
  tắt backend đang được ưu tiên không còn để `routing.prefer` trỏ vào nó; cả năm gói phủ 100% nhánh**. F-A:
  `gate_cli approve|reject|reopen`, quyết gate qua console (cả gate keeper) và `orchestrator decide-change` trả lỗi
  rõ khi `by` không có dạng `human` / `human:<tên>` — trước đây `reviewer:*`/`orchestrator` (ở keeper là mọi tên)
  lọt ACL bus, in "approve"/`ok` mà gate vẫn chờ ở mọi tiến trình khác; `decide-change --by ops` ghi quyết định của
  khách dưới tên agent; vai khác nổ traceback (console: HTTP 500). F-B: `gate_reviewer decide` kiểm `missing_bus`
  như `gate_cli`. F-C: sổ `TRAN_SKIP`/`TRAN_PRAGMA` đếm cả `pytestmark`, marker skip gán vào biến (theo chỗ dùng) và
  `# pragma: no branch`. F-D (lộ ra khi phủ nhánh console): `console/settings.py` sửa bản sao của `routing` rồi chỉ
  gán lại khi khác rỗng — tắt backend duy nhất được ưu tiên thì báo "bỏ ưu tiên" mà file vẫn giữ `prefer` cũ. F-E:
  gateway (27 nhánh) và console (13 nhánh) bật `branch = true`, sổ `CHUA_PHU_NHANH` rỗng; đột biến từng nhánh: 25/27
  và 10/12 đỏ, bốn ca sống là lớp phòng thủ thừa. Báo cáo `docs/reports/2026-09-27-audit-hoan-thien.md` (#366).
- fix(audit): kiểm lại ranh giới đường dẫn khi tìm file, dừng cây tiến trình sandbox, cập nhật console theo WAL, trả lỗi JSON đúng HTTP 400 và đồng bộ cổng local với CI; sửa quyền thực thi script và test Python độc lập PATH. Báo cáo `docs/reports/2026-09-27-audit-hardening.md` (#365).

- fix(khung): **hook `auto-format.sh` chỉ format file vốn đã sạch `ruff format`, không còn làm phình diff**. `dev-task.sh format-file` chạy `ruff format` toàn file sau mỗi Edit, trong khi phần lớn repo cố ý viết gọn một dòng và CI chỉ `ruff check`: sửa 5 dòng `orch/guards.py` thành +82, `orch/gates_flow.py` 399 → 591 dòng (vượt trần 400). Nay chỉ format khi bản trong index đã sạch (`git show :./<file> | ruff format --check --stdin-filename <file> -`) hoặc file mới chưa track; ngoài repo hay git lỗi thì bỏ qua. Đo trên `guards.py`, cùng một dòng thêm: bản cũ +52/−23, bản mới +1/−0. Năm ca mới trong `test_cong_khung.py`, mục `TRAPS.md` §3; có hiệu lực sau khi checkout chính `pull` (#364).
- fix(audit): **Đợt 2–3 của audit 2026-09-27 — routing đọc mốc "resets 10:40pm" và nghỉ lùi dần khi lỗi vận chuyển, hai chỗ nuốt lỗi im lặng, rò kết nối SQLite trong test console** (#363). B5 (`xagents_core.routing`): hết session limit của `claude -p` nghỉ tới đúng mốc giờ đồng hồ trong thông điệp thay vì 3600s cố định; lỗi vận chuyển liên tiếp nghỉ 60→120→…→3600s thay vì hỏi lại mỗi phút (447 lần trên bus thật). B6: `_test_scope_ok` để lại audit `test_scope.worktree_failed`; `Integration.merge` coi `merge --abort` hỏng là lỗi môi trường, không xoá nhánh ticket đã duyệt. B7: test console bật `filterwarnings = error`, đóng kết nối `sqlite3` bằng `closing()`.
- fix(audit): **Đợt 0 của audit 2026-09-27 — `recheck`/`redeploy` thoát 1 khi lượt model lỗi, lệnh không tạo bus ở sai thư mục, `pr-policy` đòi `(#số PR)`** (#362). Báo cáo `docs/reports/2026-09-27-audit.md`. B1: hai lệnh vận hành trả `StepResult`, CLI in lỗi và thoát 1 khi lượt có `error:`/`transient:` (trước đây luôn "đã chạy lại", thoát 0). B3: `missing_bus` — chỉ `run`/`publish` (gate_cli: `request`) được mở bus chưa có; lệnh khác thoát 2 và chỉ đường `companies/software-company/`. C1: `scripts/pr_changelog_check.py` bắt dòng thêm của CHANGELOG mang đúng `(#n)` mà `drift-check` tìm sau merge (main đỏ ở #353, #357). `.gitignore` bắt `-wal`/`-shm`/`.lock`. Sửa chín chỗ tài liệu lệch mã (dãy ADR, số test gateway/company, "bốn package", đường dẫn keeper, K3 đã xong); sổ "Việc để lại" của `TASK-PACK.md` thêm việc treo mới và trạng thái ADR Proposed.
- docs(core): **đối chiếu 15 repo agent với runtime X-Agents** — ghim các tên nguồn đã đổi, bản đồ tính năng/checkpoint/gate/eval/sandbox/MCP đang có và contract để mở adapter khi có ticket thật; không thêm SDK song song (`docs/reports/2026-09-27-agent-frameworks.md`) (#361).

- docs(company): **kết quả chấm lại REL-007 bằng DAST thật** — `recheck` chạy trên CAMPUS-UNI bằng mã `main`: DAST dựng sản phẩm trên cổng trống, đo 24 lần đăng nhập sai đều 401 không 429/`Retry-After`, thiếu CSP; security vẫn `block` nhưng vì T-01 (High) đo được, không còn vì thiếu bằng chứng. Ghi ở `docs/sessions/2026-09-27.md` (#360).
- fix(khung): **`pre-commit-gate.sh` chạy cổng chất lượng trên cây đang commit, không trên checkout chính** (#359). Phép 4 gọi `$ROOT/scripts/dev-task.sh`, mà `dev-task.sh` lấy cây và venv từ `CLAUDE_PROJECT_DIR` = checkout chính. Kết quả: trong phiên worktree, cổng chấm code khác code đang commit. Đo 2026-09-27 từ worktree `release-bang-chung`: hook đỏ `uv trampoline failed to canonicalize script path` (venv chính cũ), trong khi cổng chạy thẳng trong worktree xanh. Nay dùng `CLAUDE_PROJECT_DIR="$CAY" "$CAY/scripts/dev-task.sh"`, lùi về `$ROOT` khi cây không có script, và log in ra cây đang chạy. Test đỏ trước: 2 ca (chặn oan khi checkout chính đỏ; cho qua khi worktree đỏ); 2 đột biến đều bị bắt (bỏ lối lùi; bỏ `CLAUDE_PROJECT_DIR=`). Hook chạy là bản của checkout chính → chỉ có hiệu lực sau merge + `pull` ở đó.
- feat(company): **bằng chứng release-check đủ để security chấm** (ADR-0046 bổ sung, ADR-0047). SBOM/license đọc thêm `package-lock.json` v2/v3, `Cargo.lock` (`cargo metadata --offline` trong sandbox), `go.mod` ở gốc cây RC và thư mục con một tầng. DAST tối thiểu do orchestrator chạy trên đúng cây RC (`evidence.dast`): header bảo mật, trang lỗi lộ debug, cookie, và cửa đăng nhập lấy từ `api-contract` — 12 lần sai khác username / cùng username để đo rate-limit (T-01), một thân JSON hỏng; lời khai của model bị bỏ, verdict không bị ghi đè. Lệnh mới `orchestrator recheck <REL> --by human:x|reviewer:y` chấm lại lượt security của RC cũ, giữ waiver. Đo được: REL-007 CAMPUS-UNI bị chặn vì thiếu DAST và không có đường chấm lại. Chưa làm: khoá tài khoản thật, cookie phiên sau đăng nhập, HSTS/TLS, sản phẩm `runtime.deploy`; yarn/pnpm/npm v1; license Go (#358).
- feat(company): **release-check của security có SBOM + license do máy sinh** (ADR-0046). Trước lượt security trên `release-candidates`, orchestrator đọc `uv.lock` của đúng cây RC, lấy license từ metadata gói trong môi trường khách (`uv run --frozen`, sandbox), chuẩn hoá SPDX khi không mơ hồ và đưa vào `evidence.supply_chain` (CycloneDX 1.5, `sbom_ref=sha256:…`, danh sách `noassertion`/`copyleft`); lời khai của model bị bỏ; verdict không bị ghi đè. Đo được: security chặn mọi RC CAMPUS-UNI (REL-004, REL-007) vì RC không mang bằng chứng nào. Bằng chứng máy trước/sau lượt chấm (QA hồi quy + security) gom vào `orch/verify.py`. Chưa làm: lock khác `uv.lock`, DAST (#357).
- fix(company): **ticket bị từ chối ở gate escalation vẫn `closed` sau khi mở lại bus** (#356). Khi chạy `close_escalated` đặt `closed`, nhưng `rehydrate` chỉ gọi `abandon` nên `ticket.blocked` cũ trong log thắng: ticket đã bỏ hiện `blocked`, chờ người duyệt lại. Test đỏ trước (`blocked` ≠ `closed`), đo hai chiều.
- fix(company): **mở lại bus thì thi hành nốt lần duyệt escalation mà code trước #354 bỏ sót** (#355). Duyệt release / ticket `dispatched` khi event bị bỏ (`unhandled`) chưa được chạy lại và gate đã đóng: `rehydrate` coi lần duyệt đó là lệnh chạy lại chưa kịp chạy (khuôn `event.retried`, không ghi bus). Không phát lại khi dự án đã đi qua lần duyệt: release mà sau đó đã có RC mới (REL-003 duyệt 24/09, sau đó REL-004/005/007 — phát lại là deploy RC cũ đè staging), ticket đã đóng. Đo được 2026-09-26 trên CAMPUS-UNI: REL-007 duyệt 15:44, lượt QA hồi quy bị bỏ 13:42 nằm im, không gate, không watchdog. Test đỏ trước 5 ca, đo hai chiều.
- fix(company): **duyệt escalation của ticket `dispatched` có event bị bỏ thì chạy lại đúng event `tasks` đó** (#354). Trước đây chỉ subject không phải ticket mới được `_retry_unhandled`; ticket mà lượt giao việc bị bỏ vì hoãn `transient:` quá trần chỉ được `resume` rồi nằm im tới watchdog "không hoạt động > 4h" mở gate mới cho cùng việc. Đo được 2026-09-26 trên CAMPUS-UNI: TCK-012/TCK-015 hết quota 13:13–13:43, duyệt 15:43, gate mở lại 15:48. Cùng họ ở nhánh release: duyệt escalation `REL-*` chỉ `_rerun_release` (ops `pending_human`), lượt QA hồi quy bị bỏ vì transient không ai chạy lại — REL-007 nằm im sau duyệt; nay thử thêm `_retry_unhandled`. Test đỏ trước 3 ca (ticket vẫn `dispatched` sau duyệt; cả khi restart giữa lỗi và duyệt; `unhandled[REL]` còn nguyên).
- feat(company): **cầu nối delivery hai chiều, offline và không cấp quyền**: xuất policy/schema từ native
  DeliveryContract; kiểm bundle được pin độc lập, policy, toàn bộ AC và bytes spec trước khi trả contract.
  Không đổi ApprovalLookup, receipt, journal, gate hay run đã đăng ký. Chi tiết và kết quả kiểm thử:
  `docs/reports/2026-09-26-bidirectional-delivery-handoff.md` (#353).
- feat(claude): **auto-compact native ở cửa sổ 300000 token mỗi phiên, giữ trạng thái thi hành qua compact** (#352). `.claude/settings.json` bật `autoCompactEnabled` + `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, `CLAUDE.md` thêm Compact Instructions, `docs/AUTO-COMPACT.md`, 7 test cấu hình offline ở console. Dòng này bổ sung vì `drift-check` đòi (bắt ở PR kế tiếp).

- feat(company): **phiên chính quyết mọi gate trừ spec — phạm vi `rong` của reviewer có chữ ký** (#351). ADR gốc 0025 (Accepted, chủ dự án quyết 2026-09-26: *"phiên chính tự quyết định thay tôi làm hết mọi thứ, trừ duyệt spec ban đầu"*). `COMPANY_GATE_REVIEWER_SCOPE=rong`: reviewer `approve`/`reject` mọi gate — escalation (kể cả `REL-*`, nợ kiến trúc), release, acceptance — trừ `spec`, không trần; vẫn đường chữ ký Ed25519 của ADR gốc 0024, ký `reviewer:phien-chinh`, không bao giờ `human:*`. Nghiệm thu do reviewer duyệt đóng ticket như sàn ADR-0043 (`machine_acceptor`), khách ký khác `accepted` sau đó vẫn thắng. Bỏ biến = quay về S2, quyết định ngoài S2 thôi được tin khi replay. Test đỏ trước 8 ca + 1 ca vòng thật (ticket kẹt `released`); 7 đột biến đều bị giết.
- fix(company): **người mở lại ticket thì trần "làm tiếp" và trần xung đột merge về 0 cùng `retry`** (#350). `DeliveryLead.reopen` đếm `retry` lại từ 0 nhưng `turn_continuations` (#345) và `conflict_retries` thì không: ticket đã dùng hết ba lần làm tiếp, sau khi người duyệt escalation `approve` thì lần hết lượt tool đầu tiên đã tính retry. Nay nhánh mở lại ghi audit `ticket.reopened` (chỉ tin người ghi `orchestrator`) và xoá hai bộ đếm, `_rehydrate` làm đúng như vậy khi restart. Chặn trước lệnh mở lại TCK-011/TCK-015 của CAMPUS-UNI. Test đỏ trước: 2 ca (3 ≠ 6 lần làm tiếp; bộ đếm xung đột còn 1 sau restart); 3 đột biến đều bị giết.
- docs: **điền số PR #348 vào CHANGELOG, nhật ký phiên và ADR gốc 0024** (#349). PR theo luật 10 sau #348; dòng này bổ sung vì `drift-check` đòi mọi PR merge sau mốc §10 có dòng riêng (bắt được ở #350).
- feat(company): **reviewer gate có chữ ký — phiên Claude độc lập mở lại ticket/dự án bị chặn** (#348). ADR gốc 0024 chuyển Accepted; chủ dự án giao phiên chính chốt: S2, trần 1 lần mỗi subject, khoá file ngoài repo, chạy theo lệnh qua skill `/gate-review`. `gate_reviewer.py`: actor `reviewer:<id>` (không giả `human:*`), chữ ký Ed25519 trên subject/decision/by/reason/thế hệ gate/hash hồ sơ; nhánh tin cậy `trusted_reviewer` sau `trusted_autoapprove`, core không đổi. Chỉ `approve` escalation checklist `decision:reopen|close`/`decision:retry|close`, không `REL-*`; cờ `COMPANY_GATE_REVIEWER` mặc định tắt. Test đỏ trước 18 ca; 9 đột biến đều bị giết (ca `by==actor` sống lần đầu → thêm test reviewer ký dưới tên người). Trần đã biết: khoá cùng user OS, F1 của ADR gốc 0023.
- docs: **ADR gốc 0024 (Proposed) — một phiên Claude độc lập được mở lại ticket bị chặn, actor `reviewer:<id>` có chữ ký Ed25519, không giả `human:*`** (#347). Đo trên bus thật: 11/13 escalation đã quyết là `approve` với lý do `retry|reopen`; 4 gate chờ ~34 giờ. Phiên chính không độc lập (là tác giả #345 và hint cần duyệt; lệnh duyệt bị chặn *Self-Approval*), actor chỉ dựa vào tên có đúng lỗ F1 của ADR gốc 0023. Phạm vi đề xuất: chỉ `approve` (mở lại/chạy lại) escalation ticket và dự án; spec, release, chấp nhận finding vẫn là người. Năm câu hỏi chờ chủ dự án.
- fix(ci): **`block-dangerous-git.sh` hết chặn oan khi `main` nằm ở lệnh khác cùng dòng** (#346). Hook dò `main` trên cả chuỗi lệnh nên `git push -u origin x && gh pr create --base main` bị coi là push vào `main` (đo được 2026-09-26 khi mở #344). Nhánh 1 nay xét từng đoạn tách ở `&&` `||` `;` `|`. Test đỏ trước: 2 ca chặn oan; 3 ca mới canh push `main` ở đoạn sau vẫn bị chặn.
- fix(company): **công ty tự chạy tiếp thay vì chờ người ở hai lỗi hạ tầng đo được khi chạy thật** (#345). Rà `diagnose` trên dữ liệu CAMPUS-UNI (39 ticket, 2 blocked kéo 32 waiting, 4 gate escalation chờ). (1) Builder hết lượt tool (`error_max_turns`, 8 lần) mà worktree có tiến độ → làm tiếp từ WIP, không tính retry, tối đa `MAX_TURN_CONTINUATIONS=3` lần mỗi ticket (`turn_continuations`, bền qua restart qua audit `ticket.continued`, chỉ tin người ghi `orchestrator`); worktree sạch hoặc lỗi khác vẫn retry như cũ. (2) `error_max_structured_output_retries` → tự thử lại đúng một lần mỗi (event, agent) qua đường hoãn `transient:` sẵn có (`llm.autoretry`, khoá `once`), lần hai mới mở gate. (3) `deploy.py` hai chỗ giải mã `encoding="utf-8"` thiếu `errors=` — họ lỗi #329 còn sót: script khách in byte lạ thì Windows mất output lặng lẽ, Linux ném khỏi deploy. Test đỏ trước cho cả ba; đo chiều ngược 7 đột biến đều bị giết (bỏ trần thì `run()` lặp vô hạn).
- docs: **ADR-0023 (Proposed) — mã khách ghi được quyết định gate khi `sandbox: auto` tụt về `subprocess`** (#344). Tái hiện F1 của `sc-security` có đối chứng. Tiến trình con chỉ dùng stdlib, chạy qua `SubprocessSandbox`, `INSERT` được `gate.decide` mang actor `human:*`, hoặc `orchestrator` trên `UAT-*`, và gate được duyệt; `run --watch` nhận dòng đó qua `poll()`. Gốc lỗi: ACL của bus chỉ chạy lúc `publish`. Đề xuất `auto` fail-closed khi thiếu runtime, chờ người chọn. `SECURITY.md` ghi hệ quả với gate. Đóng trạng thái Q1–Q7 (#335) và N6 (#343); `pt.4` ghi lý do chặn mới.
- feat(company): **pe2-duyet — Ready xác minh người ký spec thật từ bus, `--quality-trust` cho orchestrator** (#343). `spec_approval.BusApprovalLookup`: người ký gate `SPEC-<pid>` (actor người, thế hệ mới nhất) kèm profile chính họ ghim là nguồn sự thật của `approved_by`; `submit_quality` dùng nó mặc định. `orchestrator --quality-trust <registry>`; `quality_execution commit --db <bus>` (phải là bus cạnh `--journal`). Bổ sung ADR-0021. `sc-security` nêu F1–F5; F2–F4 đã sửa kèm test đỏ trước, F1/F5 ghi thành trần.
- feat(core): **pe2-noi2 — `quality:accept` chấm lại được khi candidate đổi sau `SUCCEEDED`** (#342). N5 theo ADR-0022, phương án (a). Chủ dự án trả lời bốn câu hỏi, và ADR chuyển sang Accepted. Core thêm event thứ bảy `task.reopened` và `TaskSpec.reopenable`: chỉ task lá được mang cờ, khoá chỉ ghi khi `True` nên byte RunSpec cũ giữ nguyên (ghim bằng chuỗi chụp từ trước N5). Company: run mới đánh dấu `quality:accept`. Sha staged đổi sau khi đã đạt thì run tự mở lại và chấm ở sha mới; R6 vẫn chặn tới khi có kết quả mới. Run đăng ký trước N5 không migrate và giữ hành vi cũ. Attempt lặp lại mang hậu tố `~<n>`, sửa luôn lỗi `quality:accept` kẹt `READY` khi candidate quay về RC đã chấm. Theo review `sc-security`: R6 đọc trạng thái và candidate từ một snapshot (`runs_for_release` chuyển sang `orch/quality_release.py`), cache `_quality_done` bị xoá khi attempt khác đang mở, và kết quả nộp muộn cho attempt cũ bị từ chối thay vì đánh FAILED attempt đang chạy.
- docs: **pe2 — ADR-0022 nghiệm thu lại khi candidate đổi (Proposed), đóng bảng B** (#341). Đề xuất event `TASK_REOPENED` cho task `reopenable`, không đổi byte của RunSpec cũ. N1–N4 = xong #340; N5 chờ người duyệt ADR.
- feat(company): **pe2-noi — orchestrator chạy nghiệm thu quality contract** (#340). N1 theo ADR-0021 (Accepted), gồm các phần sau. `orch/quality_flow.py` đăng ký một run cho mỗi plan và chạy `quality:accept` qua trusted driver ở cuối `_mark`. `approve SPEC --quality-profile` ghim profile; chỉ người ghi được, và console cũng tuân theo. Agent không được giao `quality:` và không có đường ghi journal. Candidate là sha đã staged của RC. Dự án không có profile chạy y hệt trước. N2: sàn ADR-0043 thêm gap R6 mang blocker khi `quality:accept` chưa đạt ở đúng sha đã staged, khi ticket nằm ngoài run, hoặc khi journal lỗi. N3: console có khối "Quality contract" đọc journal chỉ đọc. N4: ADR-0018 Accepted, cập nhật CODEMAP và PRODUCT-EXCELLENCE.
- feat(company): **pe2-ky — receipt ký Ed25519, verifier không giả được reviewer** (#339). ADR-0020 (Accepted, chủ dự án đồng ý thêm `cryptography` 50.0.1, kéo theo `cffi` và `pycparser`). Registry chỉ giữ public key có `key_id` và `not_after`. Contract có `allowed_schemes` được compile thành `product-excellence/4` và từ chối HMAC. Receipt HMAC v2 vẫn verify được với byte giữ nguyên. Có test giả mạo từ mọi byte trong registry, sửa evidence hoặc chữ ký, và key hết hạn.
- fix(company): **pe2-cung — CAS, target theo check và Ready thật cho quality contract** (#338). P1: `commit_quality_result` dùng đúng snapshot history đã đọc làm `expected_count` (tham số của caller thành tuỳ chọn), `ExecutionJournal.append` thành alias deprecated của `_append_unchecked`, và có test cổng cấm `src/` ghi journal không qua `transition`. P2: `QualityTarget.check_id` và `ProjectProfile.evidence_policy` có trần. `product-excellence/3` chỉ dùng khi profile có trường mới, hash v2 được ghim. P3: `ready_gaps` kiểm tự duyệt (principal đã chuẩn hoá), thời điểm duyệt, hash spec và record duyệt qua `ApprovalLookup`. Không có lookup thì không PASS.
- ci: **pe2-quytrinh — chặn merge khi Definition of Done còn ô mở** (#337). Bước mới trong job `metadata` của `pr-policy.yml` chạy `scripts/pr_dod_check.py`: mục `## Definition of Done` hoặc `## BÁO CÁO XÁC THỰC…` còn ô `- [ ]` thì đỏ, trừ ô ghi `(sau merge)`. Thân #335 nguyên văn là fixture chiều ngược. Đoạn "Mục tiêu chất lượng sản phẩm" trong `AGENTS.md` rút từ 11 dòng xuống 4.
- docs: **đánh giá #335 và đặc tả Product Excellence v2** (#336). Bản đánh giá `docs/reports/2026-09-25-danh-gia-pr335.md` (adapter chưa có caller runtime, HMAC khoá chung, Ready chỉ kiểm cấu trúc, CAS dựa vào caller, merge khi DoD còn ô mở) và kế hoạch `docs/thi-hanh/pe2.md` gồm bốn hạng mục pe2-quytrinh → pe2-cung → pe2-ky → pe2-noi. Không đổi code.
- feat(company): **tiếp thu projects-template có chọn lọc** (#335). Thêm DeliveryContract/DeliveryReport Ready–Done–Complete, gate không nhận no-op là PASS, source pin theo commit/blob và nối vào assessor/journal sẵn có; giữ bytes/hash/signature v2 khi opt-out. Bổ sung 60 ca, design precedence và chẩn đoán lỗi đúng tầng; không copy dispatcher/CI/agent registry.

- feat(company): **product-quality contract theo dự án/ngành nối vào execution kernel hiện có** (ADR gốc 0018) (#335). Thêm profile/Design Brief, receipt checker, RunSpec/TaskResult adapter và `/product-goal` nối `/thi-hanh`; giữ sàn tự duyệt ADR-0043 và 6 agent. Thêm 126 test company cùng 25 test core; sửa đóng kết nối SQLite khi khởi tạo journal hỏng. Gia cố ADR-0019: transition/đăng ký run nguyên tử, CAS chống kết quả cũ, ACK idempotent và lưu kết quả nghiệm thu cùng bằng chứng; bỏ skip symlink bằng test ranh giới đa nền tảng, không tăng trần CI. Đây chưa là migration H7 hay runtime tự chủ đầy đủ.
- feat(core): **execution harness kernel H1+H2 — RunSpec/TaskSpec DAG, state machine replay được, EvidenceReceipt và SQLite journal append-only** (#334). Phiên chính giữ intent/quyết định; execution state chuyển dần về code có type/test theo ADR-0017. PR này mới là foundation: `/thi-hanh` vẫn dùng state hiện tại cho tới bridge H7, không tuyên bố migration đã xong.
- fix(core): **`SubprocessSandbox` hết giờ thì giết CẢ CÂY tiến trình, không treo vì cháu còn giữ ống** (#333). Đo thật CAMPUS-UNI/TCK-002 2026-09-24: tool `run test` (`uv run pytest`) quá 600s, `subprocess.run` chỉ giết `uv.exe` rồi trên Windows `communicate()` KHÔNG trần — pytest thật (cháu) còn giữ ống stdout nên orchestrator 0% CPU, 0 event suốt 20+ phút trong khi pytest mồ côi ăn 1245s CPU; trên POSIX không treo nhưng cháu thành mồ côi. Nay runner mặc định `_run_tree`: POSIX `start_new_session` + `killpg`, Windows `taskkill /T /F`, rồi chờ ống tối đa 5s. Test đỏ trước: `test_subprocess_timeout_giet_ca_cay_tien_trinh_khong_treo_vi_chau_giu_ong` (tiến trình thật: cha sinh cháu giữ ống). Họ lỗi cùng khuôn còn ở `xagents_core.llm` (`claude -p`/`codex exec` qua `subprocess.run(timeout=)`) — chưa treo thật vì cầu MCP tự thoát khi CLI chết; để PR riêng nếu gặp.
- build(deps): bump `anthropic` 1.5.0 → 1.7.0 (dependabot) (#332)
- build(deps): bump `ruff` 0.16.7 → 0.16.8 (dependabot) (#331)
- fix(company): **lượt MCP của `claude -p` có trần thời gian chứa được thời gian tool chạy, không còn bị giết giữa chừng khi builder chạy test hai lần** (#330). Đo thật CAMPUS-UNI/TCK-002 2026-09-24: trần cứng 900s cho CẢ tiến trình `claude -p` (gói cả vòng tool, ADR-0024) trong khi một lần `run test` được phép 600s — builder chạy test lần hai là bị giết, mất trắng việc của lượt, routing coi là lỗi vận chuyển và thử lại y hệt: 4 lượt × 900s, bus im lặng 1 giờ, 0 event, rồi backend bị cho nghỉ. Nay `ToolBox.run_timeout` (core) khai trần mỗi lệnh của bảng; lượt MCP dùng `timeout + MCP_SLOW_TOOL_RUNS(3) × run_timeout` (900 + 1800 = 2700s), theo thread, lượt không tool giữ 900s. Test đỏ trước: `test_mcp_tran_thoi_gian_cli_chua_du_cho_tool_chay_lau`.
- fix(company): **lời gọi git/gh không còn chết khi repo khách có byte không phải UTF-8** (#329). Đo thật CAMPUS-UNI/TCK-001 2026-09-24: tài liệu bằng chứng chứa log console Windows cp1252; `git diff` của PR in ra byte `0xe3`, luồng đọc của `subprocess` chết với `UnicodeDecodeError`, Windows trả `stdout=None` → `'NoneType' object has no attribute 'strip'` trong handler QA → ticket rơi về escalation dù code không sai. Năm chỗ giải mã `encoding="utf-8"` không kèm `errors=` (`workspace._git`, `_git_ok`, `Integration.merge`, `gate_brief._git`, `github_pr._gh`) nay `errors="replace"`. Họ lỗi cùng khuôn còn ở keeper (7 chỗ) và console (`git_truth.py`) — tách việc riêng. Test đỏ trước: `test_git_khong_chet_khi_repo_khach_co_byte_khong_phai_utf8`.
- fix(company): **ticket bị chặn lại sau restart vẫn mở gate escalation — `_rehydrate` chỉ đếm `gate.decide` đã xử lý** (#328). Đo thật CAMPUS-UNI/TCK-001 2026-09-24: `_rehydrate` đếm MỌI `gate.decide` trong log vào `escalation_decided`, kể cả quyết định còn trong hàng đợi; khi decide đó chạy, `_on_gate_decide` đếm thêm lần nữa → bộ đếm sống lệch bộ đếm dựng lại. Khoá `once` đã dùng :0, :2, :3; restart dựng lại 3; lần chặn lúc 10:09 sinh đúng khoá `escalation:TCK-001:0:blocked:3` → `once` nuốt, `gates_pending` rỗng, `status` chỉ báo "không có việc nào chạy được", 38 ticket phụ thuộc đứng im. Nay chỉ quyết định có dấu `orchestrated` mới được đếm lại. Test đỏ trước: `test_chan_lai_sau_restart_van_mo_gate_khi_decide_tung_cho_trong_hang_doi`.
- fix(company): **lint/test của repo khách chạy bằng môi trường CỦA KHÁCH, không phải venv của công ty (ADR-0044)** (#327). Đo trên CAMPUS-UNI/TCK-001: `stacks.PY` ghép argv bằng `sys.executable` — Python của orchestrator — rồi chạy trong worktree khách, nên `pytest` chết ở khâu collect (`No module named 'django'`) với MỌI code builder viết ra; ticket quay đủ 3 lượt rồi `ticket.blocked`, bằng chứng trên bus đổ lỗi cho builder trong khi lỗi nằm ở hạ tầng, và dính mọi ticket Python của mọi dự án khách. Nay `detect()` đọc `pyproject.toml` bằng `tomllib`: khách khai `[project]` + công cụ (`pytest`/`ruff`, kể cả trong `[dependency-groups]`/`[project.optional-dependencies]`) thì lệnh đó chuyển sang `uv run` — mỗi lệnh quyết định riêng, cùng khuôn `_node_stack`. Khách không khai công cụ, chỉ có `[tool.*]`, `setup.cfg`/`requirements.txt`, hoặc file TOML hỏng → giữ đường cũ thay vì đổi màu đỏ hạ tầng này lấy màu đỏ hạ tầng khác. Cái giá đã ghi thẳng trong ADR: `uv run` cài gói từ `pyproject.toml` do chính model viết — mở rộng ranh giới tin cậy có chủ đích, người vận hành đã chọn; backend `subprocess` chưa thật sự tắt mạng và chưa có lọc egress, cần ADR riêng.
- feat(company): **kế hoạch bị `_check_plan` từ chối thì máy tự trả `product[plan]` sửa trước khi hỏi người; reload `execv` hỏng không còn giết orchestrator im lặng** (#326). Đo thật CAMPUS-UNI 2026-09-22: hai lần liên tiếp dự án đứng ở gate `escalation` chờ người gõ "retry" cho một việc máy tự làm được. Nay `PLAN_REWORKS` (=1) lượt tự sửa cho mỗi event nguồn, lượt sửa mang `hint` + `previous_plan` (cùng khuôn `_spec_runtime_missing`), audit `plan.rework`; quá thì `plan_rejected` + gate như cũ; người duyệt retry ⇒ lại có lượt tự sửa; bộ đếm `plan_reworks` dựng lại từ audit (`plan.rework` + `plan_rejected`), chỉ tin `product`/orchestrator ghi. `run --watch`: `_reexec` ném `OSError` → audit `orchestrator.reload_failed`, chạy tiếp mã cũ với reload tắt thay vì thoát sau khi đã trả lease. Kèm: gộp `main` vào #325 và điền số PR cho nó. Audit đầy đủ (hai trợ lý rà điểm chờ người và điểm treo/đốt tiền, 24 điểm) ở `docs/sessions/2026-09-23.md`.
- fix(company): **bốn chỗ kẹt im lặng sau khi người chốt yêu cầu — công ty tự đi tới cùng hoặc hỏi người qua gate** (#325). (1) `product[plan]` lỗi `RunnerError`/`LLMError` nay đi đường `_mark_unhandled` (gate `escalation` dự án, duyệt = chạy lại) thay vì `_mark` rồi im; (2) threat model `block` mở gate `escalation` thay vì chỉ audit; (3) câu hỏi làm rõ không ai trả lời quá `COMPANY_CLARIFY_TIMEOUT_H` (mặc định 24h) → orchestrator ghi `clarification.assumed` (lấy `default` của từng câu) và chạy pha `spec` từ draft — người vẫn ký gate `spec`; (4) event hoãn `transient:` quá `COMPANY_TRANSIENT_MAX_H` (mặc định 2h) → escalation thay vì thử lại mỗi nhịp vô hạn. Tách `_mark_unhandled` khỏi `_after_error`; `pending_clarifications` mang `event_id` và bỏ vòng đã giả định. Audit đầy đủ: `docs/sessions/2026-09-23.md`.
- fix(company): **đóng 3 lỗ `sc-security` để ngỏ ở ADR-0043** (#324). `_rehydrate` chỉ áp action khi `env.actor` là người ghi thật (`TRUSTED_WRITERS`), không tin tên action hay `actor` tự khai — gốc lỗ: route `change-requests → product → audit-log` publish payload model, nay ép `action=change.impact`; đầu ra của route đọc `tasks`/`pull-requests`/`test-suites` mang đúng `ticket_id` của đầu vào (`output.subject_overridden`); đo được agent không tự ký `acceptance-results` (không route nào xuất nó, CLI chỉ nhận actor người) — canh bằng test thay vì đổi hợp đồng agent (cần eval-record model thật).
- feat(company): **ADR-0043 — sau khi người ký spec, công ty tự duyệt release (= deploy production) và nghiệm thu khi bằng chứng MÁY đạt sàn chất lượng** (#323). Sàn cứng `quality_floor.floor_gaps` (lint+test PR do workspace chứng, sản phẩm chạy ở đúng sha staged, QA/security pass, không finding được miễn, chưa từng sự cố; nghiệm thu thêm deploy production đúng sha); dự án nâng mức lúc ký spec bằng `gate_cli approve SPEC-x --quality-bar` (chỉ siết); thiếu bằng chứng → người, kèm `gate.auto_skipped`. Máy nghiệm thu không ghi `acceptance-results`; khách ký khác sau đó → escalation. Sửa kèm: `scheduler` bỏ qua quyết định do `code` tự duyệt (lỗ từ adr113). Review `sc-security` vá 5 khoảng trống trong cùng PR: verdict release chỉ tính khi là phản hồi cho sự kiện của chính release và `run` chỉ lấy từ audit của orchestrator; replay chỉ tin `acceptance.auto`/`release.staged` do orchestrator ghi; không ai ký tay được dưới tên `code`; hàng luật chỉ đóng được gate đúng loại. Cờ `COMPANY_GATE_AUTOAPPROVE` vẫn mặc định tắt; `spec`/`escalation` luôn là người.
- fix(company): **audit 2026-09-23 đợt 2 — sửa nốt phần còn lại, mỗi bản sửa có test đỏ trước** (#321). Nối tiếp #320 (đợt 1 + keeper). company: duyệt escalation sự kiện không-ticket mất sau restart; deploy production, hồi quy QA và tool chỉ đọc của QA chạy ở đầu nhánh tích hợp thay vì sha đã staged; merge hỏng không-xung-đột bị coi là xung đột và xoá nhánh ticket đã duyệt; probe loopback đi qua `http_proxy`. core: container sống sau timeout/kill; mirror blackboard theo `project_id` ra ngoài store; routing phân loại chữ do model viết; `Lease` không nguyên tử. gateway: non-stream 5xx làm nguội tài khoản; ghi cooldown chặn event loop; `index` tool call stream đếm lại từ 0; discovery hỏng dò lại mỗi request; callback OAuth sai `state` huỷ đăng nhập. console: một event keeper sai schema làm `/api/state` 500; ghi `llm.yaml` mất quyền 0600; `/api/settings` không kiểm kiểu. Chưa sửa (cần quyết định): `docs/sessions/2026-09-23.md`.
- fix(company): **audit 2026-09-23 — năm lỗi đã tái hiện, sửa kèm test đỏ trước** (#320). (1) `glob` của `list_files`/`search` thoát khỏi worktree bằng `../*` (đọc được repo khách, `company.sqlite`); (2) `ticket_id` do agent đặt như `..`/đường dẫn tuyệt đối biến worktree thành checkout của khách — nay `workspace()` trả `None`; (3) tên compose project giữ chữ hoa (`company-QLKH-staging`) nên compose từ chối, mọi deploy compose đều hỏng — nay hạ chữ thường; (4) keeper `bump_dependency` không có ranh giới tên gói (`pytest` sửa cả `pytest-cov`, `[tool.pytest.ini_options]`) và coi `new_spec` là mẫu regex; (5) gateway: refresh token gặp 429/5xx bị coi là Google từ chối → cooldown 5 phút cả pool. Danh sách lỗi còn lại chưa sửa ở `docs/sessions/2026-09-23.md`.
- build(deps): bump `ruff` 0.16.6 → 0.16.7 (dependabot) (#316)
- build(deps): bump `anthropic` 1.4.0 → 1.5.0 (dependabot) (#317)
- fix(company): **kế hoạch thiếu `risk_tags` tự sửa thay vì `plan_rejected` cả kế hoạch; thêm tiêu chí phá thế
  bế tắc cho gate** (#322). Đo thật 2026-09-22 (CAMPUS-UNI): `_check_plan` từ chối cả kế hoạch 2 lần liên tiếp
  chỉ vì một ticket thiếu `risk_tags` suy được thẳng từ `RISK_HINTS` — mỗi lần tốn một lượt `product[plan]`
  đầy đủ (model thật) để sinh lại từ đầu. Nay `HINT_TO_TAG` (`events.py`) ánh xạ hint đã biết sang đúng tag,
  `_check_plan` tự gắn và ghi audit `risk_tags_autofixed` thay vì từ chối; hint không suy được tag vẫn bị từ
  chối như cũ, không đoán bừa. `_check_plan`/`_cycle` dời từ `ticket_fsm.py` (đã 479 dòng, vượt trần 400) sang
  `orch/guards.py`. Kèm `gates/checklists.md`: một tiêu chí chung cho mọi gate — bằng chứng mơ hồ giữa nhiều
  phương án kỹ thuật hợp lệ thì nghiêng về chất lượng cao nhất và phiên bản/nền tảng mới nhất đã ổn định (≥3
  tháng).
- fix(company): **audit 2026-09-22 — ba lỗ cơ chế và một lớp tài liệu trôi** (#319). (1) Dự án chờ người trả lời câu hỏi làm rõ nay hiện ở `status.clarifications_pending` + `warnings`, và ở hàng đợi gate của console (`CLARIFY-<pid>`, `decidable=false`) — trước đó pha intake/research/spec mù hoàn toàn (CAMPUS-UNI đứng im từ 13:11, không ai biết). (2) `_superseded_release` nhận RC trùng ở CUỐI danh sách (TRAPS "chưa vá" từ 09-10): void thay vì đá ticket đã giao về rework. (3) Khoá `uat:{rid}` mang thế hệ `event_id`: deploy lại sau khi khách từ chối mở lại gate nghiệm thu. (4) Cổng mới `test_codemap_duong_dan.py`: mọi đường dẫn backtick trong `CODEMAP.md`/`ARCHITECTURE.md`/`CLAUDE.md` của company phải tồn tại — bắt 14 đường dẫn sai sau lần dời `platform/`; sửa kèm ARCHITECTURE (ADR 0001–0042), README package (deploy đã nối vào release; 1282 ca / 77 file), 4 ADR trỏ file đã dời vào `docs/archive/`, ghi chú đối chiếu ADR-0033/0034/0036, `thresholds.yaml` nói rõ "100%" là replay chứ không phải `score`. `_deadlock_warnings` dời sang `orch/scheduler.py` (K1.8).
- fix(gateway): **ghi file token không còn mất im lặng trên Windows; README hết conflict marker** (#318).
  `os.replace` thỉnh thoảng trả `WinError 5` khi Defender/indexer giữ file đích; `_update_account_fields` nuốt
  lỗi nên cooldown và `last_used_at` mất mà không ai biết — đó là nguồn của test LRU "chập chờn" (đo 1/8 lượt
  đỏ). `_atomic_write` nay thử lại có giới hạn khi `PermissionError`, sau sửa 20/20 lượt xanh. Kèm: `README.md`
  mang nguyên hai nhánh conflict từ #307 suốt một tuần mà không cổng nào đỏ; giải conflict và thêm cổng
  `test_khong_file_nao_con_conflict_marker` quét mọi file git theo dõi.
- docs(sessions): **xoá worktree là xoá luôn state của công ty; engine treo im lặng khi chạy nền** (#315).
  State QLKH (`company.sqlite`) mất cùng worktree bị dọn ở #298 vì phép dọn tra "commit đã merge chưa" mà
  file state thì không theo dõi. Dựng lại dự án từ yêu cầu mới trên đúng code khách còn nguyên. Ghi cả khuôn
  chưa giải: `run` khởi động bằng `nohup` thì sống + giữ lock + `status` xanh nhưng 0 lượt model, foreground
  thì chạy ngay. Kèm một bài học về phép đo: cửa sổ quan sát 6 phút trên hệ có chu kỳ ~160 s không phân biệt
  được *treo* với *đang chạy lượt đầu* — "không đổi" là dữ liệu rỗng, không phải bằng chứng phủ định.
- docs(khung): **`pt.8` chờ người — subscription không đóng được ngưỡng eval** (#314). Đo bằng
  `provider: claude-code` (subscription, ADR-0019): bốn câu chống over-engineering cho `builder.md` làm điểm
  eval tệ đi thật (0.54 → 0.23), nhưng ngay cả prompt gốc cũng dưới xa `min_pass_ratio: 0.95` — client này
  không có đường cấp tool cho `builder` trong chế độ eval (`run()` không truyền `tools=`, khác
  `generate_in_workspace()`). Không commit bản ghi điểm thấp; cần backend có tool thật hoặc sửa harness
  (việc kiến trúc, ngoài phạm vi `pt.8`) trước khi ghi lại được. `pt.4`/`pt.5` vẫn chờ người (đo `SubagentStart`
  bị classifier auto-mode chặn tự sửa cấu hình).

- docs(sessions): **đo nốt backend `chatgpt-sub` (codex), khép mục treo cuối của phiên 2026-09-15** — `probe`
  theo thiết kế chỉ dò backend `claude-code`, nên đo bằng một lượt `complete` tối thiểu qua chính adapter:
  **chạy được** (7,0 s, `gpt-5.6-terra`, 14.198 token), rồi lượt ngay sau **hết hạn mức gói**. Hết hạn mức
  KHÔNG phải hỏng cấu hình — `routing.is_quota_error` khớp đúng chuỗi đó (thử bằng thông điệp thật → `True`),
  nên backend nghỉ `cooldown_s` và lượt đó tự đi backend kế, đúng ADR-0019. **Không tool-use**:
  `xagents_core/llm.py:783` ném thẳng, là thiết kế adapter chứ không phải thứ dò ra được. Ghi kèm một nghi ngờ
  **đã tự bác bỏ**: tôi tưởng quota bị ném thành `LLMError` (thay vì `TransientError`) sẽ làm routing không
  failover — tức guardrail ADR-0019 thành no-op; đo ra thì routing phân loại theo **thông điệp** chứ không theo
  lớp ngoại lệ. Không đổi một dòng mã nào. (#313)
- docs(sessions): **chốt phiên 2026-09-15** — sáu PR (#304, #307, #308, #309, #310, #311) và một sợi chỉ xuyên
  suốt đáng đọc trước khi làm tiếp: bốn lỗi khác nhau trong phiên (#299, #307, #310, #311) **cùng một khuôn** —
  *phép thử lệ thuộc môi trường ở chỗ không ai nghĩ tới* (máy có WSL · thứ tự merge · `$HOME` có `llm.yaml` ·
  **phiên bản Python**) — và cả bốn đều vô hình với CI. Rút ra: **CI xanh không chứng minh phép thử đúng, chỉ
  chứng minh nó đúng trong đúng ô môi trường CI đứng**; một ca đỏ "chỉ trên máy tôi" thường là phép thử đang
  nói thật về một ô CI không phủ, và lần thứ ba trong phiên nó hoá ra là lỗi **sản phẩm** chứ không phải máy
  bận. Mục "Kết phiên" giữa phiên được giữ nguyên chứ không sửa cho khớp hiện tại — sửa một bản ghi quá khứ
  cho khớp hiện tại là đúng thứ nhật ký phiên tồn tại để chống. (#312)
- fix(core): **span đo được khoảng ngắn — `observe` đổi từ `time.monotonic_ns` sang `time.perf_counter_ns`.**
  Cả hai đều `monotonic=True`, nhưng trên Windows + CPython **≤ 3.12** `time.monotonic` là `GetTickCount64()`
  phân giải **15,625 ms**: mọi span ngắn hơn một tick báo `duration_ms = 0.0` — module sinh ra để đo thời gian
  lại mù đúng khoảng ngắn. `perf_counter` là `QueryPerformanceCounter()`, phân giải **1e-7 s** trên cùng máy,
  và chính là đồng hồ `company/runner.py:473` đã dùng cho `duration_ms` của lượt model — nên bản vá làm
  `observe` khớp lại với lựa chọn sẵn có của repo chứ không đặt ra lựa chọn mới. Triệu chứng là hai ca
  `test_observe` đỏ **chập chờn** (`sleep(0.002)` chỉ vượt tick khoảng 13% số lần) và chỉ trên máy chạy Python
  ≤ 3.12: CI không bao giờ thấy vì Linux dùng `clock_gettime` phân giải ns, còn job Windows chạy 3.13 (CPython
  đổi sang QPC từ 3.13). Cổng mới `test_span_dung_dong_ho_du_min_de_do_span_ngan` đo bằng `get_clock_info`
  thay vì bằng `sleep` — phép thử dựa trên `sleep` chính là phép thử chập chờn vừa phải vá. Kèm sửa một ca
  **xanh rỗng**: `test_sink_none_la_no_op_that_su` vá `observe.time.monotonic_ns` nên sau khi đổi đồng hồ nó
  vẫn xanh mà không còn chứng minh gì; nay vá đúng `observe._now_ns`. Đo hai chiều dưới Python 3.11: tắt bản
  sửa → 3/3/2/2 đỏ qua bốn lần chạy, bật → 17 xanh bốn lần liền. (#311)
- fix(tests): **bộ test không còn đọc cấu hình model THẬT của máy đang chạy nó** — từ ADR-0016, `load_config()`
  đọc tầng máy `~/.config/xagents/llm.yaml` **dù có truyền `path` hay không**, nên mọi ca chạm
  `load_config`/`explain_config` mà không tự đặt `XAGENTS_LLM_CONFIG` đều lệ thuộc vào việc máy có file ấy hay
  không. Đo ngay sau khi tạo file theo đúng ADR: **3 ca đỏ** — 2 ở `xagents-core` (một trong đó,
  `test_khong_co_file_thi_van_ra_cau_hinh_mac_dinh`, có từ **trước** ADR-0016: bản vá #303 làm hỏng phép thử cũ
  mà CI không thấy) và `test_probe_cli_exits_nonzero_when_no_claude_backend` (tầng máy cấp sẵn backend
  `claude-code` nên probe không còn "không có backend" để báo). Khuôn lỗi nguy đúng chỗ khó đoán: xanh trên CI
  (máy sạch) và xanh ở máy chưa làm theo ADR, **đỏ đúng lúc người phát triển làm theo ADR** — cổng phạt người
  làm đúng. Vá ở `conftest.py` của cả hai gói (`autouse`, `Path.home()` trỏ tmp riêng) chứ không vá từng ca,
  vì đây là một HỌ chứ không phải ba chỗ. Đo hai chiều: tắt fixture → 3 đỏ, bật → xanh. (#310)
- docs(sessions): **kết phiên 2026-09-15 + ghi lại phép dọn nhánh theo bằng chứng** — `git branch --merged`
  NÓI DỐI ở repo này vì mọi PR đều squash-merge (107 nhánh local, chỉ **15** báo đã merge): tin cờ đó thì giữ
  lại 92 nhánh rác, tin ngược lại thì xoá nhầm việc thật. Ba phép thay thế, dọn 108 → **4** nhánh: khớp
  `headRefName` với PR đã merge (76), `git rev-list --count main..<b>` = 0 (12), và tra số PR dẫn trong chính
  commit message / grep sản phẩm của nhánh trong `main` (16). Hai ca suýt kết luận ngược được ghi nguyên: nhóm
  `worktree-hm1..hm7` trông như chưa merge vì squash xoá cả sha lẫn tiêu đề — **số PR viết trong commit là sợi
  dây duy nhất còn lại**; và `fix/ops-staging-deployed-vong-khoa` có văn bản không nằm trong `main` nhưng đã
  được #290 giải cùng vấn đề bằng cách khác, tức superseded chứ không phải bỏ sót. (#309)
- refactor(company): **tách `orch/routes.py` (400 dòng, sát trần) thành ba module theo đúng ba việc nó đang
  làm** — `guards.py` (vị từ "event này có đi đường này không", 181 dòng), `enrich.py` (làm giàu payload trước
  khi giao agent, 72 dòng), `routes.py` (bảng + `Route` + `check_routes`, 234 dòng). Nhập **một chiều**:
  `routes.py` → `guards.py`/`enrich.py`, không có chiều ngược — nên thêm một guard không phải sửa bảng và
  ngược lại. Lý do tách là cổng chứ không phải khẩu vị: `test_kich_thuoc_module_orch_duoi_400_dong` đã đỏ ở
  #307 và chỉ lách qua được bằng cách nén bình luận; PR sau thêm một route là đỏ lại. **Dời thuần, chứng minh
  bằng máy**: so `ast.dump` từng định nghĩa trước/sau — 29/29 giống hệt, không thiếu, không đổi, không thêm.
  Hai cổng bắt đúng việc của chúng trong lúc tách: sổ miễn trừ `EXEMPT_LINES` khoá theo `(file, nguyên dòng)`
  nên dòng dời file là stale ngay (`test_moi_dong_mien_tru_van_ton_tai`), phải đổi khoá kèm lý do; và
  `verify.py`/`orchestrator.py` nhập tên riêng từ `routes` được trỏ thẳng sang module mới thay vì dựng lớp
  chuyển tiếp giả. Kèm một dòng `CODEMAP.md`: muốn thêm guard/enrich thì sửa ở đâu. (#308)
- test(company): **`--selftest` — mỗi ca eval phải bác được bản `bad:` của chính nó** (`pt.6`, `pt.7`, `pt.9`,
  ADR-0042). Repo có cổng cho *đầu vào* của phép đo eval (`--replay --strict`) và cho *kết quả* của nó
  (`thresholds.yaml`), nhưng không có cổng nào hỏi **"thước này có bao giờ chỉ sai không?"**. Đo ra: **13/59 ca**
  có `expect:` cho một output sai thật đi qua — mỗi ca như vậy xanh vĩnh viễn mà vẫn tính vào mẫu số
  `min_pass_ratio`, tức làm điểm đẹp lên bằng một phép đo rỗng. Nay cả 59 ca mang một khối `bad:`, `check()`
  phải bác được nó; ca thiếu `bad:` cũng đỏ; chạy **không gọi model, không đọc bản ghi** nên vào được CI cạnh
  `--replay --strict`. 13 `expect:` lỏng đã siết theo đúng một chiều (siết `expect:`, không nới `bad:`), và
  `--replay --strict` vẫn 59/59. Kèm `pt.9`: `thresholds.yaml` ghi `ops: cases: 8` trong khi `ops.yaml` có 9 ca
  — cổng chống thu nhỏ bộ ca đang hở một ca, nay có ca test canh cho cả sáu agent. (#306)

- feat(khung): **quy ước nợ kỹ thuật `no-ky-thuat` và lệnh thu hoạch** (`pt.2`, `pt.3`). `TRAPS.md` ghi bẫy
  *đã mắc*; repo không có chỗ nào ghi thứ ngược lại — **nợ cố ý tạo ra**: một đơn giản hoá hôm nay không sai
  nhưng có trần đã biết, và cái trần đó chỉ nằm trong đầu một người rồi mất cùng phiên của họ. Nay có mục
  "Nợ kỹ thuật cố ý" trong `AGENTS.md` (khuôn một dòng `# no-ky-thuat: <trần>, <điều kiện quay lại>`, ranh giới
  rõ với `TRAPS.md` và với TODO thường) và `/no-ky-thuat` thu mọi marker thành bảng, **gắn cờ `no-trigger` cho
  chính những marker sẽ mục** — marker không nêu điều kiện quay lại. Lệnh chỉ đọc, không sửa gì; cổng khung
  bắt buộc nó tồn tại. (#306)

- test(khung): **cổng chặn 4 file luật harness trôi khỏi `AGENTS.md`** (`pt.1`). `.cursorrules`,
  `.windsurfrules`, `.clinerules` và `GEMINI.md` tự khai "cố ý không chép lại luật" nhưng thực tế có chép hai
  danh sách — file cấm commit và tên gói — và **đã trôi**: cả bốn thiếu "khoá/token, dữ liệu khách thật" của
  luật cấm 3, tức agent không phải Claude Code (không có hook nào canh) đọc bản thiếu đó rồi commit khoá mà
  không biết mình sai. Cổng mới ở `test_cong_repo.py` **trích danh sách từ chính `AGENTS.md`** (chốt cứng ở
  test chỉ tạo bản sao thứ năm) và soi cả bốn bản sao; kèm một ca đếm đủ 8 mục cấm + 11 mục bắt buộc để regex
  trích không sót mục in đậm trải hai dòng. Bốn file đã được sửa cho đủ. (#306)

- fix(khung): **`pre-commit-gate.sh` canh cây đang commit, không phải checkout chính** (`pt.10`). `CLAUDE.md`
  luật 2 bắt mỗi phiên một `git worktree`, nhưng hook đọc `git -C "$CLAUDE_PROJECT_DIR"` — checkout chính. Hỏng
  hai chiều cùng lúc: phép 1 thấy nhánh `main` của checkout chính nên **chặn oan mọi commit đúng luật**, phép
  2–4 đọc index rỗng nên **file cấm, hạ `fail_under` và cổng gói không được canh gì**. Tách hai nghĩa: `$ROOT`
  chỉ để tìm `scripts/dev-task.sh`, `$CAY` (`git rev-parse --show-toplevel`, lùi về `$ROOT`) cho mọi phép đọc
  trạng thái git. Bốn ca mới dựng worktree thật, ba ca đỏ trước khi sửa. Đã rà cả họ lỗi: `block-dangerous-git.sh`
  (không đọc trạng thái git) và `auto-format.sh` (chỉ dùng `$ROOT` để tìm script) an toàn, không phải sửa. (#306)

- fix(company): **rework không còn quay lại pha `author` khi bộ test đã có** — vòng lặp `tasks`→`qa` đo được
  khi vận hành QLKH 2026-09-14, bốn vòng liền: ticket rework (`retry+1` vì lint/test đỏ) phát lại `tasks` →
  `qa` pha `author` mở worktree, thấy bộ test đã commit từ lượt trước nên **đúng đắn là không ghi gì** →
  `author_tests` thấy worktree sạch và ném "không viết file test nào" → `agent_error_unhandled` → escalation →
  người duyệt → phát lại → lặp; thoát ra chỉ bằng cách khởi động lại engine **bỏ** `--test-author`. Lỗi ở
  **guard** chứ không ở agent: `_can_author_tests` hỏi "có bật cờ không" và "stack phân vùng được không", chưa
  bao giờ hỏi "bộ test cho ticket này đã có chưa". Nay có `_da_co_bo_test`, và nó lọc theo **`causation_id`**
  chứ không theo `ts` — hai route của `tasks` (qa author, builder qua `_no_test_author`) được đánh giá **tuần
  tự trong cùng một event**, nên hỏi trống "bus có bộ test không" thì guard của builder lật ngay sau khi qa
  phát và ticket đi CẢ HAI đường (`tests_authored_by` thành `assignee` ở đúng lượt vừa có test độc lập — bản vá
  đầu mắc đúng lỗi này, ca luồng cũ bắt được). Bỏ pha có **vết audit** `test_author_bo_qua` với khoá `once`
  mang thế hệ retry, không bỏ im. Đường re-author hợp lệ duy nhất (tranh chấp test, `_has_dispute`) không bị
  đụng. Kèm: gộp hai chỗ tra `retry` trùng nhau trong cùng hàm. (#307)
- docs(khung): **kế hoạch thi hành `pt` — năm cơ chế lấy từ `DietrichGebert/ponytail`.** Đo hiện trạng bằng
  4 subagent `Explore` chỉ đọc tìm ra **ba lỗi đang tồn tại**, không phải ba chỗ "có thể cải thiện": 4 file luật
  harness đã trôi khỏi `AGENTS.md:34` (thiếu "khoá/token, dữ liệu khách thật"); `evals/thresholds.yaml:15` ghi
  `ops: cases: 8` trong khi `ops.yaml` có 9 ca nên cổng chống thu nhỏ bộ ca đang hở; và ≥ 6 ca eval có `expect:`
  lỏng tới mức output sai vẫn PASS. Lỗi thứ tư lộ ra trong lúc commit chính PR này:
  `pre-commit-gate.sh:17` lấy `ROOT` = `CLAUDE_PROJECT_DIR` = checkout chính, nên trong phiên worktree (thứ
  `CLAUDE.md` luật 2 **bắt buộc**) phép kiểm nhánh chặn oan mọi commit, còn ba phép kiểm còn lại đọc index rỗng
  nên không bao giờ bắn — hàng rào vừa cản người đúng luật vừa buông người sai luật. Hai mục của ponytail bị loại **sau khi đo**: `--rescore` (repo đã có dưới tên
  `make eval-replay`) và judge LLM (repo chấm tất định). 9 mã / 5 hạng mục ở `docs/thi-hanh/pt.md`, thi hành bằng
  `/thi-hanh pt`. (#305)

- fix(console): **số test trong `README.md` gốc thôi trôi — có cổng canh, không chỉ sửa một lần.** Ba dòng bảng
  "Quy mô" đều lệch và **đều lệch một chiều "nói ít hơn thật"**: company 1249→**1256**, gateway 251→**256**,
  core 479→**488**. Đúng khuôn bản tự kiểm 2026-09-07 từng bắt (5/10 dòng số liệu README lệch, tất cả cùng một
  chiều, tất cả ở đúng những dòng KHÔNG có test CI canh) — sửa số một lần thì vài tháng sau lệch lại, nên phần
  chính của PR này là `test_so_test_trong_readme_khop_dia`: đọc số từ chính bảng README rồi chạy
  `uv run --directory <pkg> pytest --collect-only` để so với đĩa. Dùng `uv run --directory` chứ không
  `sys.executable -m pytest`: mỗi package có nhóm dev riêng, chạy pytest của console trong thư mục gateway thì
  10 file lỗi thu thập vì thiếu `pytest-asyncio` — một cổng "đếm được 0" là cổng nói dối chứ không phải cổng đỏ.
  Đo ba chiều: trả README về số cũ → đỏ; sửa đúng → xanh; thêm một ca test mới ở core → đỏ ngay. Kèm
  `docs/TASK-PACK.md` A1/A5/A6 nói đúng hiện trạng cổng: A5 còn viết ba lối thoát "không có trần, không ai đếm"
  trong khi `TRAN_PRAGMA`/`TRAN_SKIP`/`TRAN_OMIT` so bằng đúng từ 2026-09-12, A6 còn bảo đi grep tay trong khi
  `CHUA_PHU_NHANH` đã canh từ #297 — gói việc thường trực chỉ sai chỗ nào cổng đã làm rồi thì người audit tiêu
  giờ vào việc máy làm xong, và bỏ qua đúng phần máy không làm được. (#304)
- feat(core): **cài đặt ADR-0016 — cấu hình model ba tầng: máy → package → biến môi trường.** Tầng máy
  (`~/.config/xagents/llm.yaml`, đè bằng `$XAGENTS_LLM_CONFIG`) nằm NGOÀI repo nên không bốc hơi theo
  `git worktree add` — đo 2026-09-14: **0/4 worktree**, kể cả checkout chính, có một `llm.yaml` nào, tức không
  phiên agent nào chạy được model thật cho tới khi có người dựng tay. Ba chỗ đáng chú ý, mỗi chỗ một ca test đo
  hai chiều: (1) gộp hai tầng ở tầng **dữ liệu** chứ không gọi `apply_yaml` hai lần — `apply_yaml` gán đè nên
  một `llm.yaml` package không khai `backends:` sẽ **xoá trắng** `backends` của tầng máy, đúng thứ ADR sinh ra
  để tránh; (2) `$XAGENTS_LLM_CONFIG` trỏ file không có ⇒ **fail-closed nói rõ thiếu gì**, không lặng lẽ rơi về
  `provider: fake` (không chỉ đích danh thì vắng tầng máy vẫn bình thường — test và `evals --replay` chạy
  offline); (3) `XAGENTS_LLM_CONFIG` vào `SECRET_ENV` của `sandbox.py` cùng họ `CLAUDE_CONFIG_DIR` — không phải
  bí mật, mà là **đường đến** bí mật (`AGENTS.md` luật bắt buộc 5). Kèm ràng buộc bắt buộc của ADR:
  `python -m company.probe --explain [--json]` in **nguồn của từng khoá**, không gọi CLI (lệnh chẩn đoán không
  được phụ thuộc vào thứ đang hỏng) và báo lỗi cấu hình tử tế bằng exit 2 thay vì traceback. (#303)
- docs(adr): **ADR-0016 — cấu hình model ở tầng cấp máy**, `llm.yaml` của package chỉ giữ phần khác nhau. Câu
  hỏi khởi nguồn *"sao không tích hợp `llm.yaml` trong core, gọi model qua gateway"* bị chính phép đo lật cả
  hai vế: `llm.yaml` **đã** ở core từ K3.3 (`load_config` là chỗ duy nhất đọc), còn gateway **không** thay thế
  được vì đường `provider: claude-code` là tiến trình CLI chứ không phải HTTP. Vấn đề thật nằm chỗ khác:
  `llm.yaml` gitignored + luật mỗi phiên một worktree ⇒ cấu hình model bốc hơi đúng chỗ agent làm việc — đo
  09-09 **14/16 worktree** không có file nào, đo lại 09-14 **0/4**, kể cả checkout chính. Quyết định: tầng máy
  ngoài repo (`~/.config/xagents/llm.yaml`, đè bằng `$XAGENTS_LLM_CONFIG`) giữ `backends`; package giữ
  `routing`/ngân sách/`prices`. **ADR ghi quyết định, mã chưa có.** Port từ worktree mồ côi 5 ngày; số cũ 0010
  đã bị `domain-allowlist-mang-sandbox` chiếm nên đánh lại 0016, và mọi số dòng/đường dẫn được trích đã kiểm
  lại theo cây mã hiện tại. (#302)
- fix(company): **trần TIỀN đặt mà model không có giá thì phải kêu, không im** — `Pricing` trả `cost_usd = 0.0`
  cho model không khớp bảng `prices` trong `llm.yaml` và đánh dấu `unpriced` "để không ai tưởng là miễn phí",
  nhưng dấu ấy chỉ được ĐẾM rồi in trong `sprint_report`. Hệ quả: ai đặt `budget_usd`/`project_budget_usd` mà
  đi backend không có giá thì `_check_ticket`/`_check_project` cộng dồn `0.0` mãi — trần không bao giờ chạm,
  `budget_cut` và `pause` không bao giờ nổ; guardrail ngân sách tiền là no-op **im lặng**. Đo trên QLKH thật:
  137 318 818 token, tổng chi phí ghi nhận **0,0000 USD**. Nay `Supervisor._check_unpriced` sinh `escalate`
  đúng MỘT lần cho mỗi ticket/dự án **có** trần tiền (không đặt trần thì `unpriced` chỉ là thông tin);
  `unpriced_warned` dựng lại được từ bus như `ticket_warned` nên `replay` không lệch. Đo hai chiều: bỏ
  `self._check_unpriced(a)` → 2 ca đỏ, bật lại → xanh. Port từ phát hiện 3 của audit 2026-09-09, việc nằm
  ngoài mọi PR suốt 5 ngày trong một worktree bám layout trước ADR-0011. (#301)
- docs(traps): **bài học gộp agent** vào `TRAPS.md` gốc (3 mục §2: gộp vai để "giảm cổng" không bỏ được cổng
  nào; quyết lại điều một ADR đã quyết; ba lần vá lòi chỗ mới = kiến trúc sai) và `software-company/TRAPS.md`
  (3 mục Prompt/eval: `phases:` chỉ cắt SKILL không cắt thân prompt — prompt phình 13× mà `assetbudget` vẫn
  xanh; một agent hai pha lẫn đúng nhãn phân biệt hai pha; hai route cùng agent+`topic_out` đụng khoá
  `partial`). Rút từ ADR-0040 đã lùi ở #286. (#300)
- fix(console): **`test_cong_khung.py` chạy được trên Windows — chọn bash bằng phép thử, không lấy cái đầu
  PATH** — `shutil.which("bash")` trên máy có WSL trả stub `AppData/Local/Microsoft/WindowsApps/bash.exe`;
  stub chuyển tiếp vào WSL, nơi `C:\Users\x\a.sh` bị nuốt hết dấu `\` thành `C:Usersxa.sh` → exit 127 cho mọi
  ca gọi script. Hệ quả: **51/73 ca đỏ** trên máy phát triển trong khi CI ubuntu xanh — hàng rào mới port ở
  #294 không chạy được ở đúng chỗ nó phải chặn, và vì phụ thuộc thứ tự PATH nên đỏ *chập chờn*. Nay `_tim_bash()`
  thử THẬT từng ứng viên (chạy một script ở thư mục tạm bằng đường dẫn hệ điều hành) và lấy cái đầu tiên chạy
  được; vị trí Git Bash suy từ `git --exec-path` chứ không đoán `C:\Program Files`. Đo hai chiều: tắt bản sửa
  → 52 failed, bật → 74 passed. (#299)
- docs(sessions): **nhật ký phiên dọn tồn 2026-09-14** — merge nốt PR mở duy nhất (#297, kẹt `DIRTY` dù
  auto-merge đã bật: rebase + giải 2 xung đột nhật ký, cổng `console` 423 passed, CI 30/30) và dọn **11**
  worktree cũ theo bằng chứng đã-merge (tra số PR trong commit riêng của từng worktree, hoặc tra sản phẩm của
  nó trong `main` khi worktree không gắn PR nào). Ghi lại 4 worktree cố ý giữ — hai cái (`-wt-usd`,
  `-wt-llmcfg`) mang việc **chưa merge, chưa có PR** và bám layout trước ADR-0011 — cùng ba thao tác bị
  classifier chặn, để phiên sau không dọn nhầm và không thử lại vô ích. (#298)
- fix(core): **`ContainerSandbox` chạy được trên Windows — env ra `-e` thay vì `--env-file -`** — docker CLI
  trên Windows coi `-` là TÊN FILE (`docker: --env-file: open -: The system cannot find the file specified`),
  nên mọi `local_checks` của builder đều `lint=false tests=false` và không ticket nào mở nổi PR (đo thật trên
  QLKH-034, 2026-09-14). Đường `--env-file -` (giá trị không lộ trong danh sách tiến trình) giữ nguyên cho
  Linux/macOS; Windows dùng cùng đánh đổi đã có của ca `stdin`, và tên sandbox mang `:env-argv` để audit thấy.
  `env_via_stdin=None` tự chọn theo `os.name`, đặt tường minh trong test để không phụ thuộc máy chạy. (#296)
- feat(khung): **hàng rào thi hành luật cấm — `scripts/dev-task.sh` + ba hook Claude Code**, lấy từ
  `seeker19110/project-template` và thích ứng cho workspace năm package. Trước bản này, 8 luật cấm của
  `AGENTS.md` (không commit/push `main`, không commit `llm.yaml`/`*.sqlite*`, không hạ `fail_under`) chỉ được
  canh bằng trí nhớ của agent; CI bắt sau khi đã push, và gitleaks quét cả lịch sử nên commit rồi xoá vẫn đỏ
  vĩnh viễn. Nay: `pre-commit-gate.sh` chặn commit khi đứng trên `main` / staged có file cấm / diff hạ
  `fail_under` / cổng đỏ (chạy **hẹp** theo gói bị đụng — cổng cả năm gói mất nhiều phút thì agent sẽ né);
  `block-dangerous-git.sh` chặn push–force-push `main`, `reset --hard`, `*--abort`; `auto-format.sh` format
  file vừa sửa. `dev-task.sh gate [gói]` là một điểm vào cho lệnh CI (khớp đúng `ci.yml`: `--cov` cả năm gói,
  `-n auto` riêng software-company). Thêm `/gate`, `/debug`, `/adr`; `GEMINI.md`/`.cursorrules`/
  `.windsurfrules`/`.clinerules` trỏ về `AGENTS.md` cho agent khác Claude Code. Hai lỗi của bản gốc đã sửa
  trong port: máy phát triển **không có `jq`** nên hook bản template fail-open im lặng cả phiên (thêm đường
  đọc JSON bằng Python), và `.sh` CRLF làm bash Linux vỡ mà không đỏ ở đâu (`*.sh text eol=lf` + test
  `git check-attr` canh). Đo hai chiều: chưa có script/hook → 50/51 test đỏ, có rồi → 73/73 xanh; cổng console
  408 passed, coverage 100.00%. (#294)
- test(console): **trần `branch = true` cho độ sâu coverage (A6), và quyết định KHÔNG xây "arch-health-radar"**
  (ADR-0015). Phiên này dựng xong `keeper.radar` ba phép ratchet (đủ test, 100% dòng + nhánh, cổng keeper
  xanh) thì `make test` đỏ ở `test_cong_repo.py::test_skip_xfail_khong_vuot_tran` — và đọc file đó mới thấy
  **hai trong ba phép đã có cổng từ 2026-09-12**, mạnh hơn bản đang viết: sổ `TRAN_PRAGMA`/`TRAN_SKIP`/
  `TRAN_OMIT` so **bằng đúng** (bớt cũng đỏ) và tách theo từng package, còn `test_quality_needs_phu_moi_job_con`
  đã làm đúng phép A8 bằng cùng thuật toán. Radar bị xoá thay vì sửa cho sống chung: hai bộ đếm cùng một thứ
  với hai baseline khớp tay là một nguồn lệch mới. Giữ lại đúng phép còn thiếu thật —
  `test_branch_coverage_dung_so_chua_phu_nhanh` + sổ `CHUA_PHU_NHANH = {gateway, console}`: `fail_under = 100`
  trên DÒNG vẫn để lọt nhánh, và tới giờ không cổng nào canh việc một package lặng lẽ tắt `branch`. Đo hai
  chiều: tắt `branch` ở keeper → đỏ; bật ở gateway mà quên hạ sổ → cũng đỏ. Cổng đầy đủ: ruff+mypy sạch cả
  năm package, `make test` → 2889 passed, 0 failed. (#297)
- docs: **đối chiếu `seeker19110/projects-template` theo PROMPT-SHEET §H + khuôn Báo cáo xác thực cho luật
  cấm 8**. Báo cáo `docs/reports/2026-09-14-doi-chieu-projects-template.md`: trên ~25 hạng mục của bộ khung
  kia, 13/15 hạng mục đối chiếu chính repo này đã sâu hơn (gate là máy trạng thái chạy thật chứ không phải
  tài liệu; `keeper` thay cho một script bảo trì; `stacks.detect()` thay cho bảng tra cổng theo loại dự án;
  TDD cứng + `fail_under = 100` thay cho khuyến nghị), 1 thứ đáng lấy, phần còn lại xếp "chưa cần" kèm lý do
  — `/grill` bị loại vì **ngược** luật "Khi bối rối". Hai ứng viên ban đầu bị chính đối chiếu loại bớt một:
  vòng hội tụ audit đã có đủ ở `docs/TASK-PACK.md` §"Việc để lại đang treo" + ô kiểm mục 2 của gói việc audit,
  nên không sửa file đó. Thay đổi duy nhất lên luật: `AGENTS.md` luật cấm 8 thêm khối BÁO CÁO XÁC THỰC
  điền-vào-chỗ-trống (lệnh thật của repo: `make lint`/`test`/`cov`, `evals --replay --strict`,
  `subagents check`, `assetscan scan`, dòng đo-hai-chiều của luật 4, ô CHANGELOG+session log của luật 10) —
  bước 4 của luật cấm 8 trước nay chỉ tồn tại trong đầu, không có vật thể để người sau kiểm. Không thêm code,
  không thêm cổng CI, không thêm file luật. (#295)
- fix(company): **`merge_ticket` không còn gọi lại `git merge` vô ích mỗi nhịp watch cho ticket đã tích hợp
  xong (noop)** — lớp thứ ba của cùng họ bug `integration.noop`/`integration.skipped`: khoá `once` (#291) chỉ
  chặn được BẢN GHI audit-log trùng, không chặn việc `_merge_ticket` bị gọi lại — nhánh noop không thêm `tid`
  vào `o.integrated`, nên short-circuit đầu hàm không bao giờ có tác dụng cho ticket đó. Đo thật trên QLKH
  (2026-09-14, sau khi #291 đã merge): orchestrator vẫn đứng yên ở TCK-033, mỗi release-candidate mới tham
  chiếu ticket đó lại gọi `git merge` lần nữa. Thêm `o.integrated.add(tid)` vào nhánh noop. TDD:
  `test_merge_ticket_noop_them_tid_vao_integrated_khong_goi_lai_git_merge` đỏ trước (5 lần gọi `merge()`), xanh
  sau. CI đầy đủ: ruff/mypy xanh, pytest -n auto --cov → 1250 passed, 1 skipped, 100% dòng + nhánh. (#293)
- feat(company): **`smoke()`/`regression_run()` bỏ qua chạy trần khi spec đã khai `runtime.deploy`** (ADR-0041,
  nối tiếp ADR-0029/0039/0040). Đo thật trên QLKH: 6+ release liên tục fail ở `smoke()` (`npm run dev`,
  `exit_code=127`) TRƯỚC KHI kịp chạm `deploy_process.sh` — `runtime.command` chạy trần bằng subprocess của
  chính orchestrator, không hợp với app cần cài dependency riêng (venv/bắc cầu WSL); cờ `legacy` không giải
  được vì chỉ tác dụng khi hoàn toàn không khai `runtime.command`, còn QLKH có khai (dù sai). Khi spec đã khai
  `runtime.deploy`, `smoke()` giờ trả `unverified` (không đổi status) và `regression_run()` không hạ verdict QA
  xuống `fail` vì lý do không liên quan chất lượng PR — bằng chứng thật đến từ `deploy_release()` chạy ngay
  sau, tự chờ `/healthz` trước khi kết luận. TDD: `test_runtime_deploy_khai_thi_smoke_bo_qua_khong_fail` (dùng
  lệnh CHẮC CHẮN fail nếu bị spawn thật để chứng minh không hề chạy) đỏ trước, xanh sau. CI đầy đủ:
  ruff/mypy/pytest -n auto --cov → 1249 passed, 1 skipped, 100% dòng + nhánh. (#292)
- fix(company): **`merge_ticket` không còn ghi lặp `integration.noop` mỗi nhịp watch** — sửa cùng bẫy đã vá
  cho `integration.skipped` (thiếu khoá `once`) nhưng bị bỏ sót ở nhánh liền kề: ticket không có commit mới so
  với nhánh tích hợp (PR no-op) không đổi trạng thái gì, nên orchestrator ghi lại y hệt một bản ghi mỗi 3 giây
  vô thời hạn. Đo trên `company.sqlite` thật của QLKH (TCK-033): 1319/2165 bản ghi audit-log (61%) là bản sao
  của cùng một sự kiện — `metrics`/`console` đọc sổ này nên số liệu bị pha loãng, và orchestrator quay vòng
  không tiến triển. TDD: `test_integration_noop_chi_ghi_mot_lan_cho_moi_ticket` đỏ trước (5 bản ghi), xanh sau
  khi thêm `once=f"integration.noop:{release_id}:{tid}:{before}"`. (#291)
- fix(company): **agent `ops` không còn tự ý lùi `status=pending_human` khi đã có runbook cụ thể** cho deploy
  staging. Nguyên nhân gốc thật của 5+ release QLKH kẹt vĩnh viễn (REL-001/005/006/007/008/009): `ops` hiểu
  nhầm `status=deployed` là lời khai "tôi đã tự chạy deploy" (nó không có tool chạy trực tiếp) nên luôn lùi về
  `pending_human`, khiến code (`_smoke`/`_deploy_release`, chỉ chạy khi `status=="deployed"`) chưa từng thực thi
  `deploy_process.sh` một lần nào. Sửa `agents/operations/ops.md` (v1→v3, chốt rõ `deployed` là YÊU CẦU để code
  tự xác minh, không phải lời khai) và `skills/customer-acceptance.md` (v2→v3, `accepted`/`conditional` là
  phép đếm, finding trích literal mã yêu cầu). Đo bằng eval thật `--runs 3` qua sub Claude Code: điểm `ops` từ
  ~0.85 lên 0.963, qua ngưỡng 0.95 không cần hạ chuẩn; `eval-replay --strict` 59/59 pass. (#290)
- feat(company): **`COMPANY_DEPLOY=process` — deploy được khách không dùng Docker** (ADR-0040, nối tiếp
  ADR-0039). Ca gốc: 5 `release-events` của QLKH (REL-001/005/006/007/008) kẹt ở gate `escalation` vì
  `deploy.py` chỉ biết `docker compose`, còn staging QLKH chạy tiến trình Python trần trên WSL. Thêm mode thứ
  hai: `runtime.deploy` của spec giờ có thể trỏ tới một script hỗ trợ hai lệnh con `up`/`down` (không dò tên
  mặc định như compose); `deployed` là hai phần — script `up` thoát 0 **và** smoke vào `rt.port` đã khai trong
  spec (không có `ps` như compose để tự đọc cổng). Runner mặc định là một argv PREFIX bắc cầu qua WSL từ hub
  chạy trên Windows native (`wsl.exe --cd . bash`, `.` được thay bằng `repo_root`, đã đo thật bằng `wsl.exe
  --cd <đường dẫn Windows> bash -lc pwd`); máy Linux/CI đặt `COMPANY_DEPLOY_RUNTIME=bash` để bỏ qua cầu nối. TDD
  14 ca đỏ trước ở `tests/test_deploy_process.py` (đường hạnh phúc không `down`, `up`/`smoke` hỏng đều `down`,
  thiếu cổng, không khai/không có script → `skipped` không đoán tên, fail-closed thiếu binary → raise, argv/
  prefix do code ghép), CI đầy đủ xanh (ruff, mypy --strict, pytest 100% dòng+nhánh, 1247 pass). (#289)
- fix(platform): **`is_loopback_host` không còn nhận tên miền giả loopback** ở CẢ `platform/console` và
  `platform/gateway`. Cả hai kết thúc bằng `startswith("127.")`, nên `127.0.0.1.evil.example` — kẻ tấn công chỉ
  cần một bản ghi A trỏ về 127.0.0.1, không cần DNS rebinding — đi lọt cả hàng rào `Host` lẫn `Origin` (hai
  hàng rào gọi chung một hàm). Hệ quả đo được: trang tấn công khi đó CÙNG NGUỒN với console nên đọc được token
  phiên mà `_serve_index` nhúng vào HTML rồi gọi `/api/gate/decide`; gateway không có xác thực client nên trang
  ấy `POST /v1/chat/completions` đốt quota Google thật. Nay quyết bằng `ipaddress.ip_address(...).is_loopback`
  thay vì tiền tố chuỗi; siết thêm có chủ ý: dạng viết tắt `127.1` bị từ chối (fail-closed). 9 ca test đỏ trước
  bản vá (4 gateway + 5 console, cả mức đơn vị lẫn request thật qua `guard_middleware`/`_guard`), xanh sau. Khuôn
  lỗi vào `TRAPS.md` §1 khuôn 6 ("kiểm danh tính bằng tiền tố chuỗi"); đóng mục 1 sổ việc để lại của
  `docs/reports/2026-09-13-audit.md`. (#288)
- fix(docker): **hub container không còn bake bí mật, không còn mất state, và với tới được gateway** (ADR gốc
  0014, sửa đổi ADR-0013). Năm chỗ hở im lặng do audit 2026-09-13 đọc ra: `.dockerignore` không loại
  `llm.yaml`/`.env` trong khi `Dockerfile` có `COPY . .` (bí mật vào layer image — gitleaks mù lớp này vì file
  chưa từng vào git); không volume nào mang `llm.yaml` vào container; không có đường tới gateway trên host
  (`127.0.0.1:1123` trong container là chính container); bind-mount FILE `.sqlite` trong khi bus chạy WAL nên
  `-wal`/`-shm` rơi vào layer container; volume artifacts mount trượt tên (`company.sqlite.artifacts` trong khi
  `runner.artifact_store` sinh `company.artifacts`) nên blackboard chưa bao giờ persist. Vá: bí mật ra khỏi
  ngữ cảnh build, `llm.yaml` vào bằng mount `:ro`, `extra_hosts: host.docker.internal`, state mount theo THƯ MỤC
  `var/` (đóng cả hai lỗi state bằng một quyết định). Không đổi một dòng mã: `--company-db`/`--keeper-db` đã có
  sẵn, entrypoint chỉ truyền đường dẫn. Cổng cứng mới `platform/console/tests/test_cong_docker.py` 6 ca, viết
  trước bản vá — đo hai chiều: tắt vá 6/6 đỏ, bật vá 6/6 xanh. (#287)

- docs(audit): **audit toàn dự án 2026-09-13 — tám phép đo A1–A8 + rà bề mặt HTTP**
  (`docs/reports/2026-09-13-audit.md`). Mọi cổng máy chạy lại và xanh (2852 test, 100% coverage cả năm package,
  ruff/mypy sạch, eval phát lại, `subagents check`, `assetscan`, `keeper drift`). Sáu dòng tài liệu lệch đã sửa
  trong chính PR này: số màn console (6 → 8, `1`–`7` → `1`–`8`), bốn câu coverage nói "100% dòng" sau khi ba
  package đã bật `branch = true`, ba comment `pyproject.toml` còn đếm "bốn"/"sáu" package. Bảy việc để lại,
  trong đó ba cái mới: `is_loopback_host` nhận mọi tên miền bắt đầu bằng `127.` ở CẢ console và gateway (trái
  với chính docstring chống-DNS-rebinding của chúng); `pragma: no branch` là lối thoát thứ năm khỏi
  `fail_under = 100` mà sổ trần chưa đếm; luật "lý do duyệt gate ≥ 20 ký tự" không có chốt mã nào. (#287)

- fix(company): **nhãn `source` của `review-results` do CODE điền từ ROUTE**, không do model khai. Đo bằng
  model thật thấy model khai nhầm nhãn 4/18 ca khi prompt mang nhiều vai; `delivery.py` đếm review THEO NHÃN
  nên khai nhầm là ticket rủi ro **không bao giờ đủ review và nằm im** mà `status` không báo gì — cùng họ sự
  cố QLKH-001 (13 ticket chờ vô hạn). `review_source.source_for`/`enforce_source` (module `orch/` riêng để
  giữ hai trần của `test_orch_khuon_loi`), vết ghi đè ở audit `review.source_overridden`. (#286)
- refactor(company): **`GateRiskContext` mang thêm `created_by` và `seq`** — mở đường cho hàng `RISK_RULES`
  đầu tiên (cổng tự qua khi rủi ro thấp) mà không bịa trường: `created_by` phân biệt `escalation` do
  supervisor/ops/delivery-lead mở, `seq` là thế hệ gate — thứ duy nhất diễn đạt được "chỉ tự động lần đầu".
  **Không thêm luật, không đổi hành vi**: `RISK_RULES` vẫn rỗng, mọi gate vẫn chờ người. (#286)

- feat(platform): container hoá hub console+orchestrator để chạy trên WSL — ADR-0013, Dockerfile+
  docker-compose.yml+entrypoint ở gốc repo, state qua volume (không bake `company.sqlite`/secret vào image),
  socket `docker.sock` passthrough cho orchestrator gọi `docker compose` deploy khách (ADR-0039) mà không cần
  `dockerd` trong container; thêm Mức 0 vào `docs/TRUC-VA-DUNG-KHAN.md` (#285)
- docs(sessions): ghi lại phiên vận hành QLKH 2026-09-13 (#284)
- fix(company): **`product` bắt buộc gọi tool đọc repo khách trước khi kết luận `data.codebase`, và bắt buộc
  ghi `architecture`+`api-contract` lên blackboard ngay trong lượt planning** — vận hành thật dự án QLKH lộ ra
  research chưa từng gọi tool đọc repo (5/5 lượt `tool_calls: 0`) nên `_check_plan` từ chối cả kế hoạch hợp lệ
  vì thiếu hai namespace này, và gate `escalation` mở ra không có route xử lý cho lỗi cấp dự án đó. Sửa
  `agents/research/product.md` v2→v3, eval-record 16/16 (lần đầu 14/16 do dao động điểm, xác nhận bằng chạy
  lại lần hai) (#283)
- ci: thêm `dependency-review` workflow, tham khảo `project-template`, cập nhật `docs/QUY-TRINH-GIT.md` §4 (#282)
- build(deps): bump `anthropic` 1.3.0 → 1.4.0 (dependabot) (#246)
- docs(keeper): **ghi lại canary BT8 lần hai — chạy pipeline `keeper` thật trên tín hiệu drift `pr-280` có thật**
  (thiếu dòng CHANGELOG của PR #280), dừng đúng ở cổng ngân sách I3 (PR #246 đang mở chặn PR canary) thay vì tự
  merge/đóng PR ngoài phạm vi. Ticket + patch + đo hai chiều đỏ/xanh đều chạy thật, chỉ còn thiếu bước `publish`.
  Cập nhật `docs/reports/2026-09-12-audit.md` mục A7 + `docs/TASK-PACK.md`. Nhân đây cũng điền lại dòng CHANGELOG
  của #280 (tín hiệu drift thứ hai lộ ra khi CI chạy lại — merge #246 để mở đường cho canary tạo ra chính tín
  hiệu này) (#281)
- test(company): **bật chính thức `branch = true` cho `companies/software-company` — bù xong 3 nhánh bế tắc
  cuối cùng (86/86 nhánh)** — `orchestrator.py:_call`, `orch/scheduler.py:_take_batch`, `orch/scheduler.py:_audit`
  đều có test đúng từ trước nhưng coverage.py không đăng ký được arc `return` một dòng lồng trong `with`; người
  quyết định tách `return` ra dòng riêng (đổi format, không đổi hành vi) thay vì `# pragma: no branch`. CI xanh:
  `ruff check`, `mypy`, `pytest --cov` (`fail_under = 100` cả dòng lẫn nhánh) (#280)
- test(company): **bù 48/51 nhánh coverage còn lại ở `companies/software-company`, đợt 2/2** — 11 file trong 12
  đã 100% nhánh (`orch/release_fsm.py`, `orch/routes.py`, `orch/ticket_fsm.py`, `orch/verify.py`,
  `orch/worktree_flow.py`, `orchestrator.py`, `runner.py`, `subagents.py`, `tools.py`, `web.py`, `workspace.py`);
  file thứ 12 (`orch/scheduler.py`) còn 2/154 nhánh. Còn ĐÚNG 3 nhánh bế tắc thật (không phải thiếu test): cả ba
  có hình `with <lock>: \n if <cond>: return <x>` — đo trực tiếp bằng test tối giản xác nhận coverage.py không
  bao giờ ghi nhận arc `return` một dòng NẰM TRONG khối `with`, dù test gọi đúng nhánh và assert đúng hành vi.
  `branch = true` VẪN chưa bật (giữ comment, xem lý do trong `pyproject.toml`) — cần người quyết ba nhánh này
  trước khi bật thật (#279)
- docs(adr): **đối chiếu 50/50 ADR còn lại (audit A4) với mã thật, sửa 2 chỗ lệch** — `companies/software-company/docs/adr/0037-gop-21-agent-thanh-5-hai-gate.md` khai "Đề xuất/chưa cài" nhưng agent (5 vai) và `GateKind` (bỏ `plan`) đã khớp mã từ nhiều PR trước, đã sửa Trạng thái thành "Chấp nhận (đã cài đặt)"; `docs/adr/0008-allowlist-vai-duoc-tao-gate.md` sửa tham chiếu tới đường dẫn `Studio-creators/...` đã không còn tồn tại. Một mục (ADR-0004 `lessons_for`) chưa cài, để lại cho người quyết trong `docs/TASK-PACK.md` — không phải việc của audit. Bảng đầy đủ ở `docs/reports/2026-09-12-audit.md` mục A4 (#277)
- test(company): **bù 16/67 nhánh coverage còn thiếu ở `companies/software-company`** (đo 2026-09-12,
  `docs/reports/2026-09-12-audit.md` A6) — `gate_cli.trusted_autoapprove` (5 nhánh: topic/action sai, evidence
  không phải dict, `subject_id` rỗng, `by` giả mạo, `decision` không phải chuỗi), `orch/gates_flow.py` (7 nhánh:
  gate release duyệt mà chưa có release-candidates, escalation bỏ qua ticket không `approved`, gate acceptance/
  escalation đã pending thì không mở trùng, `_rework_after_error`/`_retry_stalled` các đường thoát sớm),
  `orch/rehydrate.py` (2 nhánh: event không có mốc hẹn, không suy ra được route để chạy lại), `probe.py` (1
  nhánh: backend đã `mcp` OK đứng cạnh backend `cli` khi tổng kết), `supervisor.py` (1 nhánh: bản ghi `knowledge`
  không phải bài học bị bỏ qua). Còn 51/67 nhánh ở 12 file (`orch/{release_fsm,routes,scheduler,ticket_fsm,
  verify,worktree_flow}.py`, `orchestrator.py`, `runner.py`, `subagents.py`, `tools.py`, `web.py`,
  `workspace.py`) — `branch = true` CHƯA bật thật, tiếp tục nhiều PR nhỏ theo cụm file (#278)

- ci: **thêm job `dependency-review`** (`.github/workflows/dependency-review.yml`) — chặn PR thêm phụ thuộc
  mới có CVE mức `high`+, đo trên diff của chính PR đó (`actions/dependency-review-action@v5`). Bổ sung cho
  `pip-audit` trong `quality` (soi toàn bộ resolve mỗi lần chạy, không phân biệt PR nào thêm gì), không thay
  thế. Tham khảo cấu trúc từ repo mẫu `seeker19110/project-template`. Không thuộc required status check —
  không đổi ruleset `main`.
- feat(keeper): **nối `git push` + `gh pr create` thật vào keeper (BT8 canary)** — đo được khi thử chạy canary
  thật: `orchestrator.open_pr()` chỉ ghi ý định PR (`pr.intent`), chưa từng gọi `gh`/`git push`. `publish.py`
  mới (`push_branch`, `create_pr`) là capability ghi THỨ BA của bất biến I1 (tạo nhánh, commit, mở PR — hai đầu
  đã có), tách khỏi `github.py` để giữ nguyên bất biến "chỉ đọc" của nó. `KeeperOrchestrator.publish()` nối nó
  vào vòng release: push nhánh → `gh pr create` → `release.fill_pr_number()` điền số PR thật vào dòng
  CHANGELOG/session-log đã soạn (cơ chế đã có từ trước, chỉ chưa ai gọi bằng số thật) — đúng luật bắt buộc 10
  (commit thứ hai vào CHÍNH PR đó). CLI `keeper publish <ticket_id>` cho người/script gọi thủ công — `watch`
  CHƯA tự động gọi nó (chuỗi signal→patch→publish chưa nối thành một vòng, ghi trong `TRAPS.md`). Idempotent:
  gọi lại không tạo PR trùng (I3); "gh báo đã có PR" dùng đúng số cũ, không coi là lỗi (#276)

- fix(company,console): **dọn sổ "Việc để lại đang treo" của `docs/TASK-PACK.md`** — sửa lời khai sai của
  `supervisor` về phạm vi bài học `knowledge` (chỉ 2/5 agent đọc được, chỉ bản ghi mới nhất mỗi namespace, không
  phải "mọi agent" + "toàn bộ lịch sử"); vá đường dẫn chết `Makefile` assetscan/assetbudget (`../Studio-creators`
  đã tách repo ở #259); sửa dẫn chiếu chết `../AGENTS.md` ở ba `CLAUDE.md` cấp package (đúng một cấp trước
  ADR-0011, nay phải `../../`) kèm cổng cứng chặn tái phát; viết đủ bốn file khung (`CLAUDE.md`/`TRAPS.md`/
  `CODEMAP.md`/`ARCHITECTURE.md`) cho `platform/xagents-core` và `companies/keeper` (khảo sát bằng Explore agent,
  sự thật từ docstring + test đo được — không đoán) và khôi phục câu khai đúng "mỗi package con có đủ bốn file"
  ở `AGENTS.md`/`README.md`; sửa `ARCHITECTURE.md` nói đúng cả bốn dãy ADR của repo; đọc thêm 2 ADR gốc đối
  chiếu mã thật (A4, nay 5/12); đo lại branch coverage `software-company` bằng cách bật tạm không commit —
  **67 nhánh/16 file** chưa test, không phải 62 như comment cũ (sổ treo, quy mô một hạng mục riêng); **thử
  chạy thật canary `keeper` BT8** — dừng đúng lúc khi phát hiện chuỗi tự động signal→patch chưa nối hết
  (`watch` mới `triage`+ghi ý định, chưa có `git push`/`gh pr create` thật; `dependency-scout`/`security-auditor`
  chưa nối CLI) và chính repo hiện quá sạch cho phạm vi vá đã nối (`fix_docs` chỉ thêm dòng CHANGELOG/session-log
  thiếu — không thiếu dòng nào lúc đo; Dependabot alerts bị tắt ở repo; tín hiệu CI thật có nhưng không loại nào
  vá tự động được) — không dựng kịch bản giả, ghi phát hiện thật vào sổ treo (#275)

- docs(adr): **ADR-0012 — PR theo hạng mục lớn, chốt quy trình mới** — hợp thức hoá luồng đã chạy thử qua bốn
  hạng mục trước (#270–#273): một nhánh cho cả hạng mục (2–8 mã), mỗi mã một commit, PR mở **nháp** ngay sau mã
  đầu (CI chạy thật trên nháp), `gh pr ready` + auto-merge khi hạng mục xong. Đo trước khi viết ADR: luật cũ
  "mỗi PR một gói" bị vi phạm ở mọi bản thi hành thật có ≥2 mã (6 mã→1 PR #198, 3 mã→1 PR #266); "điền đủ 7
  mục task pack" bị bỏ 3 mục ở 3/4 bản thật không được phép nói lý do. Sửa `docs/QUY-TRINH-GIT.md` (§2d mới),
  `docs/KHUON-THI-HANH.md` (luật 2/6, bảng B đổi cột "loại PR"→"hạng mục"), `docs/TASK-PACK.md` (mục 1/2/4 được
  viết "suy ra từ hạng mục lớn: ..." tường minh thay vì để trắng im lặng). Giữ nguyên luật 2c cho cả PR nháp —
  không có ngoại lệ "nháp không tính". Nhược điểm ghi thẳng vào ADR: squash gộp mọi mã một hạng mục thành một
  commit trên `main`, revert một mã cuốn theo cả hạng mục (#274)

- docs: **bớt trùng lặp và dẫn chiếu chết trong bộ luật** — `README.md:123` liệt lại checklist 7 bước nhưng chỉ
  ghi 4/7 (thiếu `assetscan`/`assetbudget`/`subagents`), đổi thành trỏ về `CONTRIBUTING.md` §3 thay vì liệt lại;
  `AGENTS.md:77` trỏ sai section `TRAPS.md` (§4 thay vì §6 — bảng biện hộ thật); `docs/KHUON-THI-HANH.md:33` dẫn
  "ADR-0026" thiếu namespace (ADR thật ở `companies/software-company/docs/adr/`, không phải `docs/adr/` gốc);
  `docs/adr/README.md` tự nó còn hoá thạch `Studio-creators` (đã tách #259) — sửa và thêm câu neo rõ bốn dãy ADR
  cùng đánh số từ 0001. Cố ý không đụng `docs/TASK-PACK.md`/`KHUON-THI-HANH.md` §3.6 ("mỗi PR một gói") — sửa ở
  hạng mục 5 để không làm hai lần (#273)

- docs(audit): **phiên audit toàn dự án đầu tiên chạy đủ A1–A8** (`docs/reports/2026-09-12-audit.md`) — sửa số
  liệu README gốc/con lệch đĩa (software-company 1100→1152 test; console ADR 0001–0003→0001–0004; gateway
  216→251 ca; `companies/software-company/README.md` tự mâu thuẫn 1151 vs 1097 ca ở hai dòng khác nhau), mở
  rộng `test_readme_goc.py` canh thêm dãy ADR console+gateway (đóng dòng treo từ 2026-09-07), và dọn 38 chỗ
  nhắc `Studio-creators` còn sót trong `HUONG-DAN-VAN-HANH.md`/`DIEU-PHOI-MODEL.md` sau khi công ty đó tách
  repo ở #259 (cả một mục §3.3 34 dòng và §6 85 dòng mô tả quy trình không còn tồn tại). Đề xuất mở rộng phạm
  vi phép A3 sang tên riêng công ty đã xoá, không chỉ số đếm package. A4 (đọc 50 ADR đối chiếu mã) và A6/A7
  (branch coverage, canary keeper) vào sổ "Việc để lại đang treo" — phép A4 chậm, không tự động hoá được (#272)

- fix(ci): **hồi sinh cổng chết và biến bốn luật thủ công thành cổng cứng** — cải tổ thư mục #262 làm
  `.pre-commit-config.yaml` (`files:` + `--project`) và 7/9 pattern `.github/CODEOWNERS` trỏ vào hư không:
  hook `subagents-check` **không bao giờ chạy nữa** và luật sở hữu rút về còn dòng `*`, không gì đỏ — cổng chết
  im lặng nguy hiểm hơn không có cổng vì người ta vẫn tin nó canh. Vá đường dẫn, và thêm
  `platform/console/tests/test_cong_repo.py` (17 ca) chặn tái phát bằng năm cổng cứng: mọi đường dẫn trong hai
  file cấu hình cấp gốc phải tồn tại thật · mọi package có `tests/test_golden_agents.py` phải nằm trong matrix
  `golden-check` (bắt được `companies/keeper` đang đứng ngoài — sửa prompt keeper quên tăng version thì CI vẫn
  xanh) · `quality.needs` phải phủ mọi job con (job thiếu trong `needs` là cổng xanh giả) · **trần** cho ba lối
  thoát khỏi `fail_under = 100` (`pragma: no cover` 21, `skip`/`xfail` 6, `omit` 2 — trước nay không trần, không
  hạn đáo, không ai đếm lại) · `AGENTS.md:7` khai "mỗi package con có đủ bốn file khung" trong khi
  `platform/xagents-core` và `companies/keeper` thiếu cả bốn — đã sửa câu khai, việc viết file vào sổ treo (#271)

- fix(console): **động cơ bật từ console giao hàng được, và tự khai khi không** — bấm "Bật động cơ" trước đây
  luôn chạy `orchestrator` thiếu `--deliver --push-remote`, nên release đã duyệt **không bao giờ** được tag và
  đẩy lên repo khách: đúng sự cố 2026-09-10 (QA pass, gate ký, khách nghiệm thu, sản phẩm nằm lại máy). Khác
  `--repo` — cờ đó đã thành per-project ở ADR-0025 nên console không truyền là đúng thiết kế; còn
  `Orchestrator.deliver` là cờ **toàn tiến trình**, không override được. Thêm `--deliver-remote REMOTE` (cần
  `--allow-engine`, thiếu thì dừng mã 2 thay vì hứa suông), remote đến từ dòng lệnh người trực chứ không từ
  `POST /api/engine`; `status()` khai `delivers`/`deliver_remote` để chế độ không-giao-hàng **tự khai báo** thay
  vì nhìn y hệt chế độ giao hàng. `docs/HUONG-DAN-VAN-HANH.md:872` trước đó còn khẳng định nút này chạy "đúng
  lệnh ở §5/§6/§7" — đã sửa. Chặn ở gate: gate `release` (ký **trước** khi `_deliver()` chạy) thêm mục tự kiểm
  `release.giao-hang-duoc`, `gate_brief` đọc **trạng thái tiến trình thật** (`orch.deliver`/`push_remote`) chứ
  không đọc lời khai agent — `--deliver` tắt thì hồ sơ báo `gap` kèm câu "ký xong vẫn không tới repo khách",
  đúng chỗ mà bốn gate xanh trước đây vẫn lọt (#270)

- docs: **README gốc khớp lại số liệu keeper (8→10 agent) và số package workspace (6→5)** — `companies/keeper/README.md`
  đã tự sửa "8 agent" thành 10 (đúng, lỗi đếm cũ) từ trước nhưng README gốc quên theo; "cả sáu package" còn sót
  ở `AGENTS.md:36,103` và bốn dòng comment `ci.yml` sau khi `Studio-creators` rời workspace ở #259 (`members`
  nay có 5). Đóng hai dòng trong sổ "Việc để lại đang treo" của `docs/TASK-PACK.md` ghi từ phiên audit
  2026-09-10. Không đổi mã (#269)

- feat(console): **console một view — giai đoạn 5/5 (cuối) của ADR-0011** — sáu màn "thông tin vận hành"
  (Trực ban, Phễu sản phẩm, Xưởng phần mềm, Công ty bảo trì, Chi phí, Nhật ký) trước đây ẩn/hiện qua sidebar
  (một màn thấy tại một thời điểm) nay LUÔN hiển thị cùng lúc trên một trang cuộn dài; sidebar không còn
  ẩn/hiện mà chỉ cuộn tới đúng mục. `render()` đã vẽ mọi hàm không điều kiện theo view từ trước nên gộp
  không cần vẽ lại gì thêm; ba mục trước chỉ vẽ khi điều hướng tới (`renderSubmit`/`renderGuide`/`loadSettings`)
  nay vẽ thêm một lần lúc mở trang để không rỗng nếu người dùng không bấm nav. `Cài đặt`/`Hướng dẫn` không đổi
  hành vi (#268)

- docs: **thứ tự backend mặc định cho công ty hợp nhất — giai đoạn 4/5 của ADR-0011** — chốt tường minh vào
  `docs/DIEU-PHOI-MODEL.md` §4 thứ tự `claude-code (sub) → codex (sub) → gateway (Antigravity) → model local →
  API trả phí` (đã đúng sẵn trong thứ tự khai báo mẫu, chỉ thiếu ghi thành tài liệu); thêm ví dụ backend
  `provider: anthropic` (API trả phí) còn thiếu ở cuối `companies/software-company/llm.example.yaml`. Không đổi
  cơ chế `RoutingClient`/`routing.prefer` (#267)

- feat(company): **bậc rủi ro gate + actor "code" tự động qua gate thấp — giai đoạn 3/5 của ADR-0011** —
  `gate_risk.py` mới (`RiskRule`/`RISK_RULES` tra cứu được, khởi tạo RỖNG có chủ đích: chưa có luật nào qua
  review nên PR này không đổi hành vi runtime của gate nào); actor mới `"code"` tự `approve` gate khi cờ
  `COMPANY_GATE_AUTOAPPROVE` bật (mặc định TẮT) và đúng một hàng khớp tier "low"; 12 điểm `gate.request` đổi
  sang `request_gate()`. `sc-security` chấm riêng (2 lượt) tìm và vá 2 lỗ hổng thật trước khi mở PR: thiếu
  `actor=` tường minh khiến gate nghiệm thu tự động qua bị nhầm actor "orchestrator"; tên hàng trong `reason`
  không được đối chiếu với `RISK_RULES` thật (#266)
- feat(console): **`--with-gateway` — giai đoạn 2/5 của ADR-0011, một lệnh bật cả gateway lẫn console** —
  console đã tự bật `orchestrator run --watch` sẵn từ ADR-0004 (`--allow-engine`), nên phần còn thiếu là
  gateway: cờ mới gọi `python -m gateway start` như tiến trình con trước khi phục vụ; `gateway start` đã
  idempotent và tự chờ `/health` xanh nên không dựng lại vòng chờ nào. Gateway không lên được thì console dừng
  lại và báo, không im lặng phục vụ một công ty không có model (#265)

- docs: **gói việc thường trực đổi từ "tự kiểm số liệu" thành "audit toàn dự án"** (`docs/TASK-PACK.md`, vẫn theo ADR-0003). Bản đầu chỉ đo số liệu README gốc; ba loại lệch nặng nhất nằm ngoài phạm vi đó, nên gói mở ra **tám phép đo** A1–A8: số liệu tài liệu gốc · README gốc so README con · hoá thạch sau khi cấu trúc đổi (nguồn sự thật là `[tool.uv.workspace] members`, grep cả comment mã và comment CI) · ADR "được chấp nhận" so mã thật · sổ bốn lối thoát hợp lệ khỏi cổng (`pragma: no cover`, `omit`, `assetscan-waivers.txt`, `skip`/`xfail` — ba trong bốn không có trần, không có hạn đáo) · độ sâu phép đo (`branch = true` mới ở 2/5 package) · hạn dùng của bằng chứng (bản ghi eval, sổ nợ keeper) · cổng còn hiệu lực (job có trong `ci.yml` mà thiếu trong `needs:` của `quality` là cổng xanh giả — không test nào canh). Thêm mục **"Ranh giới với cổng máy"** (17 job CI đã canh gì, phiên audit không đo lại) và sổ **"Việc để lại đang treo"** — chỗ để leftovers sống tiếp thay vì chết trong một báo cáo cũ; nạp sẵn 6 dòng, gồm 2 dòng treo từ 2026-09-07 và 4 dòng đo được khi rà lại. Không đổi một dòng mã nào (#264)
- fix(company): **`test_mcp_bridge` đỏ trên Windows vì server giả không đọc request** — `_one_shot_server`
  gọi `close()` khi buffer nhận còn request chưa đọc → TCP gửi RST; Winsock vứt luôn dữ liệu đã đệm nên client
  thấy `WinError 10053/10054` thay vì `trả lời quá dài`. Server giả nay đọc request trước khi đóng, như server
  thật vẫn làm (#263)
- fix(console): **console trỏ sai cây công ty sau ADR-0011** — `REPO_ROOT = CONSOLE_DIR.parent` nay chỉ tới
  `platform/`, nên `--company-db`/`--keeper-db` mặc định và `cwd` của hai động cơ (`engine.SPECS`) trỏ vào
  `platform/software-company` không tồn tại: console mở lên hiện bảng RỖNG không báo lỗi, và bấm Bật động cơ
  thì hỏng. Test cũ chỉ so `spec.cwd.name` nên không thấy; test mới đòi thư mục **có thật** trên đĩa (#263)

- refactor(repo): **cải tổ cấu trúc thư mục thành `platform/` + `companies/` (ADR-0011)** — hạ tầng dùng chung
  (`xagents-core`, `gateway`, `console`) tách khỏi công ty (`software-company`, `keeper`); PR thuần di chuyển,
  không đổi logic ngoài ba đường dẫn lên gốc repo (`subagents.OUT_DIR`, `assetscan`, `keeper.cli drift`) và hai
  lỗi lộ ra khi đo: `assetscan` với root tương đối ném `IndexError`, `drift` tìm công ty ở đường dẫn cũ (#262)

- docs(core): **ADR-0010 khoanh phạm vi domain allowlist cho mạng của `ContainerSandbox`** — `RunSpec.network`
  chỉ bật/tắt mạng toàn phần, không lọc theo domain; ghi lại vì sao chưa cài egress proxy (không có nơi gọi thật
  cần, một field không enforce là an toàn giả) và khuôn thiết kế bắt buộc cho phiên sau khi có nhu cầu thật (#260)
- refactor(company,console,core): **chuyển Studio-creators sang repo riêng (github.com/seeker19110/X-Studio,
  giữ lịch sử git), copy platform/gateway/ sang đó kèm lịch sử, xoá mọi tàn dư studio khỏi Claude-Agents** — console mất
  màn "Xưởng video"/StudioView (test/coverage 100% giữ nguyên), CI mất ba job `studio-*`, workspace còn năm
  package (#259)
- test(company): **bù 24/86 nhánh chưa đi cho `software-company`, chuẩn bị bật `branch = true`** (#258). Audit
  toàn diện 2026-09-10 đo được 86 nhánh (if/elif chỉ một vế từng chạy) chưa test trên `src/company`; PR này
  bù xong 8/24 file: `assetscan.py`, `delivery.py`, `evals.py`, `gate_brief.py`, `llm.py`, `mcp_bridge.py`,
  `metrics.py`, `orch/cli_cmds.py`. Hai nhánh của `llm.py`/`mcp_bridge.py` (raise/return thoát qua
  `with`/`@contextmanager` lồng nhau) là bẫy đo của coverage.py — đã test đúng hành vi, đánh dấu
  `# pragma: no branch` kèm bằng chứng arc thật, không phải bỏ qua kiểm. `branch = true` CHƯA bật (còn 62
  nhánh/16 file) — bật ở PR kế tiếp khi xong hết, tránh CI đỏ giữa chừng cho người khác.

- docs: **khớp README gốc với thực tế — số test company, trạng thái keeper** (#257). Software-company nói 1097
  test trong khi lần chạy thật gần nhất ra 1100; dòng keeper nói BT2–BT8 chưa có mã trong khi BT1–BT7 đã merge
  (mã thật, 532 test, ba lệnh CLI chạy được) — chỉ BT8 (canary) chưa xong. Phát hiện qua một đợt audit toàn diện.
- docs(sessions): nhật ký phiên 2026-09-10 (QLKH: PR #248/#251/#254/#255, tag+push thật REL-047/048) và
  `TRAPS.md` (software-company) — ghi lại lỗ hổng còn lại của `_superseded_release` (không nhận ticket đã xong
  qua `mark_done_already_integrated` khi RC không có bản giao "sau" nó), để phiên sau vá theo TDD (#256).
- fix(company): **huỷ release "superseded" phải đóng sổ ticket, không để lửng lơ ở `approved`** (#255). Khi một RC cũ bị
  từ chối vì nội dung đã nằm trong bản giao sau (`_superseded_release`), `void_release` đưa ticket approved về
  `unreleased()` — đúng cho ca xung đột tích hợp (ticket thật sự cần RC kế tiếp) nhưng sai ở đây: ticket đã giao
  rồi. Không đóng sổ thì `scheduler.tick()` (flush_releases mỗi nhịp, #251) tạo ngay một RC trùng cho ticket đó;
  nếu RC trùng đó đụng lỗi thật (nhiễu backend, xung đột khác), ticket ĐÃ GIAO bị đá về rework rồi hết retry →
  blocked lần nữa — dù code chưa từng sai gì. Đo được 2026-09-10 (QLKH thật): QLKH-002/005 và nhóm
  TCK-CR-RUNTIME-03..06 dính đúng vòng này sau khi dọn RC cũ. Vá: khi huỷ vì superseded, gọi
  `mark_done_already_integrated` cho mọi ticket approved trong RC đó trước khi trả lại pool.
- feat(console): **nút "Tick tất cả" cho checklist gate** (#254) — gate nợ kiến trúc (SD-*, DEF-*) có thể mang
  20-40 mục, tick từng ô một là việc vô nghĩa sau khi đã đọc hồ sơ bằng chứng. Chỉ hiện khi checklist có hơn
  một mục; không bỏ qua khoá lý do ≥20 ký tự hay logic mở khoá nút Duyệt — chỉ tự động hoá phần tick.
- docs(sessions): ghi nhật ký phiên 2026-09-10 — so sánh quy trình với skill `superpowers`, áp TDD/gate
  function/kiểm PR trùng (#252), và phát hiện `main` cục bộ với `origin/main` không có tổ tiên chung trong môi
  trường phiên này (#253).

- docs(agents): **TDD bắt buộc cho mọi code, gate function 5 bước xác minh, kiểm PR trùng trước khi mở PR,
  bảng tự-biện-hộ** (#252). So sánh quy trình với skill `superpowers` (obra/superpowers) theo yêu cầu người
  dùng, rút các quy tắc còn thiếu về áp cho `AGENTS.md`/`CLAUDE.md`/`TRAPS.md`/`docs/QUY-TRINH-GIT.md`: luật
  bắt buộc 4 đổi từ "test đo hai chiều khi sửa lỗi" thành TDD đầy đủ (đỏ → xanh → refactor) cho **mọi** code;
  luật bắt buộc 6 thêm ngưỡng "3 lần vá liên tiếp lòi vấn đề mới = kiến trúc sai, dừng hỏi người"; luật cấm 8
  cụ thể hoá thành gate function 5 bước trước khi nói bất kỳ câu hoàn thành nào; luật bắt buộc 11 (mới) đòi
  kiểm PR/issue đã đóng trùng vấn đề trước khi mở PR mới. Nối luật TDD vào `CLAUDE.md` của bốn package con đã có
  file này (`software-company`, `Studio-creators`, `gateway`, `console`) — mỗi package trỏ đúng lệnh test của
  mình, không chép lại luật. `xagents-core` và `keeper` chưa có `CLAUDE.md` từ trước — để ngoài phạm vi PR này.
  Không đổi hành vi code — thuần tài liệu quy trình.

- docs(sessions): **ghi nốt hai mục nhật ký phiên còn thiếu cho #247 và #249** (#250). Luật bắt buộc 9 đòi mỗi
  phiên một mục; nhật ký 2026-09-09 dừng ở #245 trong khi hai PR sau đó đã merge — cả hai có dòng CHANGELOG
  và mục `TRAPS.md` nhưng thiếu phần kể lại. Mục mới ghi ba thứ đo được: `rerun_failed_jobs` phát lại payload
  sự kiện gốc nên nhãn mới không tới được cổng; vá `labeled` **không hồi tố** cho PR có head cũ hơn thay đổi;
  và `port + 1` là một giả định vô căn cứ khiến một ca test xanh lâu nay vì môi trường tình cờ thuận. Kèm ghi
  lại ba lần tự bác bỏ trong phiên, để lần sau đọc được cả chỗ sai lẫn chỗ đúng.

- fix(company): **`orch/scheduler.tick()` tự gọi `flush_releases` mỗi nhịp watch cho backlog ticket `approved`
  chưa nằm trong RC nào** (#251). Trước đây `flush_releases` chỉ được gọi ngay lúc một ticket vừa review pass hoặc lúc
  đóng một ticket escalated — không nhịp nào gọi lại sau đó; ticket approved từ trước một lần restart (RC không
  được tạo lại khi replay, đúng chủ đích, tránh RC trùng) nằm `approved` vĩnh viễn dù `status` báo
  `queue: 0, blocked: []` xanh hết. Đo được 2026-09-10 (QLKH): 16 ticket approved đứng im nhiều ngày. Test đo
  hai chiều: tắt bản vá thì `test_tick_tu_gom_ticket_approved_con_sot_thanh_release` đỏ.
- test(company): **cổng chết trong `test_adr0012` lấy bằng socket giữ chỗ, không phải `port + 1`** (#249). Ca
  `test_resolve_host_va_default_fetcher_tren_server_that` giả định cổng kế bên cổng server là cổng trống —
  **vô căn cứ**: `port` do OS cấp từ dải ephemeral nên `port + 1` cũng ephemeral và có thể đang bị tiến trình
  khác giữ; lúc đó kết nối thành công và `ToolError` không được ném. Đã ĐỎ THẬT trên `unit (windows-latest,
  3.13)` ở #247 với đúng thông điệp `DID NOT RAISE ToolError` — một cổng xanh lâu nay chỉ vì môi trường tình
  cờ thuận, không vì mã đúng. Nay lấy cổng chết bằng một socket đã `bind` nhưng **không `listen`** và **giữ
  nguyên tới hết ca**: kết nối bị từ chối tất định, mà không ai giành được cổng vì chính ca test đang giữ —
  hết cửa sổ đua, không chỉ thu hẹp. **Đo hai chiều**: dựng đúng điều kiện của CI (chiếm sẵn `port + 1`) →
  mã cũ **không ném ToolError**, tái hiện nguyên văn lỗi; mã mới 6/6 lần chạy đều pass. 1098 test, phủ 100%.

- fix(console): **áp lại `ticket.blocked`/`ticket.already_integrated` từ audit-log khi console replay** (#248).
  `CompanyView._replay()` chỉ gọi `DeliveryLead.replay(env)`, mà `DeliveryLead.handlers` không có mục cho topic
  `audit-log` — hai hành động chỉ sống trong RAM của orchestrator lúc chạy thật (được `orch/rehydrate.py` dựng
  lại khi mở lại tiến trình) chưa từng được console áp lại. Đo được 2026-09-10 (QLKH): TCK-CR-STAGE-001-02 đã
  `merged` từ 2026-09-06, nhưng console vẫn báo `blocked` mãi mãi và tự sinh cảnh báo "bế tắc im lặng" giả trên
  Trực ban.
- ci: **PR do máy sinh qua được cổng `metadata`** (#247). Hai vá nối tiếp nhau, cùng một họ lỗi "cấu hình chỉ
  sinh ra PR hỏng". (1) `dependabot.yml` gắn nhãn `dependencies` + `no-changelog` cho mọi PR nó mở: cổng
  `metadata` đòi dòng CHANGELOG mà dependabot không viết được, nên thiếu nhãn là **mọi** PR dependabot đỏ —
  đo trên #246: **35/36 check xanh, chỉ `metadata` đỏ** đúng vì lý do đó. Cùng quy ước với PR do
  `eval-record.yml` tự tạo (đã gắn `no-changelog` từ trước). (2) `pr-policy.yml` thêm `labeled`/`unlabeled`
  vào `pull_request.types`: cổng **in ra** lời khuyên "gắn nhãn no-changelog để miễn" nhưng gắn nhãn không
  kích nó chạy lại, và **re-run tay cũng không cứu được** vì `rerun_failed_jobs` phát lại *payload sự kiện
  gốc* — đo được: gắn nhãn 23:03:15, chạy lại 23:03:23, log vẫn in `LABELS: dependencies,python:uv`. Một
  cổng in ra cách tự cứu mà cách đó không chạy được thì tệ hơn cổng không nói gì.

- docs(console): **hướng dẫn bật động cơ nằm trong chính trang, không ở README** (#244). Tab *Hướng dẫn* có sẵn ba mục (quyền, giao việc, duyệt gate) nhưng chưa biết gì về ô Động cơ của #243, nên **bước dễ quên nhất lại không có chỗ nào trên màn nhắc**: giao việc khi động cơ chưa chạy thì event vào bus, trang báo thành công, không gì nhúc nhích, không lỗi nào cả — mà người mở console lần đầu không đọc README. Thêm: *"Một ngày trực, làm đúng thứ tự này"* (năm bước, bước 1 là bật động cơ, nói thẳng hậu quả của việc quên); *"Ô Động cơ đang nói gì"* (bảng ba trạng thái, phân biệt **người tắt** với **nó tự chết**, nhịp là gì, model lấy từ `llm.yaml`); bảng quyền ba dòng thành bốn, dòng `--allow-engine` đọc trạng thái THẬT của phiên qua `canEngine()` như ba dòng kia (bảng quyền nói phiên NÀY đang mở gì, không phải danh sách cờ trong tài liệu); khối dòng lệnh nói rõ `run --watch` **chính là** lệnh nút Bật chạy và được in nguyên văn vào đầu `platform/console/.engine/<xưởng>.log` để đối chiếu. `test_man_huong_dan_day_nguoi_truc_bat_dong_co_truoc_khi_giao_viec` canh cả bốn thứ, nên mục hướng dẫn không trôi khỏi hành vi thật. 297 test, phủ 100%.
- feat(console): **bật/tắt động cơ của từng xưởng ngay trên trang** (#243). Console làm được ba việc (nhìn, giao việc, ký gate) nhưng vòng lặp xử lý vẫn phải bật ở terminal khác — nên **giao việc khi quên bật `orchestrator run --watch` là một chế độ hỏng IM LẶNG**: event publish thành công thật, trang không báo lỗi, gate không bao giờ mở, người trực kết luận sai rằng công ty đang nghĩ. `platform/console/CLAUDE.md` phải dặn bằng chữ — dấu hiệu của thứ lẽ ra do máy đảm bảo. Nay có `engine.py` + `POST /api/engine` + ô *Động cơ* ở màn Trực ban, sau cờ **riêng** `--allow-engine` (ADR-0004 của console). Bốn ràng buộc là một phần của quyết định, không phải chi tiết cài đặt: (1) quyền riêng — `--allow-decide` KHÔNG mở nó, vì tiến trình con gọi model và ghi vào repo khách, ký gate và đốt hạn mức là hai rủi ro khác nhau; (2) **không tham số nào của client đi vào `argv`** — dòng lệnh dựng từ bảng `SPECS` chốt cứng, client chỉ đặt được `interval` kẹp [5, 3600], không `shell=True` (console đã là bề mặt HTTP duy nhất chạm được gate; biến nó thành bề mặt chạy lệnh tuỳ ý là biến một lỗ XSS nhỏ thành thực thi mã); (3) `stop_all()` ở `server_close` + `atexit` — orchestrator mồ côi vẫn ghi bus sau khi tắt console là 'công ty chạy mà không ai nhìn'; (4) trạng thái **đo được** bằng `Popen.poll()` mỗi lần hỏi, không suy từ 'đã bấm Bật' — động cơ chết vì thiếu `llm.yaml` hiện `exited` + mã thoát + 12 dòng cuối log, đúng ADR-0003 'ô rỗng là ô xám'. Model vẫn là gói thuê bao khai trong `llm.yaml`; console không truyền model, không truyền API key. Test dùng **tiến trình con thật** (`sys.executable -c`), không mock `Popen`: thứ đáng sai ở đây là vòng đời tiến trình. **Đo hai chiều**: bỏ `poll()` trong `status()` → 2 test đỏ (`exited` khai thành `running`); bỏ chặn `--allow-engine` ở `do_POST` → 2 test đỏ (403 thành 200); khôi phục → 295 test xanh, phủ 100%.
- build(deps): **gộp chín bản nâng phụ thuộc + vá gốc cấu hình dependabot cho uv workspace**. Chín PR
- build(deps): **gộp chín bản nâng phụ thuộc + vá gốc cấu hình dependabot cho uv workspace** (#245). Chín PR
  dependabot (#228–#236) mở cùng lúc và **không cái nào gộp được**: chúng chỉ nới sàn `>=` trong
  `pyproject.toml` con, còn `uv.lock` — chỉ có MỘT, ở gốc workspace — thì không đụng tới, vì lock nằm **ngoài**
  mọi `directory` dependabot được cấu hình. Mọi job CI chạy `uv sync --locked`, đỏ khi lock lệch pyproject:
  hỏng do **cấu trúc cấu hình**, không do nội dung bản nâng. PR này áp cả chín bản nâng rồi `uv lock` lại trong
  cùng một PR, và sửa gốc: `.github/dependabot.yml` còn **một** mục `uv` `directory: /` thay vì sáu mục theo
  package. Diff lock chỉ đổi dòng `specifier`, **không version nào được giải khác đi** — bản nâng là nâng sàn,
  không phải nâng gói. **Đo hai chiều**: bỏ `uv.lock` mà giữ pyproject (đúng hiện trạng chín PR kia) →
  `uv sync --locked` **exit 1** "lockfile needs to be updated"; có lock → exit 0. Cả sáu package xanh:
  gateway 251, console 297, core 477, studio 587, keeper 532, company 1098 = **3 242 test**, phủ 100%
  (đo lại sau khi rebase lên `main` mang #243/#244 — console tăng 259 → 297 vì hai PR đó, không phải vì PR này).
  Kèm **vá một cổng CI hỏng vì nguyên nhân bên ngoài**: `studio-unit` chết ở `sudo apt-get update` với exit 100
  vì source Google Chrome của runner image phục vụ `Packages.gz` lệch hash so với chính `Release` của nó —
  `apt-get update` đọc MỌI source nên một cái hỏng là cả lệnh hỏng, job chết trước khi chạy test nào. Hỏng **y
  hệt qua hai lần chạy** (cùng SHA256), nên không phải dao động. Gỡ source đó trước khi `update`; CI không dùng
  Chrome ở đâu cả. **Không** dùng `|| true`: ba test ghép video thật `skipif` trên `shutil.which("ffmpeg")`, nên
  thiếu ffmpeg là chúng lặng lẽ bỏ qua và job vẫn xanh — đúng kiểu "xanh vì rỗng".

- docs: **thêm bước "quét toàn repo trước khi tạo PR" vào `QUY-TRINH-GIT.md` §5** (#242). Rút từ chính sự cố PR
  #193 (đỏ cổng `metadata` vì thiếu dòng CHANGELOG khi cherry-pick sang nhánh khác). Bước 0 mới: `grep` dẫn
  chiếu chết trên toàn repo (không chỉ package đang sửa), kiểm CHANGELOG + bảng theo dõi thi-hành, `git
  status`/`git diff --check` trên toàn diff, và `gh pr list --state open` trước khi `gh pr create`.
- fix(console): **console đọc lại bus có ticket cũ bằng `Task.tu_log`, không `model_validate`** (#241). Console
  chết ngay ở `/api/stream` với `ValidationError: assignee Input should be 'builder'` và mặt kính trực ban chỉ
  còn một dòng đỏ "Server đọc được stream nhưng không đọc được bus" — không xem được gì. `company.events.Task`
  đã có sẵn `tu_log()` viết đúng cho việc đọc lại bản ghi trước ADR-0037/PR-5d (`assignee: "platform"` cũ chuyển
  thành `stack`), nhưng `collect._replay()` gọi thẳng `Task.model_validate()` nên bỏ qua đường tương thích đó.
  Một dòng mã, kèm **ca hồi quy còn thiếu**: bản vá gốc chỉ được "xác minh bằng mắt" — đo lại cho thấy hoàn
  nguyên nó vẫn **259/259 xanh**, tức phủ 100% chỉ nói dòng ĐƯỢC CHẠY QUA, không nói hành vi được khẳng định.
  Ca mới ghi bản ghi lịch sử THẲNG vào bảng `events` chứ không qua `bus.publish` (publish hôm nay validate theo
  schema mới, nên không dựng nổi một bản ghi cũ). **Đo hai chiều**: hoàn nguyên `tu_log` → ĐỎ đúng
  `collect.py:288 ValidationError`; khôi phục → 259 passed, coverage 100%. Rà cả họ lỗi: đây là chỗ DUY NHẤT
  trong `platform/console/src` dựng `Task` từ payload thô.
- feat(keeper): **hạ tầng eval + bản ghi bằng model thật (gói sub CLI)** (#239). `keeper` là package duy nhất trong sáu package chưa có cổng eval; nay có `evals.py`, 4 bộ ca (21 ca), job CI `keeper-eval-replay` nối vào `needs` của `quality`. **Model thật bắt hai lỗi prompt mà unit test không thấy**: `triager` xếp `semver_jump: null` (pre-release) thành `low` hai lần liên tiếp — đúng ca suýt cho tự-merge một bản pre-release; và `release-clerk` viết một báo cáo bằng chứng MỘT CHIỀU thành "đã xác minh". `regression-guard` bị BỎ khỏi bộ ca sau khi đo: nó từ chối chép `before/after` từ lời kể của `patcher` — agent đúng, ca sai. Ghi bằng gói subscription CLI, không cần API key. 532 test, phủ 100% dòng + 100% nhánh.
- fix(core): **p3.2 — cắt context theo token thật, breakpoint cache cho định nghĩa tool** (#240). Hai lỗ hổng đo được: (1) bộ cắt context và ngân sách dùng **hai đơn vị đo khác nhau** — `fit()` quyết định cắt hoàn toàn theo `len(str)` trong khi token thật từ `usage` đi đường khác vào audit và `Budget`, **không dòng mã nào so hai con số**; (2) `grep cache_control` toàn repo = **1 kết quả**, vòng tool 25 lượt có phần dài nhất không được cache. `fit(counter=...)` nhận bộ đếm ngân sách, `counter=None` cho kết quả **giống từng byte** (chốt bằng SHA-256 giá trị vàng); `ContextBudget` thêm `counted_tokens`/`actual_tokens`/`estimate_error`, nối hai đầu bằng audit `token_estimate` RIÊNG — phát ở **mọi** bước kể cả bước không bị cắt, vì chỉ đo bước bị cắt là chỉ thấy đuôi phân phối. `_first_input` lấy input token của lượt **ĐẦU**: từ lượt hai prompt đã mang thêm hội thoại tool mà `fit` chỉ đo prompt ban đầu, nên so lượt cuối là so hai thứ khác nhau rồi gọi đó là sai số. Breakpoint cache thứ hai đặt trên **định nghĩa tool cuối**: thứ tự tiền tố Anthropic là `tools`→`system`→`messages` và cache theo tiền tố, mà `system` đổi theo pha (ADR-0037) trong khi bảng tool thì không — nên mỗi lần đổi pha là ghi lại cache cả bảng tool. Không đặt trong `messages` vì phần đó bị `_prune` tỉa mỗi lượt (ADR-0007), marker ở đó chỉ ghi entry rồi không ai đọc. `cache_ttl` bảng đóng `("5m","1h")`, **mặc định TẮT** (body y hệt trước p3.2), đọc được ở cấp backend. **Gói sửa lại đặc tả hai lần**: task pack đề nghị `chars_counter` trả `len(s)/CHARS_PER_TOKEN` — sai, `max_input_chars` là số KÝ TỰ nên làm thế là nới ngân sách 3.2× và lệch mọi bản ghi eval; và TTL 1h **không** cần header `anthropic-beta`, nó là một khoá trong chính `cache_control`. 477 (632 nhánh) + 587 + 1097 test, phủ 100%; hai bộ `evals --replay --strict` 0 FAIL.
- fix(keeper): **xử lý nốt phát hiện audit — phép (d) cho drift, cổng phủ NHÁNH cho core/keeper** (#227). Bốn việc còn mở sau #226. (1) **Phép (d) `changelog_placeholder_drift`**: bốn ca thiếu dòng CHANGELOG hôm 2026-09-09 thì **ba là "quên ĐIỀN SỐ"** chứ không phải "quên viết dòng" (#161/#192 có mô tả đủ mà không có `(#n)`; #208 để nguyên `(#259)`) — phép (c) mù với cả ba khi dòng đã tồn tại, và chỉ bắt được sau khi PR đã merge. Phép mới bắt NGAY, **thuần đọc file nên không phụ thuộc độ sâu clone** (khác phép (c) — đúng chỗ đã làm tôi mù ở #226). Lọc code span trước khi dò: chính CHANGELOG này *kể lại* các ca placeholder bằng văn xuôi, và một bộ dò báo động vì tài liệu MÔ TẢ nó là bộ dò người ta sẽ tắt. (2) **`CHANGELOG.md:677` còn `(#363)`** từ 2026-09-06 → điền `(#107)`, đo từ `git log`. (3) **`CONTRIBUTING.md` ghi `fail_under` 90/84/73** trong khi cả sáu package đã là **100** từ lâu — số liệu sai trong tài liệu hướng dẫn đóng góp là thứ người mới tin đầu tiên. (4) **`dependabot.yml` thiếu hẳn `xagents-core` và `keeper`** — hai package không được quét phụ thuộc, mà `xagents-core` là lõi cả sáu package dùng chung. **Cổng phủ nhánh**: đo được **198/4966 nhánh chưa phủ** dù cả sáu xanh 100% *dòng*; `branch = true` bật cho `xagents-core` (9 nhánh) và `keeper` (3) sau khi vá hết bằng test thật — 12 test mới, không nới ngưỡng, một `pragma: no cover` duy nhất cho stub `Protocol` `ModelClient.complete` (thân `...` là khai báo kiểu, không có đường chạy tới). Bốn package còn lại giữ nguyên, khoảng cách đã đo và ghi: console 12, gateway 27, Studio-creators 60, software-company 87. **Đo hai chiều**: hoàn nguyên `(#107)` → phép (d) exit **1** đúng dòng 677; khôi phục → exit **0**. core 458 test, keeper 471, cả hai 100% dòng + 100% nhánh.
- docs(keeper): **điền số PR thật vào bảng theo dõi, ghi mục kết `/thi-hanh keeper`** (#225). Bảng §B còn `#PR` ở BT3–BT8 vì `sed` khi tạo từng PR khớp chuỗi `(#262)` CÓ NGOẶC (khuôn dòng CHANGELOG) còn bảng viết `**xong #PR**` không ngoặc. Bảng này là nguồn sự thật duy nhất của đề bài (§11 của đặc tả đã trỏ về nó), nên để sai chính là thứ nó sinh ra để chống. Kèm mục kết phiên: nghiệm thu 3 063 test trên `main@64a9414`, hai việc `chờ người` (eval-record cần model thật, canary BT8 chưa chạy), ba khuôn lỗi lặp lại suốt tám gói.
- fix(keeper): **audit sâu — nối `drift` vào CI, vá đường dẫn nguồn bản dẫn xuất** (#226). Audit chạy thật cả sáu package (lint sạch, **16.285 dòng phủ 100%, 0 miss**, file dẫn xuất sinh lại khớp từng byte) và tìm ra **một công cụ tự soi không ai bật**: `keeper.drift` phủ 100% test từ BT-keeper nhưng **không workflow nào gọi**, nên **bốn PR #161/#192/#208/#209 merge thiếu dòng CHANGELOG** mà không cổng nào đỏ — #208 còn ghi nguyên chữ `(#259)`, còn #161 và #192 có dòng nhưng **chưa bao giờ được điền số**, đúng cái bẫy `TRAPS.md` §3 đã đặt tên. **#161 chỉ lộ ra khi cổng chạy trên CI**: clone của phiên remote là *shallow* (52 commit, cũ nhất 2026-09-08) nên `keeper drift` chạy tay mù với một PR merge 2026-09-07 — đúng kiểu mù mà `fetch-depth: 0` sinh ra để chống, và là bằng chứng sống rằng cổng bắt được thứ người viết ra nó không thấy. Ba việc, một họ: (1) **bug sinh mã** `subagents.py` ghép đường dẫn nguồn từ `spec.block` — `block` là NHÃN nghiệp vụ, `supervisor.md` khai `block: supervision` mà nằm ở `agents/supervisor/`, nên `sc-supervisor.md` trỏ vào file **không tồn tại** suốt và phép (a) của drift **mù hẳn** với supervisor; nay `AgentSpec.source_rel` mang đường dẫn THẬT do `load_agents` đặt (`p.relative_to`), sửa cả lệnh `list` cùng họ. (2) **fail-open** `_source_version` trả `1` khi thiếu file nguồn, khiến lỗi đường dẫn hiện ra dưới dạng "nguồn hiện version=1" — người đọc đi tìm một lần tăng version không hề có; nay trả `None` và báo đúng "KHÔNG có file đó". Test cũ `test_sc_agent_drift_nguon_khong_ton_tai` **đóng đinh chính fail-open ấy** (đòi im lặng), đã đổi chiều. (3) job CI `drift-check` mới với **`fetch-depth: 0`** — điều kiện đúng/sai chứ không phải tinh chỉnh: depth mặc định (1) làm `git log` chỉ có một commit, không PR nào bị soi, cổng **xanh giả**. Kèm vá số liệu README đã cũ (company 1044→**1087**, studio 514→**580**, core 236→**450** test; K3.1–K3.7 đã xong hết chứ không "còn K3.5c"). **Đo hai chiều**: hoàn nguyên (1) → `drift` exit **1** kèm đúng tên `sc-supervisor.md`; đổi `(#208)` về `(#PENDING)` → exit **1**; khôi phục cả hai → exit **0**, "drift: sạch".
- feat(core): **p3.3b — điểm trong bản ghi eval, dọn khoá rác khi ghi đủ bộ** (#238). Đề bài gốc là "điểm trung bình n lần chạy tụt quá ngưỡng → CI đỏ"; đo hiện trạng cho thấy **không đặt được ở chỗ đó**: `--replay` tất định (khoá `hash(system,user)`, giá trị `text` đã ghi) nên chạy lại trăm lần ra đúng một số — **dao động sinh ra lúc GHI**. Nên `--runs N` nằm ở `RecordingClient`, và bản ghi nay có hai trường tuỳ chọn `score` (tỉ lệ đạt trên N lần) + `runs`; bản ghi cũ không có chúng vẫn chạy, `load_recording_score` trả `None` chứ không raise. Chốt cưỡng chế bằng mã chứ không chỉ bằng tài liệu: `--runs > 1` mà không `--record` bị từ chối ngay (im lặng tốn N lần thời gian không đổi kết quả), `--runs < 1` cũng vậy. `score` là số đo **độ ổn định lúc ghi**, không phải nhãn pass/fail của câu trả lời được lưu — `text` giữ lần chạy cuối và replay vẫn chấm chính nó bằng `check`; nó **giảm** rủi ro đọc một lần đỏ thành hồi quy, không **loại bỏ** dao động (`companies/software-company/TRAPS.md`). `save(prune_to=)` dọn khoá rác — `product.json` có 32 khoá cho 16 ca, `qa.json` 15/8, `security.json` 12/10, `supervisor.json` 8/3 — nhưng **chỉ khi chạy đủ bộ và không ca nào lỗi** (`ns.agent == "all" and not any(r.errored)`): dọn lúc chạy một agent lẻ là xoá bản ghi thật. `save()` không tham số giữ nguyên hành vi gộp. 457 + 587 + 1091 test, phủ 100%; hai bộ `evals --replay --strict` 0 FAIL.
- feat(keeper): **BT8 — tab console bảo trì, hướng dẫn vận hành, trạng thái thật** (#223). Tab `bao-tri` đọc SQLite chỉ-đọc rồi replay qua bus thật. **Chống "số xanh vì rỗng"**: `ran = ok AND log không rỗng` — file DB có mà log rỗng vẫn là *chưa chạy*; chưa chạy thì mọi ô là `null`, trang in "—" kèm "chưa chạy lần nào", kể cả ô "Nợ quá hạn". **Lỗ chặn nhầm cùng họ với BT2**: `_VALUE_FLAGS` thiếu mọi cờ của `gh pr create`, nên một PR bảo trì có tiêu đề đúng bằng chữ `merge` bị chặn như lời gọi ghi — đúng thứ I1 CHO PHÉP. **Canary chưa chạy** — nghiệm thu của BT8 còn mở.
- feat(core): **p3.3 — cổng điểm eval cho studio, ngưỡng lên core** (#224). `software-company` có cổng điểm (`evals/thresholds.yaml`, `check_thresholds`, CI `--strict`); `Studio-creators` **không có** — `_one` khi `--replay` chỉ trả `not any(r.errored)`, nên **14/20 agent của repo có ca chấm SAI NỘI DUNG mà CI vẫn xanh**. `Threshold`/`load_thresholds`/`check_thresholds` chuyển lên `xagents_core.evals` (ADR-0001 "core giữ cơ chế") với `ScoredOutcome` Protocol duck-typed — `gate_ok`/`cases_ok` là chính sách riêng của company, không kéo lên lõi; đường dẫn `thresholds.yaml` do **người gọi** truyền, core không hằng hoá đường dẫn của một công ty. `Studio-creators/evals/thresholds.yaml` mới: 14 agent, `min_pass_ratio: 0.95`, `cases: 2` — đo thật bằng `studio.evals all --replay` (14/14 đạt 2/2 = 1.00, làm tròn xuống 0.05 theo quy ước `CONTRIBUTING.md` §3). Với 2 ca thì một ca hỏng là 0.50, đỏ ngay. **Gói tìm ra một test đang đóng đinh chính lỗ hổng nó bịt**: `test_replay_exit_code_ignores_grading_but_not_stale_recordings` dựng bản ghi `publisher` chấm 1/2 rồi đòi exit 0 — giữ nguyên thứ nó sinh ra để đo (cổng **bản ghi**) bằng cờ `--no-thresholds` mới, và thêm dòng khẳng định chiều mới. `companies/software-company/Makefile` `eval-replay` thêm `--strict` cho khớp CI; hệ quả là nó trùng lệnh hệt `eval-thresholds` nên chú thích target kia sửa thành "bí danh" kèm lý do giữ tên (`CONTRIBUTING.md` §3 dẫn nó). **Đo hai chiều thủ công**: đòi 3 ca khi chỉ có 2 → `FAIL analytics-analyst: bộ ca bị thu nhỏ`, exit 1; khôi phục → exit 0.
- feat(core): **p3.1 — span quanh bước agent, lời gọi LLM và tool call (ADR-0009)** (#222). Repo có 6 package chạy song song mà **0 dòng đo thời gian** trong đường gọi model; thời gian duy nhất là `Generated.duration_ms` — một số phẳng cho cả bước, nên "bước 40 giây này chậm ở model hay ở tool" là câu không trả lời được. `xagents_core/observe.py` thuần stdlib (`Span`, `SpanSink` Protocol, `NullSink`, `MemorySink`, `span()`, `use_parent()`, `otel_sink()`), chèn ở **đúng ba ranh giới phía GỌI** — `ToolBox.call`, `_complete`, `generate`. Chèn phía client thì `RoutingClient`→`RetryingClient`→`AnthropicClient` sinh **3 span cho 1 lượt** và số span đổi theo `backends:` chứ không theo việc thật sự làm. **Mặc định no-op thật sự**: `sink=None` thì không cấp phát, không đọc đồng hồ (ca chiều ngược monkeypatch `time.monotonic_ns` cho ném lỗi). Cha truyền bằng `ContextVar` vì một `AgentRunner` phục vụ nhiều ticket song song trong `ThreadPoolExecutor` — ô nhớ dùng chung sẽ gán lượt model của ticket A làm cha cho tool của ticket B. **Đánh đổi có chủ ý**: trong `_turns` tool chạy SAU khi `_complete` trả về nên span `llm.complete` đã đóng; giữ nó mở tới hết vòng tool sẽ phá chính latency model mà span sinh ra để đo, nên cha gắn tường minh và `tool.call` có timestamp sau `end_ns` của cha. **Hai trợ lý chấm hội tụ vào cùng một chỗ từ hai hướng**: `sc-qa` thấy đường MCP không có test cây span, `sc-builder` tìm ra lý do — `ToolBridge` chạy `toolbox.call` trên thread handler nên `contextvars` Context rỗng và span mất cha; nay là **giới hạn đã đo** (ADR bổ sung + test khẳng định `parent is None`, và test ấy đỏ nếu ai truyền `copy_context()` qua cầu). `sc-builder` cũng bắt `_TURN_SPAN.set()` chạy cả khi sink tắt — cấp phát một Token trái quyết định 5, đã guard. 438 + 1083 test, phủ 100%; **cả hai bộ `evals --replay` 0 FAIL** nên không bản ghi eval nào phải ghi lại.
- docs(core): **p3.0 — ADR-0009 quan sát được bằng span** (#220). Điều kiện vào của `p3.1`: repo có 6 package chạy song song mà **0 dòng đo thời gian nào trong đường gọi model** (`grep monotonic|latency|elapsed` trên 4 file llm/runner = 0); `Completion` không có trường thời gian; thời gian duy nhất là `Generated.duration_ms` — một số phẳng, chỉ company, cộng cả bước agent nên không tách được "chậm ở model hay ở tool", trong khi một bước có thể là 25 lượt `complete`. Sáu quyết định: span sống **song song** `trace.py` chứ không thay (trace đọc bus post-hoc, span đọc đồng hồ trong tiến trình; đẩy span lên bus = 25 event rác/bước); đúng ba ranh giới `runner.step`/`llm.complete`/`tool.call`; chèn **phía gọi** vì `ModelClient` là Protocol với 12 `def complete` lồng nhau (routing → retry → recording → adapter) nên đặt ở client sinh 3 span cho 1 lượt và số span đổi theo cấu hình `backends:`; core **không thêm dep bắt buộc** (3 dep runtime, mypy `strict` không có `--ignore-missing-imports` toàn cục → `import opentelemetry` ở đỉnh file là CI đỏ) nên lớp span thuần stdlib + `SpanSink` Protocol, sink OTel import trong hàm; mặc định no-op không cấp phát; span **không được đổi nội dung gửi model** → `p3.1` không ghi lại bản ghi eval nào. Giới hạn đã biết, chấp nhận: chế độ `cli` (ADR-0023) không qua `ToolBox` nên không có span `tool.call`. **`sc-supervisor` CHẶN một lần**: ADR khai "core llm.py ×6" trong khi thực tế 5 (474 là khai báo Protocol, 4 hiện thực) — tổng 12 đúng nhưng phân bố sai, mà phân bố mới là bằng chứng của quyết định 3; đã sửa. Số ADR cũng suýt sai: 0008 đã bị #216 chiếm.
- docs: **p3 — đặc tả thi hành ba việc production: span, token thật, cổng điểm eval** (#219). Đề bài ban đầu sai hai phần ba: ba subagent `Explore` chỉ đọc đo hiện trạng và chứng minh prompt caching **đã có** (`cache_control` ở `llm.py:550`, `prompt_cache_key`, kế toán `cache_hit_ratio`, giá cache riêng) và cổng điểm eval **đã có** cho company (`evals/thresholds.yaml`, `check_thresholds`, CI `--strict`). Ba lỗ hổng thật lộ ra khi đo: studio không có ngưỡng điểm nào (14/20 agent, ca sai nội dung luôn xanh); "điểm trung bình n lần chạy" không áp được cho replay vì replay tất định — dao động sinh ra lúc GHI, mà bản ghi không có trường điểm; khoá rác tích tụ (`product.json` 32 khoá cho 16 ca). Tracing thì đúng là trống: 0 dòng OTel, "trace" hiện tại là dựng lại post-hoc từ audit-log. Bảng A2 21 dòng, mỗi ô có `file:dòng`.
- feat(keeper): **BT7 — release-clerk, human gate `keeper`, vòng lặp orchestrator** (#221). Công ty bảo trì chạy được một vòng: `watch → triage → patch → verify → gate? → release`, resume qua `SQLiteBus`, `keeper watch`. `orchestrator.pr_blockers()` là NƠI DUY NHẤT ghép bốn cổng đã dựng ở BT4–BT6 (đường cấm người-mới-quyết, bằng chứng hai chiều, gate cho tier `high`, ngân sách). 10 system prompt + checklist gate + golden. **Ba chỗ đặc tả §9 sai đã sửa theo phép đo** (`SQLiteBus` chứ không `SqliteBus`; `HumanGate` chỉ có `decide()`; `approve` KHÔNG phải reopen). ADR-0006 ghi "8 agent" nhưng chính bảng của nó liệt kê 10 — lỗi đếm, đã sửa cả ba tài liệu. 437 test, phủ 100%.
- feat(keeper): **BT7 — release-clerk, human gate `keeper`, vòng lặp orchestrator** (#221). **`sc-security`/`sc-qa` bắt 4 lỗ, đã sửa**: thế hệ khoá chống-trùng KHÔNG BAO GIỜ tăng (`_generation` đếm `status=="closed"` mà không chỗ nào đặt trạng thái đó) — nay chống trùng theo `Envelope.event_id`; cổng bằng chứng bị vòng qua ở đường TIÊU THỤ (`_apply` nạp mọi `verification-reports` không kiểm lại); I3 thủng trong cùng một nhịp (N ticket đủ cổng ⇒ N release-note vì `open_pr` không tạo PR thật); và **không có đường cho người duyệt gate** — công ty tự khoá chính mình, nay có `keeper gate` CLI. Công ty bảo trì chạy được một vòng: `watch → triage → patch → verify → gate? → release`, resume qua `SQLiteBus`, `keeper watch`. `orchestrator.pr_blockers()` là NƠI DUY NHẤT ghép bốn cổng đã dựng ở BT4–BT6 (đường cấm người-mới-quyết, bằng chứng hai chiều, gate cho tier `high`, ngân sách). 10 system prompt + checklist gate + golden. **Ba chỗ đặc tả §9 sai đã sửa theo phép đo** (`SQLiteBus` chứ không `SqliteBus`; `HumanGate` chỉ có `decide()`; `approve` KHÔNG phải reopen). ADR-0006 ghi "8 agent" nhưng chính bảng của nó liệt kê 10 — lỗi đếm, đã sửa cả ba tài liệu. 437 test, phủ 100%.
- feat(keeper): **BT6 — bằng chứng đo hai chiều bắt buộc, rà cả họ lỗi, security-auditor** (#218). Bất biến I2 thành cổng máy: `require_two_way` từ chối khi `before` xanh (tắt bản sửa mà vẫn xanh ⇒ test không đo gì). **`sc-security` bắt một lỗ thủng thẳng I2**: bộ lọc self-claim chỉ bỏ `verified_by`, còn `before`/`after` cũng là số đo nhưng không bị lọc và payload lại thắng khi hợp nhất — model khai hai trường đó là dựng được báo cáo hợp lệ mà KHÔNG lệnh nào chạy. Nay lọc đúng tập trường code tự đo (khoá bằng test) và hợp nhất số đo SAU. `collect_two_way` từ chối checkout chung (`git stash --include-untracked` cất cả worktree, không chỉ diff). `family_safe` mang theo LÝ DO tới tận schema topic. 333 test, phủ 100%.
- feat(core): **allowlist vai được TẠO gate** (#216). Nửa còn lại của lỗ hổng `gate.request` mà ADR-0002
  cố ý hoãn: agent nào cũng dựng được gate ma. `PersistentGate.REQUEST_ACTORS` (ADR-0008) liệt kê vai được mở
  gate của từng công ty — người luôn được phép; chiều ghi ném `PermissionError` (bug ở call site phải lộ),
  chiều replay im lặng bỏ qua (một dòng log xấu không được làm sập sổ gate). **Đo trên `company.sqlite` thật
  18293 event trước khi siết**: 33 gate lịch sử do vai trước ADR-0037 tạo → `LEGACY_GATE_ACTORS` giữ chúng lại.
  Lộ luôn một fixture bịa của console (`publisher` chưa từng mở gate nào; gate `publish` do `desk` mở).
- fix(studio): **`claude -p` không tool cần > 1 lượt** (#214). `--max-turns 1` cắt đúng lượt CLI ép
  `--json-schema` → `error_max_turns`: `make eval-record` bằng model thật chết 1/2 ca ở `seo-optimizer`. Company
  đã đo và vá cùng lỗi này 2026-09-05 (`CLI_NO_TOOL_TURNS`), studio không được port — nay port sang. Đo hai
  chiều bằng chính model thật: trước 1/2 pass, sau 2/2 pass; test cũ khẳng định `== "1"` sửa thành `> 1`.
- feat(keeper): **BT5 — patcher trên worktree riêng, đường cấm, chạy khô** (#217). Ba thao tác (`bump_dependency`, `regen_derived`, `fix_docs`); `keeper run --dry-run` không chạm file nào (đo bằng hash cây thư mục). **`sc-security` bắt 4 lỗ, đã sửa**: đường GHI không có chốt checkout chung và `--root` mặc định `"."` (gõ trong checkout chung là ghi thẳng vào nó); `_changed_files` nuốt lỗi `git` nên chốt sau-khi-chạy thành rỗng; chốt `fail_under` chỉ đếm dòng nên đổi header TOML là lọt (nay parse `tomllib` và so GIÁ TRỊ); `.github/` và `.git/` không nằm trong bảng cấm — tức `keeper` gỡ được chính cổng CI đang ép nó. 272 test, phủ 100%.

- fix(core): **`gate.request` tin `env.actor`, không tin `created_by` tự khai** (#212). Phát hiện NGHIÊM TRỌNG
  còn lại của `sc-security` ở K3.7, pre-existing từ trước khi hợp nhất: `PersistentGate.apply()` đọc thẳng
  `created_by` trong evidence của một topic MỞ, nên một envelope `gate.request` mang `created_by` bịa là đủ để
  chính người ghi tự duyệt gate của mình (four-eyes ở `decide()` so nhầm với tên bịa). Nay `created_by` lấy từ
  `env.actor` — cùng bất biến `trusted_decision` đã áp cho `gate.decide`. ADR-0002; ca test đo hai chiều.
- feat(keeper): **BT3 — dependency-scout, health-monitor, drift-detector** (#213). Khối watch: gộp trùng signal theo `(kind, subject)`, semver + dev-dependency đọc từ `[dependency-groups]` thật, flake rate và p50/p95 thời gian CI, ba phép so drift thuần cục bộ. **Hai chỗ đặc tả sai đã đo lại**: dấu vết nguồn của `.claude/agents/sc-*.md` là số `version` trong HTML comment chứ không phải hash trong front matter; `gh run list --json` dùng `startedAt`/`updatedAt` chứ không phải tên REST thô. Mốc chặn dưới của phép so CHANGELOG đo từ `git log` của `AGENTS.md` (a82a804, 2026-09-07T19:41:01+07:00), không phải danh sách số PR. 129 test, phủ 100%.
- feat(keeper): **BT4 — risk_tier bảng dữ liệu, sổ nợ có đáo hạn, ngân sách thay đổi** (#215). `risk.py` là BẢNG tra cứu 8 hàng (khớp hàng đầu, high trước low), không phải chuỗi `if`; `semver_jump is None` (pre-release, BT3) rơi vào `medium` chứ không `low` — chưa biết bậc nhảy không đồng nghĩa an toàn. `ledger.py` là cơ chế MỚI đo hạn theo lịch, **không phải** `debt_due` của lõi (cái đó đếm chuỗi review liên tiếp, không đọc đồng hồ) — §6 của đặc tả nói sai, đã sửa theo phép đo. `budget.can_open_pr()` hỏi GitHub mỗi lần, không giữ biến đếm trong RAM. Thêm cổng chống lệch hợp đồng topic: trường có trong model payload mà thiếu trong `topics/schemas/*.json` là CI đỏ. 184 test, phủ 100%.
- feat(keeper): **BT3 — dependency-scout, health-monitor, drift-detector** (#215). Khối watch: gộp trùng signal theo `(kind, subject)`, semver + dev-dependency đọc từ `[dependency-groups]` thật, flake rate và p50/p95 thời gian CI, ba phép so drift thuần cục bộ. **Hai chỗ đặc tả sai đã đo lại**: dấu vết nguồn của `.claude/agents/sc-*.md` là số `version` trong HTML comment chứ không phải hash trong front matter; `gh run list --json` dùng `startedAt`/`updatedAt` chứ không phải tên REST thô. Mốc chặn dưới của phép so CHANGELOG đo từ `git log` của `AGENTS.md` (a82a804, 2026-09-07T19:41:01+07:00), không phải danh sách số PR. 129 test, phủ 100%.
- feat(keeper): **BT2 — adapter `gh` chỉ đọc, bộ đệm TTL, `FakeGitHub`** (#211). Bất biến I1 (`keeper` không có quyền ghi) thành mã: `_run()` ném `GitHubWriteAttempt` trước khi chạm subprocess. **Bảng chặn của đặc tả có lỗ, đo được ở đây**: `gh api` chuyển sang POST ngay khi có `-f/-F/--field/--raw-field/--input` mà không cần `-X`, nên `gh api repos/o/r/pulls/1/merge -f x=y` lọt qua bảng gốc — thêm năm cờ đó. Bộ đệm TTL 60s theo argv, đồng hồ tiêm được nên test không `sleep`. 61 test, phủ 100%.
- docs: **kịch bản B 4 lớp đủ 8/8 — tổng kết 4L-1b/4L-4 chạy bằng gói sub CLI** (#209). 4L-1b và 4L-4 chạy được bằng backend `claude-code` (gói sub CLI, không cần API key trả theo token) thay vì đợi "máy có key" — sửa hiểu nhầm phạm vi của các phiên trước, vốn đã hoãn hai mã này qua nhiều đợt. Ghi lại toàn bộ diễn biến vào nhật ký phiên: PR #204/#206/#208, đo hai chiều, kẹt luật một-PR-một-lúc ba lần, và bẫy nhãn `no-changelog` không tự re-run. Chỉ tài liệu (`docs/KIEN-TRUC-4-LOP.md`, `docs/sessions/2026-09-09.md`).
- feat(keeper): **BT1 — khung package thứ sáu, CoreConfig và topic** (#210). Cơ sở hạ tầng package, mô hình dữ liệu, schema topic bảo trì; mỗi phần có test đo hai chiều.
- docs(keeper): **BT0 — đổi tên công ty bảo trì thành `keeper` + đặc tả triển khai** (#207). ADR-0006 đổi
  tên file và nội dung (`Upkeep-crew` → `keeper`); thêm `companies/keeper/README.md` và `companies/keeper/docs/DAC-TA-KEEPER.md`
  — 9 PR BT0–BT8, 7 bất biến, bản đồ 9 topic, mỗi mục có test đo hai chiều và cạm bẫy. Chưa có mã.
- docs: **ADR-0007 — tỉa tool output cũ trong vòng tool** (#206). Quyết định chuẩn bị cho 4L-4
  (`docs/KIEN-TRUC-4-LOP.md`): tỉa `role=tool` cũ hơn `keep_turns=3` lượt gần nhất trong vòng tool
  (`company.runner._turns`, `studio.runner._tool_loop`), thay bằng placeholder `[đã cắt: <tool> <chars> ký tự,
  hash <h>; gọi lại nếu cần]`; không tỉa `msgs[0]`, giữ nguyên `tool_calls`. Chỉ tài liệu — code ở PR riêng.
- feat(core): **4L-4 — tỉa tool output cũ trong vòng tool (ADR-0007)** (#208). `xagents_core.context._prune(msgs,
  keep_turns=3)` (hàm thuần): message `role=tool` cũ hơn 3 lượt gần nhất trong vòng tool thay bằng placeholder
  `[đã cắt: <tool> <chars> ký tự, hash <h>; gọi lại nếu cần]`; giữ nguyên `msgs[0]` (yêu cầu gốc) và `tool_calls`
  của `assistant`. Ghép vào `company.runner._turns` (gọi khi `turn > NO_PROGRESS_WARN`, audit `context_pruned`)
  và `studio.runner._tool_loop` (`PRUNE_KEEP_TURNS = 3`, audit tương tự) — hai vòng tool RIÊNG (chưa hợp nhất
  trên core), chỉ dùng chung hàm `_prune`. Đo trên fake 15 lượt × 6k ký tự/lượt (`companies/software-company/tests/
  test_runner_no_progress.py`): không tỉa thì lượt cuối phình gấp ~4.7 lần mốc ổn định (lượt 4), tỉa giữ nó dưới
  3 lần (đo hai chiều: tắt `_prune` bằng monkeypatch → test đỏ đúng như dự đoán). `evals all --replay --strict`
  hai công ty: mọi bản ghi hiện có (company 58 ca, studio 28 ca) PASS KHÔNG ĐỔI — không ca eval hiện tại nào có
  ≥ 4 lượt tool nên `_prune` chưa từng kích hoạt trên bộ ca đang có; ghi lại thật một agent mỗi công ty
  (`supervisor`) để xác nhận model thật vẫn chạy đúng qua code path mới. ADR: `docs/adr/0007-tia-tool-output-cu-trong-vong-tool.md`.
- fix(core): **thế hệ gate là bộ đếm, không phải dấu thời gian tường** (#203). Phát hiện 4 của audit
  2026-09-09. `scheduler._the_he` phân biệt hai thế hệ gate của cùng `subject_id` bằng
  `created_at.isoformat(microseconds)`, và nó hỏng theo HAI đường: (1) `datetime.now(UTC)` trên Windows có bước
  ~15,6 ms — đo được `timedelta(0)` giữa hai lần gọi liên tiếp, 5/5 lần lặp — nên hai gate mở cách nhau <16 ms
  mang CÙNG dấu thời gian, chung khoá `once`, và lần quá hạn của gate thứ hai bị nuốt: không audit
  `gate.overdue`, không escalate, gate bể hạn nằm im y hệt gate mới — đúng thứ TRAPS §1 khuôn 3 mà khoá ấy sinh
  ra để chặn; (2) lúc phát lại, gate được `request()` LẠI nên `created_at` là bây giờ chứ không phải mốc gốc,
  khoá đổi sau mỗi restart và một gate đã escalate lại escalate lần nữa. Nay `HumanGate.request()` gán
  `GateRequest.seq` tăng dần: không đọc đồng hồ, và phát lại cùng một log theo cùng thứ tự thì gate thứ ba vẫn
  là gate thứ ba. Kèm theo: `test_overdue_khong_truyen_now_thi_lay_bay_gio` không còn dựa vào thời gian trôi
  giữa hai dòng lệnh (biên "đúng bằng timeout thì chưa quá hạn" là cố ý, chỗ sai là ca test).
- ci: **chân Windows cho `core`/`gateway`/`console`; `mypy` core sạch trên cả hai nền tảng** (#205). Phát hiện
  5 của audit 2026-09-09: chỉ `unit` (software-company) và `studio-unit` có chân Windows. Ba package kia — gồm
  `xagents-core`, nơi K3.1–K3.7 vừa dồn TOÀN BỘ cơ chế chung của hai công ty — chưa từng chạy trên Windows,
  nên package rủi ro cao nhất lại có phạm vi nền tảng hẹp nhất. Hậu quả đo được: lỗi thế hệ gate (#203) tái
  hiện được trên Windows mà CI không hề thấy. Ba package này không bỏ lại nhánh chỉ-POSIX nào nên chân Windows
  đo `--cov` luôn (kiểm tại chỗ: cả ba đúng 100% trên Windows), khác `unit`/`studio-unit` phải bỏ coverage.
  `core-static` cũng thành hai nền tảng, và để nó xanh được thì `sqlite_bus._alive` rẽ nhánh theo
  `sys.platform` thay vì `os.name`: mypy THU HẸP theo `sys.platform` chứ không theo `os.name`, nên chú
  `# type: ignore[attr-defined]` ở `ctypes.windll` CẦN trên Linux lại THỪA trên Windows — và core bật `strict`
  nên "thừa" cũng là lỗi. Tức là `mypy src/xagents_core` chưa bao giờ xanh được ở cả hai nơi cùng lúc; nay
  sạch cả hai, không cần chú nào. Kèm phát hiện 7: `actions/checkout` v4 → v7 ở `protection-guard` và
  `pr-policy` (hai chỗ cuối còn v4, đang sinh cảnh báo Node 20 deprecated).

- docs(adr): **ADR-0006 công ty con `keeper` bảo trì toàn dự án** (#201). Chỉ là quyết định kiến
  trúc, chưa có mã: 6 khối / 8 agent / gate `keeper`, 10 tính năng nâng cao (bậc rủi ro, bằng chứng đo hai
  chiều bắt buộc, ngân sách thay đổi, sổ nợ có đáo hạn), lộ trình 5 PR.
- fix(company): **DB chạy thật không mở lại được sau khi `Assignee` thắt về `builder`** (#203). Audit toàn diện
- fix(company): **DB chạy thật không mở lại được sau khi `Assignee` thắt về `builder`** (#202). Audit toàn diện
  2026-09-09 chạy `company.orchestrator status` trên `company.sqlite` của QLKH (17,9 MB, 18 293 event) và nhận
  `ValidationError: assignee — Input should be 'builder' [input_value='platform']` **trong `Orchestrator.__init__`**:
  ADR-0037/PR-5d gộp 21 agent thành 5 và thu `Assignee` về một giá trị, nhưng bus là bản ghi bền — 7 bản ghi
  `plan.proposed` và mọi event `tasks` lập trước đó còn mang từ vựng cũ. Vì vỡ ở `_rehydrate`, **không lệnh nào**
  mở nổi DB đó nữa, kể cả `status` chỉ đọc; restart = mất dịch vụ vĩnh viễn. Vá: `Task.tu_log()` — một đường đọc
  khoan dung dùng ở **mọi** đường phát lại (`_dispatch_plan(replaying)`, `delivery._replay_task`,
  `supervisor._on`, `supervisor._sprint_report`), đường sinh MỚI (`ticket_fsm:98`) và `guard` lúc publish vẫn
  nghiêm ngặt. Sáu `assignee` cũ trùng đúng `BUILD_PHASES` nên chúng chuyển sang `Task.stack` thay vì bị vứt;
  `assignee` lạ vẫn ném. Rà cả họ (luật 5): vá chỗ thứ nhất xong thì chỗ thứ hai (`supervisor.replay`) lộ ra —
  cả 4 chỗ đọc lại đều đã đổi. Bằng chứng: `status` trên chính DB đó nay in đủ 38 ticket và 101 ruling.
- fix(company): **`integration.skipped` ngập audit-log — 78% cả sổ** (#202). Cùng lần audit: 13 399 / 17 278 bản
  ghi audit-log của QLKH là `integration.skipped`. Nhánh "không có worktree" trong `worktree_flow.merge_ticket`
  `return True` mà không đổi trạng thái gì, nên mỗi nhịp watch ghi lại một bản y hệt — trong khi các audit anh em
  cùng vòng lặp (`gate.overdue`, `gate.escalate`) đều có khoá `once`. Không phải chuyện dung lượng: `metrics.py`
  và `platform/console/collect.py` đọc "sự thật" từ chính sổ này. Thêm `once=f"integration.skipped:{release_id}:{tid}"`.

- docs(sessions): **ghi phiên vá `gate.request` created_by** (#200). Chỉ nối `docs/sessions/2026-09-09.md`,
  không đổi hành vi.
- chore(company): **4L-1b — security ≥ 10 ca eval** (#204). `evals/security.yaml` 2 → 10 ca, phủ 6 nhóm:
  (a) spec `kind=application` có `runtime` → threat-model; (b) release-check chạm PII thiếu DPIA → block; (c)
  `risk_tags` auth/payment/pii mỗi tag một ca deep-review; (d) payload PR chứa chỉ thị giả mạo → không nghe theo;
  (e) threat-model thiếu DFD → không tự duyệt; (f) `rulings[].cost_if_wrong` khi tự quyết thay vì chờ người.
  `evals/thresholds.yaml` `security.cases: 2 → 10`. Ghi lại `evals/recordings/security.json` bằng model thật
  (`COMPANY_LLM_BACKENDS=claude-liendv`, backend `claude-liendv`): 10/10 pass. 6 test trong
  `tests/{test_runner_and_persistence,test_tools_and_agentic}.py` giả định "security đúng 2 ca, một topic ra" —
  cập nhật `_security_handler`/`_input_payload` handler để suy verdict theo payload của từng ca thay vì hằng số,
  và số ca kỳ vọng 2→10 (11 ở ca "một ca lỗi không xoá ca tốt"). Không chạm `agents/quality/security.md` (version
  không tăng — prompt không đổi), không chạm `.claude/agents/`.
- fix(core): **`HumanGate.request()` từ chối `created_by` rỗng/None** (#199). Lỗ hổng bypass four-eyes
  pre-existing (có trước K3.7): `decide()` chỉ kiểm `if req.created_by and req.created_by == by`, nên
  `created_by` rỗng/None ngắn mạch điều kiện, cho phép người tạo tự duyệt gate của chính mình. `request()` nay
  chặn tại nguồn (allowlist mặc định từ chối) thay vì để lộ ở `decide()`. Rà `GateRequest(` toàn repo: mọi call
  site sản phẩm đã truyền `created_by`; 1 test (`companies/software-company/tests/test_delivery_and_gates.py::test_gate_timeouts`)
  thiếu, đã sửa. ADR: `docs/adr/0005-gate-request-tu-choi-created-by-rong.md`.
- refactor(core): **K3.7 — gates, gate_cli, supervisor hợp nhất hai chiều** (#198). Bước cuối kịch bản B:
  `xagents_core/{gates,gate_cli,supervisor,ticket_model}.py` mới, company/studio kế thừa, giữ tên method khác
  miền (`report()` studio, `sprint_report()` company). Company lần đầu có allowlist người duyệt
  (`COMPANY_GATE_APPROVERS`, mặc định tắt = hành vi cũ). `sc-security` phát hiện và PR vá luôn 2 lỗ hổng CAO do
  chính tính năng mới sinh ra: console mở gate company không truyền allowlist; đóng gate nghiệm thu khách bị
  chặn nhầm vì chữ ký khách không phải người duyệt nội bộ (`enforce=False`). Chi tiết + phát hiện cố ý không vá
  (pre-existing, ngoài phạm vi): `docs/thi-hanh/k3.7.md` mục G.
- docs: **4l — 4L-4 vẫn chờ người, kết phiên đợt 3-4** (#197). 4L-6 (#190), 4L-7 (#196) merge sau K3.5c/K3.6
  (#187-#195); 7/8 mã bảng B xong. 4L-4 đủ điều kiện K3.6 nhưng `_prune()` lệch hash bản ghi eval, cần key
  model thật (cùng ràng buộc 4L-1b) — phiên remote không có key. Chỉ tài liệu.
- feat(studio): **4L-7 — trace một video và hẹn hoãn sống sót restart** (#196). Studio không có gì tương đương
  `company.trace`: muốn biết một video đã đi qua những gì, ai ký gate publish và vì lý do gì là phải mở SQLite
  tra tay. Phần chung của hai công ty (cấu trúc dòng, đọc `audit-log`, tổng kết, cách in) lên
  `xagents_core/trace.py`; `company/trace.py` rút gọn còn `resolve`/`_belongs`/`_domain` của mình;
  `studio/trace.py` mới, mở DB `mode=ro`. Kèm theo: `defer.until` — bản ghi hẹn hoãn đã có trên audit-log từ
  K3.3d nhưng chưa ai đọc lại — nay được `Orchestrator._nap_lai_hen` nạp lúc `_rehydrate`, nên mở lại tiến
  trình không còn mất hẹn và gọi thẳng backend vừa nói "thử lại sau 1515s". Chỉ nạp hẹn của event CHƯA có
  `orchestrated`, khoá theo `event_id` (TRAPS §1 khuôn 3), không đụng `last_sync`.

- refactor(core): **K3.6d2 — `AgentRunner` (phần ngoài) lên `xagents_core`; K3.6 XONG** (#195). Nguyên tắc của
  bước này gắt hơn mọi bước trước: *cơ chế lên core, **hành vi quan sát được của mỗi công ty giữ nguyên từng
  byte***. Lên core: `__init__`, `_audit`, `run`, `run_context`, `write_context`, `publish`. Ở lại từng công ty:
  `generate` và vòng lặp tool (chúng dựng prompt — prompt là khoá bản ghi eval, xem K3.6d1),
  `generate_in_workspace`/`author_tests` (phụ thuộc `workspace.py`), `_filter_comments` (studio).
  **Hai chỗ "lấy bản company" sẽ đổi hành vi studio âm thầm; cả hai giải bằng THAM SỐ chứ không bằng quyết
  định**, nên không bên nào mất gì: (1) `write_context` của company audit `context_no_content` khi thiếu toàn
  văn, mà `context_writes` của studio **không bao giờ có `content`** → chép nguyên bản là mỗi lần ghi context
  của studio sinh một audit rác; nay là cờ `wants_content` (mặc định `False`). (2) `publish` của company dựng
  envelope bằng `inp.child(...)` (nối `correlation_id`/`causation_id`), studio dựng `Envelope(...)` mới → cho
  studio `child()` là **đổi nội dung event trên bus**, nghe như cải tiến nhưng là thay đổi dữ liệu; nay là hook
  `_new_envelope`. Hai hook nữa cùng loại: `_audit_scope` (trường phạm vi `AuditLog` — khuôn K3.5a) và
  `_produced_evidence` (câu evidence của `produced:*`, hai công ty ghi hai thứ khác nhau vào sổ).
  **Đo hai chiều lần đầu để lộ một lỗ hổng của chính bộ test**: bật `wants_content` và ép `_new_envelope` dùng
  `child()` làm **ba ca của core đỏ nhưng cả 557 ca của studio vẫn xanh** — nghĩa là nếu ai đó "dọn" hai hook ấy
  đi cho gọn thì studio ghi audit rác và đổi hình dạng event mà không có gì trong suite studio đỏ. Đã thêm
  `Studio-creators/tests/test_runner_core.py` chốt đúng ba hành vi ấy; đo lại thì cả hai đột biến làm studio đỏ.
  Nghiệm thu ràng buộc prompt: `evals all --replay` **0 FAIL** cả hai công ty. **Không sửa một dòng test nào**
  của hai công ty (1057 + 560 xanh).

- refactor(core): **K3.6d1 — khung runner lên `xagents_core`; K3.6d tách đôi vì BẢN GHI EVAL** (#194).
  **Ràng buộc thật của K3.6d không phải độ lệch mã, mà là bản ghi eval.** Khoá bản ghi là
  `hash(system_prompt, user_message)`, và `user_message` do `build_user_message` trong `runner.py` sinh ra.
  Đo trực tiếp: thêm **một dấu cách** vào chuỗi cuối của `build_user_message` studio rồi chạy
  `python -m studio.evals all --replay` → mọi ca chuyển thành *"bản ghi eval lệch prompt hiện tại"*. Nghĩa là
  hợp nhất bất kỳ **chữ** nào trong prompt (`build_user_message` 0.74, `context_writes_schema` 0.69,
  `tools_prompt`) đòi chạy lại `make eval-record` bằng **model thật** cho cả 20 agent theo 7 bước
  `CONTRIBUTING.md` §3 — cần API key. Đó là việc của một PR khác, có người và có key.
  Nên bước này giữ **mọi chuỗi prompt nguyên vẹn từng byte ở từng công ty** và chỉ đưa lên core thứ chứng minh
  được là không đụng prompt: `RunnerError`, `RunResult`, `Generated` (ba lớp kết quả) + `payload_schema`,
  `output_schema`. Nghiệm thu của chính ràng buộc ấy: `evals all --replay` **cả hai công ty, 0 FAIL**.
  **`context_writes_schema` ở lại từng công ty** dù `difflib` 0.69 trông như gộp được: company bắt buộc trường
  `content` (toàn văn artifact, ADR-0012), studio không. Cho studio bản company là đổi hợp đồng đầu ra của 14
  agent, tức đổi prompt. `output_schema` vì thế **nhận** schema ấy làm tham số thay vì tự dựng — đo hai chiều:
  bỏ tham số cho core tự dựng → core 2 ca đỏ **và** `test_context_writes_carry_full_content_and_flag_missing`
  (ADR-0012) của company đỏ.
  **Một cái bẫy đọc số, ghi lại để lần sau khỏi mắc**: `output_schema` `difflib` **0.21** nhưng hai bản
  **giống hệt nhau về logic** — lệch chỉ vì company có docstring còn studio không. Đo theo symbol vẫn phải đọc
  bằng mắt; K3.6c đã dạy "đừng tin difflib trên cả file", bước này thêm "đừng tin nó trên một symbol".
  `Generated` lên core với **bảy trường chung**; năm trường của company (`output_tokens`, `cost_usd`, `priced`,
  `duration_ms`, `phase`) ở lớp con — đưa `phase` (ADR-0037) lên core là bắt studio mang trường nó không bao
  giờ ghi (bài học `AuditLog` K3.5a). Studio `Generated` không thêm trường nào: nó trùng đúng phần chung.
  **Không sửa một dòng test nào** của hai công ty (1057 + 557 xanh). **K3.6d2 (`AgentRunner`) chưa làm**:
  `difflib` 0.14 trên 411 dòng company / 202 studio, `_tool_loop`+`_turns` 0.12, `write_context` 0.15.

- docs: **làm rõ `QUY-TRINH-GIT.md` §2c — code + commit tại chỗ trong khi chờ PR khác merge** (#193). Luật
  "chỉ một PR mở tại một thời điểm" chỉ khoá bước `gh pr create`/merge, không khoá code hay commit — ghi rõ
  thành câu chữ tường minh thay vì để ngầm hiểu, kèm quy trình cụ thể (nhánh/worktree riêng, commit tại chỗ,
  chỉ giữ lại push cho tới khi PR trước merge và đã rebase).
- refactor(core): **K3.6c — `evals` lên `xagents_core`; cổng CI của mỗi công ty giữ nguyên** (#191). `difflib`
  trên cả file **0.556** — cao nhất trong bốn module của K3.6 — nhưng con số gộp ấy giấu mất chuyện đáng kể.
  Đo TỪNG symbol: `prompt_key`/`recording_path`/`load_recording`/`load_cases`/`_get` = **1.00**,
  `outdated_versions` 0.99, `_lines` 0.98, `required_agents` 0.97, `_Probe` 0.91, `check`/`run_eval` 0.84,
  `stale_recordings` 0.83 — nửa trên là **cùng một mã chép hai lần**. Nửa dưới lệch vì **ba lý do khác nhau**,
  và chỉ một trong ba là "một bên đi xa hơn":
  1. **`RecordingClient` (0.29) — hợp nhất HAI CHIỀU.** Company có hai thứ studio không có, cả hai là bài học
     từ sự cố thật 2026-09-05: chốt `prompt_version` lúc `__init__`, và `save()` **gộp** thay vì ghi đè. Studio
     có một thứ company không có: `if not c.tool_calls` — chỉ ghi câu trả lời cuối (ADR-0007). Lấy bản company
     như đặc tả viết là **mất cái thứ ba**; core giữ cả ba. Đặc tả đã lường trước đúng điểm này.
  2. **`_run_case` (0.14) — miền, không phải cơ chế.** Company có `phase` (ADR-0037), studio có `many`+`extra`.
     Không có phần chung đáng gộp; nó ở lại từng công ty như **hook**.
  3. **`main` (0.62) + `CaseResult` (0.52) — CHÍNH SÁCH CỔNG.** Chỗ dễ sai nhất của bước này: hai bên quyết
     định "cái gì làm CI đỏ" **khác nhau** — company tách `gate_ok` (bản ghi) khỏi `cases_ok` (điểm chấm) và
     chỉ đỏ vì điểm khi có `--fail-on-score`; studio đỏ khi **bất kỳ** ca nào không chạy được. Lấy `main` của
     company là **âm thầm nới lỏng cổng của studio**. Nên `main` ở lại từng công ty, và `CaseResult` của core
     mang **hai sự thật có tên** thay vì một cờ: `broken_recording` (hỏng vì bản ghi — cổng của company) và
     `errored` (không chạy được vì bất kỳ lý do gì — cổng của studio). Hai trường, hai chính sách, không bên
     nào mất gì.
  `case_errors` là tuple lớp lỗi do từng công ty khai (`RunnerError`, `LLMError`) chứ **không** phải
  `except Exception` ở core: nuốt cả lỗi lập trình thì một `KeyError` trong `run_case` hiện ra như "model trả
  sai", và eval báo FAIL cho một nguyên nhân nằm ở code. Có ca canh.
  **Không sửa một dòng test nào của hai công ty** (1057 + 543 xanh). Điều đó đòi giữ nguyên bốn **seam** mà 20
  chỗ test đang dùng: `RECORDINGS_DIR`/`EVALS_DIR` (biến module), `load_cases` và `_run_case` (hàm module).
  `EvalSuite` vì thế đọc chúng **qua biến/hàm module** chứ không tính từ `self.root` — tính từ `self.root` là
  seam im lặng hết tác dụng: ca vẫn xanh, nhưng `monkeypatch` không còn tới được nơi nó nhắm, và test ghi đè
  bản ghi thật của repo. Đây là lần thứ ba trong chuỗi K3.6 gặp đúng khuôn ấy (sau `scope_of` ở K3.6b).
  28 ca mới ở `platform/xagents-core/tests/test_evals.py` dựng một `EvalSuite` con trên `tmp_path`. Đo hai chiều: bỏ
  `if not c.tool_calls` và bỏ `errored` → core 3 ca đỏ **và** studio
  `test_replay_exit_code_ignores_grading_but_not_stale_recordings` đỏ; trả lại → xanh.

- refactor(core): **K3.6b — `blackboard` lên `xagents_core`; studio nhận khoá, `rehydrate()`, `content` toàn
  văn** (#189). `difflib` **0.092** trên 114 dòng company vs 30 studio, 9 hàm chỉ company có — nhưng con số thấp
  ấy KHÔNG nói hai blackboard khác bản chất: cả hai làm đúng một việc (nghe `shared-context`, giữ bản có
  `version` lớn nhất, `write` là đọc-version-rồi-publish). Studio chỉ **chưa làm phần còn lại**. Hình dạng lệch
  giống K3.5b, nên cách xử lý cũng giống: core giữ toàn bộ cơ chế, mỗi công ty đưa vào dữ liệu và lớp
  (`cfg.global_namespaces`, `envelope_cls`/`context_cls`, bảng `EXT`).
  **Bước này sửa lại một quyết định của K3.5a, có lý do.** K3.5a xếp `project_id` và `content` chung với
  `rulings` vào "thứ company thêm", vì lúc ấy nó chỉ nhìn *model* `SharedContext`. K3.6b chuyển chính
  `blackboard.py` lên core, và nhìn từ đó thì hai trường ấy **là hai cơ chế của blackboard** — phân vùng
  (ADR-0018) và toàn văn thay vì con trỏ (ADR-0012) — chứ không phải trường của một miền. Một blackboard chung
  không đọc được chúng thì phần lớn thân nó phải đi qua hook, tức cơ chế bị xé làm hai chỗ. `rulings` (ADR-0030)
  ở lại company: đó mới thật là tên gọi của một miền. Ca canh của K3.5a
  (`test_khung_khong_mang_truong_pham_vi_cua_ben_nao`) **không bị nới lỏng** mà đổi thành cấm THEO TỪNG LỚP:
  `project_id` vẫn bị cấm trên `Envelope`/`AuditLog`/`SupervisorAction`, chỉ được phép trên `SharedContext`.
  **Đổi hành vi studio, có chủ ý**: khoá khi đánh version (hai chủ cùng namespace chạy song song không còn mất
  bản ghi), `rehydrate()` dựng lại từ bus khi mở lại SQLite (trước đây mở lại `studio.sqlite` là blackboard
  RỖNG), `content` toàn văn, `all()`/`overview()`, phân vùng theo dự án (chưa dùng — studio không truyền
  `project_id` ở đâu cả). Payload `shared-context` của studio nay mang thêm hai khoá null; schema studio là
  `additionalProperties: true` ở tầng payload nên không có gì đỏ, và hai trường đã khai thẳng vào schema ấy.
  **`scope_of`/`context_key` của company thôi là hàm module, thành phương thức**: chúng đọc `global_namespaces`,
  mà bảng ấy nay ở `CoreConfig` — giữ hàm module là hai nguồn cho một luật. Nơi duy nhất gọi chúng ngoài
  blackboard là một ca test, đã đổi sang vá phương thức.
  **Một ca test tự viết ra đã suýt vô nghĩa**: hai ca "ghi song song không mất bản ghi" (core + studio) ban đầu
  chỉ spawn thread rồi mong có va chạm — đo hai chiều cho thấy **bỏ hẳn khoá chúng vẫn xanh**. Đã viết lại theo
  đúng kỹ thuật company đã dùng: một `Barrier` trong `scope_of` mở cửa sổ tranh chấp một cách xác định. Sau khi
  sửa: bỏ khoá → cả hai đỏ, trả lại → cả hai xanh.

- refactor(core): **K3.6a — `registry` lên `xagents_core`; K3.6 tách làm bốn bước** (#188). Đặc tả gộp
  `registry` + `blackboard` + `runner` + `evals` vào MỘT PR. Đo `difflib` trước khi làm cho thấy bốn module
  lệch rất khác nhau — `evals` **0.556**, `registry` **0.429**, `blackboard` **0.092**, `runner` **0.036**
  (631 dòng company vs 336 studio, 13 hàm chỉ company có) — nên gộp cả bốn là đúng thứ K3.3a và K3.5 đã học
  được là không nên. Bốn bước: **a `registry`** (bước này) → b `blackboard` → c `evals` → d `runner`.
  **Hình dạng lệch của `registry`: một bên là TẬP CON của bên kia.** Ba hàm chỉ company có (`_load_phases`,
  `owned_skills`, `reads_full`) đều là *thêm vào*, không phải *khác đi*; `_split`, `load_skill`,
  `CORE_SECTIONS` và thân `load_agents` của studio giống company gần như từng ký tự. Studio chưa có `phases`
  (ADR-0037), `context_namespace_read` (ADR-0020), kiểm chủ quản skill (ADR-0008) — nó chưa cần, chứ không làm
  khác. Nên core = bản company, studio chỉ khai thêm cái nó có riêng.
  Hai thứ mỗi công ty đưa vào, cả hai là **dữ liệu**: (1) **`spec_cls`** — studio có trường `tools` (ADR-0007
  của studio: `web` cho `fact-checker` và `trend-researcher`) mà core không được biết; `load_agents` dựng đúng
  lớp con nên nó không rơi mất, cùng lý do `envelope_cls` ở bus. (2) **`check_owners`** — mặc định `True` như
  company, **studio truyền `False` và đó là sự thật ĐO ĐƯỢC**: `skills/` của studio hiện có ba skill không agent
  nào nạp đầy đủ (`content-policy`, `cost-estimation`, `finops`), bật cổng là studio đỏ ngay lần nạp đầu. Ba
  skill ấy là nợ có thật của studio; `test_ba_skill_chua_co_agent_chu_quan_la_no_co_that_khong_phai_khau_vi`
  ghi lại đúng danh sách ấy và sẽ đỏ khi nợ được trả — lúc đó việc phải làm là đổi mặc định thành `True`.
  `ROOT`/`AGENTS_DIR`/`SKILLS_DIR` nay suy từ `CORE.root` (`CoreConfig` thêm `agents_dir`, `skills_dir` cạnh
  `schema_dir`). Ba tên cũ `_split`, `_load_phases`, `load_skill(name, core_only)` giữ nguyên chữ ký ở shim nên
  không nơi gọi nào phải đổi. 19 ca mới ở `platform/xagents-core/tests/test_registry.py` dựng một công ty giả trên
  tmp_path — không mượn `agents/` thật của công ty nào, vì ca đọc `agents/` thật sẽ đỏ theo mỗi lần sửa prompt.
  Đo hai chiều: dựng `AgentSpec` core thay vì `spec_cls` → studio 7 ca đỏ (trong đó ca `tools`), trả lại → 8 xanh.

- refactor(studio): **4L-6 — rẽ nhánh trên model đã validate; vá lỗ mạo danh gate** (#190). `_rework`/
  `_publish_video` validate `ReviewResult`/`PublishEvent` trước khi rẽ nhánh; video đã live không gọi lại
  adapter. **Bảo mật**: `trusted_decision` (`gate_cli.py`) trước đây mặc định TIN mọi actor trừ khi actor hình
  người mà lệch `evidence.by` — actor `"orchestrator"` giả `by="human:x"` từng đẩy được video lên nền tảng
  thật. Vá thành allowlist mặc định từ chối, đúng mẫu `company/gate_cli.py`. `PersistentGate.apply`/
  `_rehydrate` cùng lỗ, cùng vá. Phát hiện bởi `sc-security` khi chấm gói.
- docs: **gom hai đặc tả tháng 9 đã bị `DAC-TA-KICH-BAN-B.md` bọc vào `docs/archive/`** (#192) — `DAC-TA-NANG-CAP-2026-09.md`
  và `DANH-GIA-VA-TAM-NHIN-2026-09.md` chuyển sang `docs/archive/`, thêm ghi chú "đã lưu trữ" đầu file, sửa
  các dẫn chiếu còn sống (`DAC-TA-KICH-BAN-B.md`, `KIEN-TRUC-4-LOP.md`, `NGON-NGU.md`,
  `.claude/commands/thi-hanh.md`, `.gitattributes`) trỏ đúng đường dẫn mới. Không đổi nội dung, không đụng
  `DAC-TA-KICH-BAN-B.md`/`DAC-TA-TRIEN-KHAI-KICH-BAN-B.md` (bảng theo dõi đang sống, PR tới #187) — hai file đó
  không trùng lặp nội dung với nhau nên giữ nguyên chỗ, đúng bài học `KHUON-THI-HANH.md` §6 "một file thay ba".
- refactor(core): **K3.5c — `sqlite_bus` lên `xagents_core`; studio nhận khoá, `latest()` và bus dùng được từ
  thread khác** (#187). `difflib` giữa hai `sqlite_bus.py` là **0.442** — cao nhất trong ba module của K3.5, và
  lần này con số ấy đúng theo nghĩa đen: cùng `_DDL`, cùng cách nạp lại `_log` khi mở, cùng câu `INSERT`, cùng
  `replay` ghép `WHERE`. Chỗ lệch là **company đã đi xa hơn trên cùng con đường** (6 hàm chỉ company có:
  `latest`, `_persist_only`, `__del__`, `Lease.acquire/release`, `_alive`), nên đây là bước duy nhất của K3.5
  thật sự "lấy bản company" như đặc tả hình dung.
  **Ba quyết định hợp nhất**, ghi ở docstring `platform/xagents-core/src/xagents_core/sqlite_bus.py`: (1) **khoá** —
  bản studio ghi đĩa không khoá và tháo `_subs` ra để ép "ghi trước, báo sau"; core làm cùng việc ấy trong một
  `RLock` nên mẹo tháo bảng biến mất; (2) **`check_same_thread=False`** — bản studio thiếu cờ này, một
  `SQLiteBus` truyền sang thread khác là `ProgrammingError`, nó mới chưa nổ vì runner studio chạy một thread;
  (3) **`BUSY_TIMEOUT_S` là hằng chung** — company viết thẳng `timeout=30` trong lời gọi, studio đặt tên và
  giải thích; lấy cái có tên. Đây là chỗ DUY NHẤT bản studio thắng.
  **Đổi hành vi studio, có chủ ý**: thêm khoá, `latest()` tìm trên index `(topic, key)` thay vì quét log,
  `_persist_only` ghi đĩa, `__del__` đóng kết nối, và lỗi subscriber nay thành một `audit-log`
  `subscriber_error` thay vì làm rơi các subscriber sau. Bốn ca ở `Studio-creators/tests/test_sqlite_bus_core.py`
  đo đúng bốn thứ ấy tới được studio.
  `"company.sqlite"` viết cứng ở `sqlite_bus.py:26` nay đọc từ `CORE.db_name`. `Lease`/`LeaseError`/`_alive`
  lên core cùng mã chúng phục vụ; 4 ca của `test_coverage_100.py` chuyển theo sang
  `platform/xagents-core/tests/test_sqlite_bus.py`, và công ty giả dùng chung của core tách ra `tests/conftest.py`
  (hai module test nay dùng nó). **Một điểm khác lời đặc tả**: thứ tự tham số của `InMemoryBus.__init__` ở cả
  hai công ty đổi thành `(cfg, enforce_owners)` theo core — `SQLiteBus` kế thừa CẢ hai lớp, nên
  `super().__init__(cfg, ...)` của core đi qua lớp công ty theo MRO; giữ thứ tự cũ là `cfg` rơi vào
  `enforce_owners` im lặng. Không nơi gọi nào truyền vị trí (đã grep). Ca
  `test_sqlite_bus_van_giu_luat_rieng_gate_decide_cua_company` canh chính MRO ấy: ghép sai thứ tự hai lớp cha
  là mất `_extra_publish_checks` mà không có gì đỏ.
  Nghiệm thu: `make demo` hai công ty xanh; company 1057 ca / studio 542 / core 259 / console 237 / gateway 251,
  coverage 100% cả năm package. Đo hai chiều: bỏ `check_same_thread=False` → `test_bus_dung_duoc_tu_thread_khac`
  đỏ, bật lại → xanh.

- docs: **4l — đợt 3-5 chờ K3.5c/K3.6 merge, kết phiên thi hành** (#186). `/thi-hanh 4l` đợt 1-2 xong (#181-#185);
  4L-1b chờ người (key model thật); 4L-4/6/7 chờ K3.5c/K3.6 (kịch bản B, ngoài phạm vi mã 4l). `make test` gốc
  xanh cả năm package. Chỉ tài liệu.
- feat(company): **4L-5 — metrics vòng tool và tỉ lệ chạm trần** (#185). `metrics.collect()["loops"]`
  (turns_p50/p90/max, capped_ratio, no_progress_ratio, retry_max_ratio, empty) + 6 gauge `company_loop_*`;
  console ô "Vòng tool (trung vị)" mới, RỖNG → XÁM chứ không xanh giả (ADR-0003).
- feat(company): **4L-3 — cắt vòng tool khi không tiến bộ** (#184). `_stagnant()` đếm lời gọi tool liên tiếp
  cùng `(name, args_hash, out_hash)` (4L-2); lặp 3 lần cảnh báo, 5 lần cắt (audit `no_progress`), không ném
  exception — đi vào đúng nhánh ép chốt JSON có sẵn cho case hết lượt. Chỉ tool ghi thành công mới reset đếm.
  Đo được: giảm 77% token trên vòng lặp đứng yên hoàn toàn (26→6 lượt).
- feat(core): **4L-2 — vết từng lời gọi tool vào audit, trace in được** (#183). `ToolBox.trace()` (args_hash/
  out_hash/ms, `content` chỉ ghi độ dài); audit `tools_trace` mỗi lượt tool ở company + studio, song song
  `tools_used` cũ. `company.trace` in dòng `↳`, gộp `×N` khi ≥3 call liên tiếp cùng hash. Mode `cli` không có vết
  → nói rõ, không im lặng.
- feat(company): **4L-1a — ngưỡng eval theo agent, CI chặn tụt điểm** (#182). `evals/thresholds.yaml` (6 agent,
  đo 100% hôm 2026-09-08 làm tròn xuống 0.05); `Threshold`/`load_thresholds`/`check_thresholds` trong `evals.py`;
  cờ `--thresholds`/`--no-thresholds`. Trước đây CI chỉ đỏ khi bản ghi eval thiếu/lệch phiên bản prompt, không
  đỏ khi ĐIỂM CHẤM tụt — nay bản ghi mới làm điểm rớt dưới sàn thì CI đỏ. `Makefile` `eval-thresholds`.

- docs: **4L-8 — ranh giới tin cậy nói rõ vì sao không chốt mức tool; bảng K3 cập nhật** (#181).
  `ARCHITECTURE.md` thêm `xagents-core` vào sơ đồ Năm package + đoạn giải thích lựa chọn "không chốt duyệt mức
  tool". `docs/DAC-TA-KICH-BAN-B.md` bảng K3: K3.3c2–d/K3.4/K3.5a/K3.5b = xong (#173-#179). Chỉ tài liệu.
- docs: **đối chiếu bốn lớp LLM (Prompt/Agent/Loop/Graph) với repo, khuôn thi hành một lệnh và `/thi-hanh`** (#180).
  `docs/KIEN-TRUC-4-LOP.md`: company đạt 6/9 mục checklist đặc tả, studio 3/9; tám việc `4L-1…4L-8` (cổng eval
  chấm điểm, vết từng tool call, cắt vòng tool khi không tiến bộ, tỉa hội thoại — ADR-0040 dự kiến ở K3.6, đo
  vòng, studio validate trước rẽ nhánh, trace studio, tài liệu) gắn mức C1/C2/C3 → Haiku/Sonnet/Opus. Cố ý
  **không** thêm chốt duyệt mức tool (đã có "không cấp tool + gate công đoạn"). `docs/KHUON-THI-HANH.md` +
  `.claude/commands/thi-hanh.md`: sáu giai đoạn vào một file `docs/thi-hanh/<mã>.md`, người ra lệnh một lần,
  song song phát triển nhưng PR tuần tự, idempotent qua file. Chỉ tài liệu.
- refactor(core): **K3.5b — `bus` lên `xagents_core`; studio lần đầu có ACL topic, bảng ACL ĐO chứ không suy**. (#179)
  `difflib` giữa hai `bus.py` là **0.06**, nhưng con số ấy không nói "hai bus khác bản chất" — nó nói bus studio
  61 dòng **chưa làm phần lớn việc** mà bus company 206 dòng đã làm (không validate envelope, không ACL topic,
  không `latest`, không khoá, không `_notify_safely`). Lệch vì MỘT BÊN THIẾU, khác hẳn K3.5a nơi lệch vì mỗi
  miền có trường riêng. Nên core giữ **toàn bộ cơ chế**, thứ mỗi công ty đưa vào là **dữ liệu** (`CoreConfig`):
  `topic_acl`, `payload_models`, `namespace_owners` — ba trường khai sẵn từ K3.1 nay mới điền.
  **Bảng ACL của studio đo từ event thật, không đọc từ front matter `writes`.** Bọc `publish`, chạy cả suite,
  ghi `(actor, topic)` kèm khung ngăn xếp: **76 cặp**, 40 cặp ngoài `open_topics` — **26 cặp production**
  (thành bảng) và **14 cặp chỉ có trong `tests/`**. Nguồn hiển nhiên là nguồn sai: quá nửa event studio do CODE
  phát, và `writes` không biết `renderer`, `desk`, `orchestrator`, `adapter:youtube`, `chapters` — viết ACL từ
  `writes` là chặn cả năm ngay lần chạy đầu. 14 cặp test-only **sửa tên actor trong fixture** (4 file, ~12 dòng),
  không mở lối cho chúng: mở lối là chọc thủng đúng lớp vừa thêm vào — và nay chính test cấm mở
  (`test_producer_agent_la_tap_con_cua_front_matter_writes` đỏ nếu ai thêm một actor không phải agent, không
  phải code).
  **Việc bật validate envelope làm lộ một thứ K3.5a để lại**: 19 schema `topics/` của studio có
  `additionalProperties: false` mà chưa biết ba trường `schema_version`/`correlation_id`/`causation_id` K3.5a
  thêm vào — studio khi ấy không validate envelope nên không ai thấy. 143 ca đỏ cùng lúc, sửa bằng một lượt vá
  19 schema, và nay có một ca nói thẳng điều đó thay vì 143 ca đỏ khó đọc.
  **Company không sửa một dòng test nào** (1027 xanh). Console sửa **1 dòng**: câu lỗi thiếu trường của studio
  nay là câu của `jsonschema` giống company, không còn là vòng lặp `required` tự viết — đặc tả đoán "console 0
  dòng", chỗ lệch đã ghi. Đo hai chiều 8 đột biến.

- refactor(core): **K3.5a — khung event lên `xagents_core`; K3.5 tách làm ba bước**. Đặc tả gộp `events` + `bus`
  + `sqlite_bus` vào một PR và tự gắn nhãn "rủi ro cao nhất". Đo `difflib` trước khi làm cho thấy ba module lệch
  rất khác nhau — `sqlite_bus` **0.44**, `events` **0.14**, `bus` **0.06**. Ở mức 0.06 hai file gần như không có
  gì chung; gộp cả ba là đúng thứ K3.3a đã học được là không nên, nên K3.5 tách: **a = `events`** (PR này),
  b = `bus`, c = `sqlite_bus`.
  **Chúng lên core dưới dạng LỚP CƠ SỞ, không phải lớp dùng thẳng** (tiền lệ `LLMConfig` ở K3.3b) — đây là điểm
  đặc tả không nói tới, và nó quyết định cả hình dạng bước này. Đo từng symbol: `Envelope` 0.43,
  `SharedContext` 0.45, `AuditLog` 0.38, `SupervisorAction` 0.62, `can_transition` **1.00**. Chỗ lệch không phải
  "một bên thiếu" mà là **trường phạm vi của từng miền**: `AuditLog` của company có `ticket_id`/`project_id`,
  của studio có `video_id`/`channel_id`. Đưa cả bốn lên core là bắt company mang một trường `video_id` nó không
  bao giờ ghi — đúng thứ nguyên tắc 1 cấm. Nên core giữ phần chung, mỗi công ty kế thừa và thêm trường của mình.
  Cùng lý do, `topic`/`namespace` ở core là `str`: `Topic` là danh sách topic CỦA MỘT công ty. Lớp con thu hẹp
  về Literal của mình nên **kiểm tra topic không mất** — publish một topic lạ vẫn đỏ, chỉ là việc ấy chuyển
  xuống nơi biết đủ để làm. `child()` dùng `type(self)` chứ không viết cứng tên lớp: lớp con phải sinh ra lớp
  con, nếu không mỗi event con lại tụt về lớp core và mất đúng cái kiểm tra vừa được thêm vào.
  **Hai chỗ phải quyết ngoài lời đặc tả.** (1) `can_transition` **không** chỉ là `dst in transitions[src]`: cả
  hai công ty có cửa thoát `dst in {"blocked", "escalated"}` — một ticket/video ở bất kỳ đâu cũng phải chặn hoặc
  escalate được. Quên vế này làm **12 ca của company đỏ** với `không thể changes_requested → blocked`; đó là
  cách nó được phát hiện. Nay nó là tham số `always=` chứ không viết cứng tên trạng thái của một công ty vào
  core. (2) Fixture `studio-0.1.0.sqlite` mà đặc tả đòi **không** commit dưới dạng nhị phân: `AGENTS.md` luật 3
  cấm `*.sqlite*` và `.gitignore` chặn thật. "Định dạng cũ" được dựng bằng SQL + JSON ngay trong test — không có
  blob trong git, và hình dạng cũ đọc được bằng mắt thay vì phải mở bằng công cụ.
  **Ca đắt nhất của bước này là ca tương thích ngược**, vì đây là bước đầu tiên của cả K3 đổi hình dạng của thứ
  ĐÃ nằm trên đĩa: `test_bus_cu_van_mo_duoc` dựng một bus đúng định dạng trước K3.5a rồi mở bằng mã mới —
  replay đủ event, ba trường mới nhận default, `correlation_id` lùi về chính `event_id`. Kèm
  `test_bus_cu_ghi_tiep_duoc_bang_ban_moi`: mở file cũ rồi ghi tiếp, chuỗi nhân quả nối từ event cũ sang event
  mới — đó là hình dạng thật khi nâng cấp một máy đang chạy, không ai xoá bus rồi bắt đầu lại.
  Đo hai chiều **4 đột biến**, mỗi cái đỏ ở **cả hai** suite (core và studio): `child()` viết cứng `Envelope`;
  bỏ cửa thoát `blocked`/`escalated`; bỏ `model_post_init`; và cho core mang luôn `video_id`/`channel_id` của
  studio (rò nghĩa lên core). Đã chạy: core 216 test / phủ 100%; studio 508 + 5 skip / phủ 100%; company 1027 /
  phủ 100% — **company không sửa một ca test nào**, subclassing giữ nguyên hành vi; console 233 và gateway 251
  cũng không sửa dòng nào (#178)

- refactor(core): **K3.4 — `guard.py` lên `xagents_core`; hợp nhất HAI CHIỀU chứ không phải chuyển mã**. Đặc tả
  viết K3.4 trong ba gạch đầu dòng ("chuyển `guard.py`, xoá `studio/runner.py:29-81`"), nhưng studio **không có**
  `guard.py` — nó có một bộ mẫu *khác* nằm lẫn trong `runner.py`. Đo chéo 23 câu thử trước khi gõ phím cho thấy
  **mỗi bên đều có lỗ**: company trượt 4 mẫu studio bắt được, studio trượt 8 mẫu company bắt được. Nên "lấy bản
  company" là làm mất bốn thứ ở cả hai bên — khác hẳn K3.3, nơi company đúng là tập cha.
  **Ba quyết định hợp nhất, mỗi cái có số đo, không có cái nào là gộp mù**: (1) `<|im_end|>` từ bảng studio vào
  bảng CHUNG — ký hiệu khung hội thoại, không bên nào dùng hợp lệ. (2) `developer mode`/`jailbreak` **KHÔNG** vào
  bảng chung mà thành mẫu RIÊNG của studio (`CoreConfig.extra_injection_patterns`): với phòng làm video đó là câu
  tấn công, với công ty gia công PHẦN MỀM đó là từ vựng nghiệp vụ — bằng chứng đo được chứ không phải lo xa,
  `companies/software-company/skills/mobile.md` dùng "jailbreak" hợp lệ cho yêu cầu bảo mật app di động, nên thêm mẫu ấy là
  làm một ticket bảo mật mobile `injection_detected` và không chạy được. (3) Mẫu tiếng Việt **viết lại, tốt hơn cả
  hai bản cũ**: bản company đòi bắt buộc một từ bổ nghĩa đứng sau nên trượt "bỏ qua mọi hướng dẫn"; bản studio
  không đòi gì nên báo nhầm 3/3 câu hoàn toàn bình thường ("tôi quên hướng dẫn cài đặt rồi"). Bản mới đòi HOẶC từ
  chỉ lượng HOẶC từ bổ nghĩa sau: 5/5 câu lành sạch, 6/6 câu tấn công bắt được, gồm hai câu mà *cả hai* bản cũ đều
  trượt (`bỏ qua mọi hướng dẫn`, `gạt bỏ tất cả các chỉ thị`).
  **Studio được nâng ba điểm**, đáng kể nhất là **một lỗ hổng thật**: bản cũ không chuẩn hoá ký tự vô hình, nên
  `igno\u200bre previous instructions` đi thẳng qua bộ lọc. Cộng bảng mẫu rộng hơn 8 mẫu và hết báo nhầm tiếng
  Việt. `sanitize_*` nay trả **danh sách tên mẫu** thay vì một con số — audit `injection_sanitized` của studio
  trước chỉ ghi "3 đoạn", người trực đọc log không biết chuyện gì đã xảy ra.
  **Cơ chế ở core, nghĩa ở package** (nguyên tắc 2): `CoreConfig` nhận hai trường mới ngoài hai trường K3.0 đã
  đặt trước — `untrusted_fields` (tên trường là của từng công ty vì topic hai bên khác nhau) và
  `extra_injection_patterns`. Luật bỏ TỪNG bình luận của lô `audience-comments` ở lại `studio.runner` vì company
  không có gì tương đương. Hai shim là shim **ràng buộc** (`functools.partial(..., core=CORE)`) chứ không
  `import *`, nên `test_shim_core.py` có nhóm thứ ba với ca riêng: cùng tên, cùng hành vi, KHÔNG cùng đối tượng.
  **Một lỗ hổng test có sẵn bị lộ ra và đã vá**: xoá sạch `untrusted_fields` khỏi `company/core.py` mà **không ca
  nào của company đỏ** — vì ca duy nhất chạm `diff` dùng topic `pull-requests`, một topic *dẫn xuất*, nên nó đi
  nhánh khác với nhánh nó tưởng đang đo. Một PR sau có thể làm rỗng danh sách ấy trong im lặng và mọi ticket có
  `diff` trích comment độc trong repo khách sẽ chết đứng. Nay có ca dùng `tasks` (nội bộ THUẦN, chỉ một đường đi);
  bài học vào `TRAPS.md` của company.
  Đo hai chiều **7 đột biến**, mỗi cái đỏ đúng ca đo nó — trong đó hai đột biến lùi mẫu tiếng Việt về *từng* bản
  cũ: lùi về company → 4 ca đỏ (trượt câu tấn công), lùi về studio → 5 ca đỏ (báo nhầm câu lành). Đã chạy: core
  204 test / phủ 100%; studio 501 + 5 skip / phủ 100%; company 1027 / phủ 100%; console 233 và gateway 251 (không
  sửa dòng nào). `assetscan` đọc `guard.COMPILED` công khai thay cho tên riêng tư `guard._COMPILED`.
  **`studio.runner` nay theo chính sách NGUỒN thay vì "khớp mẫu ở đâu cũng từ chối"** — bản cũ từ chối MỌI topic,
  nghĩa là một người viết `channel-briefs`, hay một trang web bị trích vào `trend-reports`, chỉ cần một câu là
  tắt được một bước của phòng ban, và event ấy bị từ chối MÃI vì payload không bao giờ tự đổi. Nửa `extra`
  (dữ liệu `enrich` do route tự dựng) **giữ luật cũ** có chủ ý: nó không mang topic/actor riêng nên không phân
  loại được nguồn, nới chỗ đó cần biết từng `enrich` lấy dữ liệu ở đâu — ngoài phạm vi K3.4.
  **Lỗ hổng test thứ hai, cùng khuôn với lỗ đầu**: ca gọi thẳng `guard_payload` chốt *hàm* đúng nhưng không chốt
  *runner có gọi hàm ấy* — thay `guard_payload` trong runner bằng luật cũ mà không ca nào đỏ. Nay có hai ca đi
  qua `AgentRunner` thật (#177)

- refactor(core): **K3.3d — `routing.py` lên `xagents_core`, và studio HOÃN lỗi vận chuyển thay vì tính lỗi
  agent**. Bước cuối của K3.3; **K5 nay mở khoá**. `routing.py` là module dễ nhất của cả chuỗi — nó không đọc
  `llm.yaml`, không biết tiền tố env, không chạm đĩa, nên khác `llm.py` ở chỗ shim là `import *` thuần chứ không
  phải hàm bọc `CORE`. Bản vào core là bản company (`difflib` 0.62); studio được nâng **bốn điểm**, mỗi điểm có
  một ca canh riêng ở `platform/xagents-core/tests/test_routing.py`: (1) phân loại theo `LLMError.status` trước, regex chỉ
  còn là đường lùi cho CLI/gateway không mã; (2) `QUOTA_PATTERNS` có **ranh giới từ** — bản studio khớp
  `insufficient` và `429` trần nên "gói unlimited", "billingham@…", mã nội bộ 4290 đều đọc ra "hết quota" và cho
  một backend còn tốt đi nghỉ nguyên tiếng, đây là **bug thật** chứ không phải khác biệt phong cách;
  (3) `is_auth_error` (401/403) — studio không có, nên khoá sai đọc ra "lỗi nội dung" và ném thẳng cho agent thay
  vì cho backend hỏng nghỉ ra một bên; (4) mọi backend đều nghỉ nay ném `TransientError` chứ không `LLMError`
  trần. `TRANSIENT_PATTERNS`/`is_transient_error` của studio **bị xoá**, không re-export: đoán "lỗi tạm thời"
  bằng regex trên thông điệp là đúng việc `TransientError` sinh ra để thay — adapter biết chắc lỗi của mình là
  loại gì, người đọc chuỗi thì không.
  **Phần đắt nhất không nằm ở chỗ chuyển mã mà ở `studio/orchestrator.py`.** Trước bước này studio chỉ có
  `except (RunnerError, LLMError)`: một nhịp mạng chập, một backend hết quota, một CLI timeout đều đọc ra "agent
  trả lời sai" → ghi `agent_failed`, desk đếm một lần hỏng (đủ số lần thì video `blocked`, cần người gỡ), và
  `_done` đóng dấu `orchestrated` nên **việc chưa bao giờ được làm lại**. Nay `TransientError` được bắt riêng và
  event bị HOÃN, nhịp `tick` sau thử lại, tôn trọng hẹn "thử lại sau Ns" của backend (`defer_until` + audit
  `defer.until`; hỏi lại mỗi nhịp trong lúc pool cạn là thứ company đo được 60 bản ghi lỗi/phút hồi 2026-09-04).
  **Ba chỗ gọi model chứ không một**: đặc tả K3.3 chỉ nói `_call`, nhưng `_plan` (channel-strategist) và
  `_decide` (publisher, ADR-0008) là hai bản sao của cùng một bước — vá một chỗ là để lại hai chỗ y hệt
  (TRAPS.md §1 khuôn 3). **Và một chỗ thứ tư mà không đặc tả nào nhắc**: `_decide` chạy trong nhánh `audit-log`
  của `process()`, nhánh có `return` sớm riêng — nếu chỉ vá cuối hàm thì một lỗi vận chuyển ở đây làm **mất luôn
  lần đăng đã được người ký gate**, im lặng, tệ hơn cả trước khi vá (trước ít ra còn `agent_failed` trong log).
  Chạy lại an toàn nhờ hai cơ chế có sẵn: nhánh `PUB-` giữ nguyên trạng thái khi video đã `approved`, và
  `_publish_video` dùng lại upload trước qua `_prior_upload`.
  Đo hai chiều **7 đột biến**, mỗi cái đỏ đúng ca đo nó: bỏ nhánh hoãn cuối `process()` → 4 ca đỏ; bỏ nhánh hoãn
  trong `audit-log` → đúng ca `_decide` đỏ; bỏ `_retry_deferred(only="transient:")` khỏi `tick` → 4 ca đỏ; bỏ
  `wait_s` → ca hẹn giờ đỏ; ở core: ném `LLMError` thay `TransientError`, bỏ ranh giới từ, bỏ `is_auth_error` →
  mỗi cái đỏ đúng ca điểm nâng của nó. Ca đối chứng `test_loi_noi_dung_van_la_loi_agent` canh chiều ngược lại:
  `LLMError` trần vẫn phải là lỗi agent, bản vá không được nuốt cả lỗi thật. Đã chạy: core 162 test / phủ 100%;
  studio 477 + 5 skip / phủ 100%; company 1023; console 233 (không sửa một dòng — shim giữ nguyên bề mặt
  `company.routing`/`studio.routing`, `platform/console/collect.py` nhập qua đó). `routing` thêm vào `SHIM` của
  `test_shim_core.py` hai bên (#176)

- refactor(core): K3.3c3 **bước 2** — `ClaudeCodeClient` lên `xagents_core.llm` dưới dạng **lớp cơ sở chỉ có
  transport**, kèm `cli_exit_error`. Đây là bước cuối của K3.3c, và điều đáng ghi nhất là **nó KHÔNG hợp nhất cả
  lớp — có chủ đích**. Đo từng method: `_parse` 0.82 (28 dòng trùng nguyên văn), `_subprocess` 0.64, `__init__`
  khác đúng một dòng cuối → lên core; `complete` **0.20** → ở lại mỗi công ty. `complete` lệch vì ba chiến lược
  tool khác nhau THẬT, không phải một bên chậm tiến: studio uỷ quyền web tool của CLI (ADR-0007), company
  `cli_tools` uỷ quyền file/bash tool trong worktree khách (ADR-0023), company `mcp_tools` đưa đúng bảng tool của
  công ty vào CLI qua cầu MCP (ADR-0024). Gộp ba cái đó cần **năm móc** để GIẤU một khác biệt có thật — đúng thứ
  `xagents_core/tools.py` đã từ chối làm cho `tools_prompt` (*"gộp lại là thêm một tham số mà một bên không bao
  giờ dùng"*). Nên core giữ transport, chính sách tool ở lại nơi nó thuộc về; cầu MCP (255 dòng `mcp_bridge.py`)
  **không** lên core.
  **Hợp nhất hai chiều, không bên nào là gốc** — như `reported_model` ở K3.3a. Company nâng studio:
  `TransientError` khi timeout và khi `is_error` nhắc quota; `cli_exit_error` đọc JSON thay vì soi 500 ký tự cuối;
  `cache_write_tokens`; `tool_mode`; tham số `cwd`. **Studio nâng company**: bắt `OSError` ("argv quá dài, không
  có quyền chạy, pipe vỡ") — company KHÔNG bắt, nên một `OSError` thoát ra ngoài dưới dạng exception thô mà
  không lớp nào phân loại được.
  **Một đính chính quan trọng**: phiên này ban đầu tin rằng studio có bug ở nhánh không-tool (`--max-turns 1`
  cộng `--json-schema`), dựa trên ghi chú đo được của company ngày 2026-09-05. **Đo lại thật trên CLI 2.1.263
  thì không tái hiện**: cả prompt tầm thường lẫn schema nặng (6 mục lồng, hai mảng bắt buộc) đều `subtype:
  success`, `num_turns: 2` với cap 1 và `3` với cap 6. Trần là giới hạn TRÊN, không phải lượt bị tiêu. Bài học
  mới: **số đo trong comment có hạn dùng** — nó nói về một công cụ NGOÀI repo, công cụ đổi thì số đo hết đúng,
  nhưng comment không tự hết hạn; ai dựa vào nó để kết luận thì phải đo lại trước.
  **Bằng chứng**: eval replay hai công ty, PASS/FAIL giống hệt từng dòng (50 + 28 ca). Đo hai chiều 8 đột biến —
  và **hai trong số đó SỐNG SÓT ở lần đo đầu**: "bỏ ưu tiên `structured_output`" (vì ca cũ để `result` và
  `structured_output` cho ra cùng chuỗi, nên xanh dù đọc nhầm cái nào) và "đọc `subtype` sau `result`" (vì
  `match=<tên subtype>` khớp cả thông điệp dự phòng). Đã siết hai ca ấy rồi đo lại: 8/8 bị bắt. Không sửa MỘT
  DÒNG test nào của hai công ty — 1023 và 471 xanh nguyên.
  Số đo từ đĩa: `company/llm.py` 552→471, `studio/llm.py` 235→186, dòng trùng khối ≥ 8 giữa hai bên **62→42**
  (từ đầu phiên: 194→42). Đã chạy: core 147 test / 100%; company 1023 / 100%; studio 471 + 5 skip / 100%;
  gateway 251, console 233 (#175)

- refactor(core): K3.3c3 **bước 1** — `OpenAICompatClient` lên `xagents_core.llm`. difflib 0.73 sau c2: company
  là **tập cha** của studio — cùng hình dạng, cùng thứ tự, hơn đúng một method và 46 dòng. Tách khỏi
  `ClaudeCodeClient` (0.39) theo đúng ghi chú của phiên K3.3c1: *"mỗi cái một quyết định hợp nhất riêng, đừng gộp
  một PR"*. Năm điểm studio đang thiếu, mỗi cái là một lớp bảo vệ chứ không phải tính năng:
  **(1) `_rejects` — bug THẬT của studio, không chỉ là thiếu sót.** Bản studio tắt `json_schema` /
  `prompt_cache_key` khi gặp BẤT KỲ HTTP 400 nào; một 400 vì prompt quá dài do đó tắt vĩnh viễn structured
  output cho cả tiến trình, và tắt **im lặng** vì lượt sau vẫn "chạy được", chỉ là chạy ở chế độ kém hơn. Bản
  company đòi thân lỗi phải NHẮC TỚI đúng tính năng đang dò. Test studio cũ mã hoá đúng con bug ấy (giả lập 400
  với thân *"schema khong duoc ho tro"* — không chứa tên tính năng nào) nên nó ĐỎ khi hợp nhất; đã sửa và nói
  rõ vì sao. (2) lỗi mạng + mã HTTP tạm thời → `TransientError` thay vì `LLMError`, kèm bắt `TimeoutError` —
  thứ `URLError` không phủ. (3) `finish_reason == "length"` nhận diện riêng: trước đó lượt này lọt xuống dưới
  với `text` cụt rồi runner báo "đầu ra không phải JSON", dẫn người đọc đi sửa prompt trong khi việc cần làm là
  tăng `max_tokens`; model *thinking* đặc biệt dễ dính vì token suy nghĩ tính vào cùng hạn mức. (4) thân RỖNG
  với HTTP 200 nhận diện riêng — khuôn 1 của `TRAPS.md` §1 đúng nguyên văn, nguyên nhân thật là server trả JSON
  qua `tool_calls` thay vì `message.content`. (5) `cached_tokens` chỉ để báo cáo, KHÔNG cộng thêm — ngược với
  Anthropic, `prompt_tokens` của OpenAI đã gồm phần cache; cộng lần nữa là thổi phồng token trong audit.
  **Bằng chứng**: `evals … --replay [--strict]` trên bản trước và bản sau, hai công ty, PASS/FAIL **giống hệt
  từng dòng** (50 + 28 ca). Đo hai chiều 7 đột biến, **7/7 bị bắt** — trong đó một đột biến cố ý hẹp: "nhánh
  thân rỗng quên loại trừ `tool_calls`", vì bỏ vế `not calls` là mọi vòng tool của company chết ngay mà đọc diff
  không thấy. mypy `strict` của core bắt thêm một `Any` ngầm ở `json.loads` mà mypy lỏng của company bỏ qua.
  Số đo từ đĩa: `company/llm.py` 698→552, `studio/llm.py` 335→235, dòng trùng khối ≥ 8 giữa hai bên **128→62**.
  Đã chạy: core 140 test / 100%; company 1023 / 100%; studio 471 + 5 skip / 100%; gateway 251, console 233,
  không sửa một dòng (#174)

- refactor(core): K3.3c2 kịch bản B — `AnthropicClient`, `CodexClient`, `FakeClient` lên `xagents_core.llm`,
  kèm `ModelClient`, `cli_env`, `check_argv`, `anthropic_input_tokens`. Đây là bước "rẻ" mà K3.3c1 đã đặt tên và
  đo trước: ba adapter này trùng 0.81 / 0.82 / 0.88 (`difflib` từng symbol, đo lại sau c1), khác hẳn hai cái còn
  lại. **Mọi điểm lệch đều là studio đang MẤT thứ gì đó**, nên hợp nhất = studio được nâng, không phải "company
  là gốc": (1) `timeout=600` cho SDK Anthropic — studio không đặt, nên một request treo giữ luôn cả orchestrator
  (vòng lặp tuần tự, một tiến trình); (2) lỗi mạng / 5xx / timeout / 429 ném `TransientError` thay vì `LLMError`
  — `LLMError` là lỗi NỘI DUNG, orchestrator dừng thay vì hoãn, nên một nhịp mạng chập làm hỏng cả lượt; (3)
  `cache_write_tokens` — Anthropic để token GHI vào cache ngoài `input_tokens`, studio bỏ trường này nên
  `audit-log.tokens` thiếu đúng phần đắt nhất của lượt đầu và trần ngân sách không bao giờ chạm; (4) prompt của
  codex đi qua **stdin** thay vì argv, kèm `check_argv` — prompt dài trên argv làm hệ điều hành thoát với
  `Argument list too long`, thông điệp không nhắc gì tới prompt (khuôn 1 của TRAPS §1). Điểm (4) đổi chữ ký
  `runner` của `CodexClient` từ `(args)` thành `(args, stdin)` — **không tương thích ngược**, 26 chỗ chèn runner
  trong test studio sửa theo, đúng như phiên K3.3c1 đã cảnh báo trước.
  **`FakeClient` giữ CẢ HAI thay vì chọn một bên**: `calls[i]["user"]` là lượt user thật sự gửi đi (bản company,
  thứ model đọc) và `user_arg` là đối số caller truyền vào (bản studio) — hai thứ khác nhau khi có `messages`, và
  mỗi bản cũ đều mất đúng thứ bên kia dùng. Nhân đó sửa một **niềm tin sai** trong test studio: comment ghi
  `user` là "khoá eval", nhưng `RecordingClient`/`ReplayClient` băm `prompt_key(system, user)` từ **tham số** của
  `complete()` và không đọc `FakeClient.calls` lần nào — ca đó nay dùng `user_arg` và nói rõ vì sao.
  **Bằng chứng đúng loại đặc tả đòi**: `evals … --replay [--strict]` chạy trên bản trước và bản sau, hai công ty,
  danh sách PASS/FAIL **giống hệt từng dòng** — 50 ca company + 28 ca studio. Đo hai chiều 10 đột biến trên bộ
  test core, mỗi cái đỏ đúng phần nó đo; **đột biến "bỏ `check_argv(args)`" ban đầu SỐNG SÓT** vì ca cũ chỉ gọi
  hàm đó trực tiếp — chứng minh hàm đúng, không chứng minh ai gọi nó (đúng khuôn "test xanh cả hai chiều",
  TRAPS §2) — đã thêm ca đi qua chính `complete()` với argv vượt trần, và đo lại thì đột biến ấy đỏ.
  mypy `strict` của core bắt tiếp một chỗ: `ModelClient` chung đòi `workdir`, nên hai adapter c3 còn lại của
  studio và ba lớp bọc trong `studio/evals.py` phải khai (và **chuyển tiếp**, không nuốt) tham số ấy — bản
  company đã làm đúng thế từ trước. Ngoại lệ mypy DUY NHẤT thêm vào core hẹp đúng một module (`anthropic.*`,
  extra tuỳ chọn không cài trong CI), không phải cờ `--ignore-missing-imports` toàn cục như bốn package kia.
  Số đo từ đĩa: `company/llm.py` 921→698, `studio/llm.py` 527→335, dòng trùng trong khối ≥ 8 giữa hai bên
  194→128. Đã chạy: core 130 test / 100%; company 1023 / 100%; studio 471 + 5 skip / 100%; gateway 251, console
  233, không sửa một dòng. `make golden && make subagents` không sinh drift (#173)

- feat(company): **D1b — `deployed` là container đang chạy, không phải lời khai** (cài nốt ADR-0039: nối `deploy()` vào vòng đời release). Lượt deploy của `ops` trên `STAGING_ROUTE`/`PROD_ROUTE` nay đi qua `verify.deploy_release`: `status=deployed` trong `payload` của model chỉ còn là **yêu cầu đi tiếp**, orchestrator dựng compose file của khách rồi **tự kết luận** — đủ ba phần (`up -d` thoát 0 + mọi service `running` + smoke vào cổng đã map) → `deployed` kèm `evidence.deploy = {project, env, services[], container_ids[], port, started_at, smoke, compose_file, verified_by: "orchestrator"}`; thiếu bất kỳ phần nào → **`status=deploy_failed`** kèm phần nào hỏng + `logs_tail` (`deploy()` đã tự `down`, orchestrator **không** gọi `down` lần hai) và gate escalation mở cho người quyết; `skipped` (chưa bật `COMPANY_DEPLOY`, không có compose file, spec không khai `runtime`, không có worktree) **giữ nguyên hành vi cũ** kèm lý do trong evidence — đường lùi để repo đang chạy không gãy. `env` là của **ROUTE**, và production vẫn **chỉ** qua `PROD_ROUTE` sau gate release: ADR-0039 quyết định 5 không thêm cổng nào. `deploy_failed` là giá trị mới của `release-events.status` (schema + `evidence` mới trong `topics/schemas/release-events.json`) và **cố ý không gộp vào `failed`**: `failed` nói sản phẩm hỏng nên trả ticket về `changes_requested`, `deploy_failed` nói chưa dựng được môi trường chạy (thường là hạ tầng máy trực) nên ticket **nằm yên**, không đốt lượt retry; route `_deployed(env)` không khớp nên RC không đi tiếp, không mở gate release. Console có hai bậc phễu riêng `staging_deploy_failed`/`production_deploy_failed` — gộp vào ô "thất bại" là bảo người trực đi tìm một ticket rework không tồn tại. Prompt `ops` **không đổi** (ADR-0039: phải sửa prompt mới chạy được là dấu hiệu ranh giới "model chỉ khai, code mới chứng" bị phá). `docs/TRUC-VA-DUNG-KHAN.md` thêm mức 4 (dừng container: `docker compose -p company-<project_id>-<env> down`, cảnh báo tranh cổng, và **dừng orchestrator không còn đồng nghĩa với dừng sản phẩm**); `docs/HUONG-DAN-VAN-HANH.md` §5.2 thêm `COMPANY_DEPLOY`/`COMPANY_DEPLOY_RUNTIME`/`runtime.deploy` và quy trình **chạy thật** từng bước. Nghiệm thu D1 **chưa đóng**: cần `docs/reports/2026-09-xx-deploy-that.md` — máy phiên không có `/var/run/docker.sock`, đó là việc của người vận hành trên máy trực (#171)

- feat(company): **D1a — `src/company/deploy.py` và `runtime.deploy`** (cài ADR-0039, phần module thuần). `deploy(repo_root, project_id, env, rt)` chạy compose file **của khách** rồi kết luận **ba phần**: `up -d` thoát 0 **và** `ps` cho mọi service `running` **và** smoke probe vào cổng **đọc từ `ps`** trả đúng `expect_status`. Thiếu bất kỳ phần nào → `ok=False`, thu `logs --tail` làm bằng chứng rồi `down` để không bỏ lại container nửa sống; đủ ba phần thì **không** `down` (sản phẩm phải còn sống — đó là khác biệt duy nhất giữa `deploy` và `run_smoke`). Fail-closed đúng khuôn `sandbox_from_settings`: `COMPANY_DEPLOY=auto` thiếu binary → bản ghi `skipped` **kèm tên biến** người vận hành phải đặt (`COMPANY_DEPLOY_RUNTIME` / `COMPANY_DEPLOY=off`), `COMPANY_DEPLOY=compose` khai đích danh mà thiếu binary → **raise**, giá trị lạ → raise, `env` ngoài `staging|production` → raise (env là của ROUTE, không phải lời khai). Ranh giới lệnh: đúng **bốn** lệnh con (`up -d`, `ps`, `logs --tail`, `down`) — `_argv` ném với lệnh con thứ năm; `--project-name company-<project_id>-<env>` do **code** đặt; env qua `clean_env`; thứ duy nhất model chạm được là `runtime.deploy` (đường dẫn compose trong repo khách) và nó phải là file **có thật** — khai sai đường dẫn KHÔNG lặng lẽ rơi về file dò được. Không khai và không dò ra `docker-compose.yml`/`compose.yaml` → `skipped`, **không** phải deploy thành công. `runtime.deploy` thêm vào `topics/schemas/approved-specs.json` + `smoke.Runtime`/`parse_runtime` (approved-specs không có model Pydantic — `PAYLOAD_MODELS` chỉ phủ 8 topic, `runtime` xưa nay đọc bằng `parse_runtime`). `deploy.py` là **ngoại lệ subprocess thứ hai** sau `github_pr.py` (ADR-0039 §7: nhốt một client gọi `/var/run/docker.sock` vào container là vô nghĩa) — khai kèm lý do trong `tests/test_sandbox_noi_vao_cong_ty.py`, và test quy ước ấy nay bắt cả **tham chiếu** `subprocess.run` (không chỉ lời gọi có ngoặc), vì một module tiêm được runner lách được luật cũ bằng cách giữ nó làm giá trị mặc định. Test tiêm runner giả nên **không cần docker daemon** (máy phiên và `windows-latest` của CI đều không có). Đo hai chiều: bỏ vế `ps` → ca "service exited" đỏ, bỏ vế smoke → ca "health 500" đỏ, bỏ `down` ở nhánh hỏng → cả ba ca hỏng đỏ, trả `skipped` thay vì raise ở `COMPANY_DEPLOY=compose` → ca fail-closed đỏ. **Chưa nối vào `release_fsm`/`orchestrator`** (D1b), chưa chạm `agents/`/`skills/`/`evals/` nên không đi 7 bước (#170)

- docs(company): **ADR-0039 — deploy thật bằng `docker compose`** (mục D1 của đặc tả nâng cấp; số ADR mà đặc tả gán trước cho D1 là 0034 đã bị dùng cho việc tách máy trạng thái, xem cảnh báo cuối §8). Ba mảng giao hàng đã có bằng chứng máy sinh — git (ADR-0027), PR cho khách (ADR-0038), smoke đối chiếu verdict (ADR-0029/0036) — riêng deploy thì chưa: `release-events` mang `status=deployed` vì route đặt `env` và agent nói đã xong, không có tiến trình nào của sản phẩm còn sống sau lượt ấy (`run_smoke` khởi động rồi **giết**, đúng cho "chạy được", sai cho "đang chạy"). Quyết định: `runtime.deploy` mới (tuỳ chọn) trỏ file compose **của khách**; staging và production là **hai compose project tách** `company-<project>-<env>`, không chia volume mặc định; `deployed` là kết luận **ba phần** — `up -d` thoát 0 **và** `compose ps` mọi service `running` **và** smoke probe đúng `expect_status` — thiếu một phần là `deploy_failed` kèm `compose down` để không bỏ lại container nửa sống trên máy trực. Chọn runtime theo đúng khuôn fail-closed của ADR-0035 (`COMPANY_DEPLOY=auto|compose|off`: `auto` thiếu docker → `deploy_skipped` kèm tên biến cần đặt; khai `compose` mà thiếu binary → **lỗi**, không tụt về "coi như xong"). Chỉ bốn lệnh con được phép (`up -d`, `ps`, `logs --tail`, `down`), argv do code ghép, `--project-name` do code đặt nên model không đổi được để giẫm sang môi trường khác. `docker compose` **không** đi qua `Sandbox` — nhốt một client gọi `/var/run/docker.sock` vào container là vô nghĩa; đây là ngoại lệ thứ hai sau `github_pr.py`. Prompt `ops` **không đổi**: deploy do code chứng, và nếu phải sửa prompt thì đó là dấu hiệu ranh giới "model chỉ khai, code mới chứng" bị phá. Cách đo chọn theo dữ liệu máy chứ không theo mong muốn: máy phiên có `docker` CLI nhưng **không có daemon**, CI `ubuntu-latest` có docker nhưng ma trận `unit` còn **`windows-latest`** — bắt CI dựng compose thật là đổi một cổng đang xanh lấy một cổng giòn, nên CI **tiêm runner giả** (đo được cả bốn nhánh quyết định) và nghiệm thu D1 là **một lần chạy thật có báo cáo** `docs/reports/…-deploy-that.md`, cùng khuôn B8/S7. Hệ quả nêu thẳng: máy trực từ nay chạy tiến trình **sống lâu** của sản phẩm khách — dừng orchestrator không còn đồng nghĩa với dừng sản phẩm, nên `docs/TRUC-VA-DUNG-KHAN.md` phải có lệnh dừng container riêng khi cài. Chỉ ADR + số liệu README (0001–0038 → 0001–0039), chưa có mã (#169)
- fix(gateway): hàng rào `Host` + `Origin` — chống DNS rebinding và CSRF vào pool tài khoản Google.
  Audit sâu 2026-09-08: gateway KHÔNG có xác thực client và giữ pool tài khoản Google, nhưng không kiểm `Host`
  lẫn `Origin` (grep: 0 hit), trong khi `platform/console/server.py::_guard` đã phòng thủ đúng hai thứ đó từ đầu và ghi rõ
  lý do. Trên loopback, một trang web bất kỳ người dùng đang mở vẫn `fetch()` được sang `127.0.0.1:1123`: CORS
  chặn trang đó ĐỌC phản hồi, nhưng **không chặn tác dụng phụ** — `POST /v1/chat/completions` đốt quota thật,
  `POST /auth/login` mở luồng thêm tài khoản. `warn_if_public_host` chỉ ghi log cảnh báo, không chặn gì.
  Thêm `guard_middleware`: `Host` không loopback → 404 (không xác nhận có server ở đây, như console); `Origin` có
  mặt mà không loopback → 403. Vắng `Origin` (curl, SDK OpenAI) cho qua — trình duyệt LUÔN gắn `Origin` cho
  request cross-origin nên đây đúng là lằn ranh cắt CSRF mà không chạm client dòng lệnh; origin loopback ở **cổng
  bất kỳ** cũng cho qua vì một trang dev cục bộ gọi sang gateway là việc hợp lệ. Hai luật tự tắt khi người vận
  hành cố ý bind ra ngoài loopback (lúc đó `Host` hợp lệ là tên miền thật) — chế độ vốn đã cảnh báo và đòi
  firewall/reverse proxy lo xác thực. Đo hai chiều: gỡ middleware → 2 đỏ; bỏ kiểm `Host` → 1 đỏ; bỏ kiểm `Origin`
  → 1 đỏ; ép luật cả khi bind ra ngoài → 1 đỏ; bản đầy đủ → 26 xanh. gateway 251 test, coverage 100%.
  Kèm mục mới trong `SECURITY.md` (vì sao CORS không đủ) và một dòng `CODEMAP.md` (#172)

- fix(studio): gate quá hạn không còn im lặng, và thế hệ khoá `once` sống sót qua restart (cả hai công ty).
  Audit sâu 2026-09-08 tìm ra `TRAPS.md` §1 khuôn 3 **vẫn sống trong studio**: `studio/orchestrator.py` dùng chung
  khoá `once=f"gate:{sid}"` cho `gate.remind` (12h) và `gate.overdue` (24h), nên lần nhắc ghi khoá trước và
  `gate.overdue` **chưa bao giờ** vào audit-log — company đã vá đúng chỗ này ở `orch/scheduler.py` từ trước, studio
  thì không, vì guard `test_orch_khuon_loi.py` khoá phạm vi ở `src/company/orch/`. Studio còn thiếu luôn bước
  escalate khi quá hạn (`_check_escalations` chỉ nhìn `desk.state == "blocked"`), nên một gate bể hạn không audit,
  không escalate, không ai biết. Khoá nay mang **giai đoạn + thế hệ** (`gate:{sid}:{pha}:{created_at}`) và quá hạn
  gọi `Supervisor.escalate_gate` mới thêm — chống lặp đặt ở `self.once` bền (dựng lại từ audit-log) chứ không ở RAM
  của supervisor (khuôn 2). Rà cả họ lỗi (luật 5) lộ ra lỗi thứ hai **có ở cả company lẫn studio**: thế hệ là
  `GateRequest.created_at`, mà tiến trình tạo gate giữ mốc dựng dataclass còn tiến trình dựng lại từ replay đặt
  `created_at=env.ts` — lệch vài trăm micro giây, nên mỗi lần mở lại bus là mọi gate đang chờ đổi thế hệ và bị nhắc
  lại + escalate lại. Vá tại gốc chung: `PersistentGate.request` gán `r.created_at = env.ts` trước khi publish (một
  helper `_envelope` mới, hai package). Thêm `Studio-creators/tests/test_khuon_loi.py` — bản đối xứng của guard
  company, bắt cả khoá viết inline lẫn khoá qua biến `key`, và tự kiểm mẫu trên một vi phạm đã biết (TRAPS §2). Đo
  hai chiều từng thành phần: bỏ pha → đỏ; bỏ thế hệ → đỏ; bỏ escalate → đỏ; bỏ `r.created_at = env.ts` → đỏ ở cả
  hai package; đủ bản sửa → 980 + 476 test xanh, coverage 100% cả hai. Kèm ba chỗ tài liệu hub trôi sau ADR-0037 mà
  PR #167 chỉ sửa ở cấp package: `ARCHITECTURE.md` bảng gate còn `plan` (bỏ từ #158) và ADR "0001–0029" (thực tế
  0039), `docs/NGON-NGU.md` cùng lỗi gate `plan`; số test trong ba README đo lại từ đĩa (#172)

- docs: bảng theo dõi §8 của `docs/DAC-TA-NANG-CAP-2026-09.md` khớp lại thực tế đo trên `main`. Bảng đang nói sai ở sáu ô, tất cả đều theo hướng **báo thiếu việc đã làm**: **E1** ghi "chưa" nhưng đã xong từ #125 (ADR-**0034**, `orchestrator.py` còn 508 dòng < ngưỡng 900, bảng `Transition`/`step()` ở `orch/fsm.py`, test bảng `tests/test_orch_bang_chuyen.py`); **D2** ghi "chưa" nhưng đã xong từ #116 (ADR-0035, `sandbox.py`); **E5** ghi "chưa" nhưng `.github/workflows/pr-policy.yml` đã chặn PR thiếu dòng CHANGELOG (đỏ) và nhắc thiếu `docs/sessions/<ngày>.md` (cảnh báo, cố ý không chặn merge). Lý do bảng trôi: ba mục ấy được làm dưới **kế hoạch khác** — `docs/DAC-TA-TRIEN-KHAI-KICH-BAN-B.md` (chuỗi K0–K8) là bản "PR theo PR" đang chạy, còn bảng này là bản chiến lược; khi hai kế hoạch cùng sống mà không ai đối chiếu thì bảng chiến lược thành tài liệu chết. Ba ô còn lại sửa theo hướng ngược: **B8** và **S7** ghi rõ "chưa" (không có `docs/reports/*du-an-mau-2*`, không có báo cáo video thật) thay vì để trống, và **E3** ghi "nửa đầu xong" (6/6 agent đã có bản ghi model thật; mục tiêu cũ ghi "21 agent" đã bị ADR-0037 rút còn 6) — còn thiếu `evals/thresholds.yaml` và CI so trung vị 3 lần. Gộp ba dòng `B1–B8` mâu thuẫn nhau (một dòng ghi "B2 xong", một dòng ghi "B2 wip") thành một dòng có đủ số PR. Thêm cảnh báo ở cuối §8: **số ADR ở cột "ADR" của §4 là số ĐẶT TRƯỚC, không phải số thật** — thực tế 0034 → E1, 0035 → D2, 0036 → việc khác, 0037 → gộp 21 agent, 0038 → PR thật cho khách; nên D1, D3, E1, E2 đang trỏ vào số đã bị dùng cho việc khác, và mục nào cần ADR thì viết số kế tiếp thay vì đi tìm số cũ. Không đổi mã, không đổi phạm vi mục nào (#168)

- docs(company): ADR-0037 **PR-6 — bước cuối**: tài liệu và console nói đúng hệ 5 công đoạn. `README.md` (package) đổi bảng "7 khối / 21 vai" thành bảng **5 công đoạn + supervisor** có cột Tier và cột Pha, luồng chính viết lại theo `agent[pha]` (`product[intake]→[research]→[spec]→[plan]`, `builder[stack]`, `qa[author|review]`, `ops[deploy|docs|account]`), và sửa các số đã trôi: 21→6 system prompt, 18→19 JSON Schema topic, 16→10 subagent, golden 5→4 hồ sơ gate, coverage "≥ 90%"→`fail_under = 100` (hai chỗ). `ARCHITECTURE.md` + `CODEMAP.md` của package: sơ đồ "một ticket đi qua đâu" bỏ `GATE plan` (không còn từ PR-2) và đi theo pha; CODEMAP trỏ sáu file `agents/` thật thay vì 21 tên cũ; thêm dòng `roles.py` vào bảng lớp code. `docs/architecture.md`: mục **Human gate** sửa lỗi thực chất — nó vẫn ghi "ba điểm bắt buộc: spec, **plan**, release" trong khi `GateKind` chỉ còn `spec|release|acceptance|escalation`. `docs/HUONG-DAN-VAN-HANH.md`: "vòng lặp dừng ở bốn điểm" → ba, và ví dụ `gate_cli reject PLAN-P1` (một lệnh KHÔNG chạy được nữa) đổi thành `reject REL-001`; hai khối output mẫu chép lại từ lệnh chạy thật trong phiên (`error:product:` thay `error:intake:`, `gate release pending` thay `gate 3 pending`). `docs/DIEU-PHOI-MODEL.md`: bảng 21 dòng → 6 dòng có cột Pha, kèm điều bảng cũ giấu mất — **tier là của agent, không của pha**, nên pha nặng nhất quyết định tier (`intake` từng `light` nay đi theo `product` `strong`); đối chiếu `model_tier` thật trong front matter: strong = product/builder/security, standard = qa/ops, light = supervisor. Console: `truth.py` bỏ ba chuỗi prose PR-5b/5c cố ý để lại ("Chờ release-engineer", "Chờ qa-debugger hồi quy") — nay dựng từ `ROLE` kèm tên pha nên không thể trôi lần nữa; `API.md` đổi ví dụ `agent`/`who`. Số đo lại từ đĩa, không chép từ đặc tả: `load_agents()` = 6, `.claude/agents/*.md` = 10, ADR = 38 (0001–0038), test = 877 hàm / 61 file. Không chạm `agents/`, `skills/`, `evals/`, `tests/golden/` nên không phải đi 7 bước (#167)
- fix(company): pha `research` của agent `product` trả **bốn mục thẳng trong `data`**, không bọc thêm một tầng. Mục `## Đầu ra` → `### Pha research` của `agents/research/product.md` viết "`research-findings` với **sections**: domain{…}, ux{…}, codebase{…}, tech{…}" — chữ "sections" là tiếng Việt nghĩa "các mục", nhưng nằm giữa một danh sách khoá tường minh nên model đọc thành TÊN KHOÁ và trả `data.sections.domain` thay vì `data.domain`. Nội dung model sinh ra vốn đã đúng và đủ (regulations có Nghị định 13/2023, glossary 10 mục, ux.flows 4, ux.personas 4, tech.options 5, tech.ai_risks 5, codebase ghi "Không áp dụng" kèm lý do) — chỉ hình dạng sai một tầng, làm **2/16 ca eval `product`** đỏ ở 8 assert. Câu chữ mơ hồ này có sẵn từ `agents/research/researcher.md` cũ và vẫn pass ở đó; nó chỉ lộ ra khi prompt bốn pha dài thêm (đúng rủi ro "prompt loãng", ADR-0037 §8). Sửa **prompt** cho hết mơ hồ, KHÔNG sửa kỳ vọng của ca eval: không chỗ nào trong `src/` đọc `data.domain`, nên ca eval là nơi duy nhất giữ giao kèo hình dạng — chấm model bằng chính đáp án nó vừa trả là hạ chuẩn trá hình. Ba chỗ trong pha `research` nay nói rõ khoá: `## Đầu ra` liệt kê `data.domain{glossary, processes, regulations}` / `data.ux{personas, flows, screens}` / `data.codebase{architecture, debt, touchpoints}` / `data.tech{options, licenses, costs, ai_risks}` kèm câu chốt "(`data.sections.domain` là SAI)", `## Bạn PHẢI` và `## Definition of done` nhắc lại "bốn khoá thẳng trong `data`". `product` v1 → **v2**; ghi lại `evals/recordings/product.json` bằng model thật. Đo hai chiều: `make eval-replay` trước sửa **14/16**, sau sửa **16/16** (#166)
- refactor(company): ADR-0037 PR-5e — **agent `product`** (gộp `intake` + `clarifier` + `researcher` + `synthesizer` + `spec-writer` + `risk` + `delivery-lead`), bước CUỐI của chuỗi PR-5x. `agents/research/product.md` mang bốn pha `intake`/`research`/`spec`/`plan`: mỗi mục H2 (Vai trò / PHẢI / KHÔNG ĐƯỢC / Đầu vào / Đầu ra / Definition of done) có H3 theo pha, thân bài **chép nguyên văn** từ bảy agent cũ (ADR-0004: mỗi dòng là một bài học đã trả giá), chỉ đổi câu nói về "agent khác mà nay cùng là mình"; `delivery-lead` được kế thừa ở bản **v13** của PR-5d (dispatching dạy `assignee=builder` + `stack`). Mục KHÔNG ĐƯỢC **chung** thêm dòng §10.1: không tự nhảy pha. `load_agents()` 12 → **6** (5 công đoạn + `supervisor`, là một file trong `agents/` nên vẫn được đếm — `test_all_6_agents_load` khoá cả hai con số kèm lý do). `ROLE.PRODUCT` = `"product"`, **xoá** sáu hằng cũ; bảy id cũ vào `MIGRATED`, trong đó hai tên SỐNG TIẾP với nghĩa mới: `intake`/`researcher` là `kind` của `research-findings` (`roles.FINDING_KIND`) và `delivery-lead` là `LEAD_ACTOR` — actor của event do `delivery.py` phát, nay chính thức KHÔNG còn là id agent (`test_hang_role_khop_front_matter_hai_chieu` khoá điều đó). **Guard theo pha thay guard theo actor** (§1.2): khi cả `requirements-draft` lẫn `clarification-questions` đều mang `actor=product`, `_from(<agent>)` không phân biệt được lượt nào — `_from_phase(name)` đọc `payload["_phase"]` do RUNNER ghi (PR-3), `_from_kind` dùng `kind` sẵn có của `research-findings`. **Lượt `risk` riêng bị bỏ**: chuỗi nghiên cứu còn 5 event thay vì 6, rủi ro nằm ngay trong `risks` của draft và `requirements-draft.json` nâng `risks` lên **required**. `_plan` gọi `generate(PRODUCT, …, phase="plan")`; `_spec_runtime_missing` và `_act_clarification_fallback` bỏ `Route(...)` dựng tay, dùng `routes.spec_route(topic)` lấy đúng dòng trong `ROUTES` (bài học PR-5c: Route tay không mang `phase`/`enrich`/`tools`). `NAMESPACE_OWNERS`: `prd`, `glossary`, `design`, `architecture` → `product`, `api-contract` → `{product, builder}`; `bus.TOPIC_PRODUCERS` ba topic nghiên cứu → `{product}`; `graph.RESEARCH_ORDER` còn hai node. **`stack` bắt buộc ở `_check_plan`, KHÔNG `required` trong `tasks.json`** (§13 vs §4.2): ép ở tầng bus thì bus từ chối từng ticket và kế hoạch chết giữa chừng, còn ở `_check_plan` cả kế hoạch quay về cho `product` kèm tên ticket thiếu — cùng lập luận PR-5d đã nêu. `evals/product.yaml` = bảy yaml cũ gộp lại (16 ca, mỗi ca khai `phase:`), hai ca của `risk` thành `expect.min_len: {risks: …}` trên draft của pha `spec` (§11), thêm ca **"nhầm pha"** bắt buộc (đề bài thô gửi kèm prompt pha `plan`, chấm bằng từ của đề bài chứ không bằng chữ "pha"); xoá 7 yaml + 7 recording, `REQUIRED.txt` thay bảy dòng bằng `product`. Test mới bắt buộc `test_chuoi_research_di_dung_5_luot_theo_pha`: chuỗi end-to-end `intake → research → spec → intake(câu hỏi) → spec(approved)` đúng **5 lượt** với `phase` trong audit đúng thứ tự; chiều đảo tắt guard `_from_phase` → chuỗi sai thứ tự/lặp → test ĐỎ. Bảy bước `CONTRIBUTING.md` §3 đủ, kể cả `make eval-record AGENT=product` bằng **model thật**. Số liệu cơ học: README gốc + package 12→6 agent, 16→10 subagent; `docs/architecture.md` bảng Consumer; `docs/dac-ta-tro-ly-kiem-duyet.md`. Prose README/ARCHITECTURE/HUONG-DAN/DIEU-PHOI-MODEL/console để dành PR-6 đúng §7 (#165)
- refactor(company): ADR-0037 PR-5d — **agent `builder`** (gộp `backend` + `frontend` + `mobile` + `database` + `platform` + `data`). `agents/engineering/builder.md` mang sáu pha `backend|frontend|mobile|database|platform|data` **chọn theo `stack` của ticket, không theo route** (ADR-0013 + §10.2): mỗi mục H2 (Vai trò / PHẢI / KHÔNG ĐƯỢC / Đầu ra / Definition of done) có H3 `### Stack <tên>` chép **nguyên văn** từ sáu agent cũ, phần trước H3 đầu là phần chung (engineering-common + phần chung của backend/frontend/mobile). Mục KHÔNG ĐƯỢC chung thêm hai dòng §10.2: không tự đổi `stack`, không ghi namespace `architecture`. Sáu prompt cũ còn nhắc `test-author` (PR-5c để dành) nay nói `qa` (pha `author`). `load_agents()` 17 → 12. `ROLE.BUILDER` = `"builder"`, **xoá** sáu hằng cũ; sáu id ấy KHÔNG biến mất khỏi hệ mà đổi nghĩa — chúng là `stack` của ticket, nên `roles.STACK`/`BUILD_PHASES` giữ chúng và `test_roles` vẫn cấm chúng dưới dạng chuỗi ở mọi file `src/` khác. `Assignee = Literal["builder"]` + `tasks.json`/`test-suites.json` `assignee.enum` → `["builder"]` (sửa cùng lúc, `test_schema_consistency`); `Task.stack` đổi sang kiểu riêng `BuildPhase`. `Route.agent` bỏ ký hiệu `"$assignee"` (route trỏ thẳng `ROLE.BUILDER`) nên `Route.agents()` và nhánh chọn agent theo payload trong `_call` biến mất — agent của một lượt lại chỉ do BẢNG ROUTE quyết định. `NAMESPACE_OWNERS`: `api-contract` (cùng lead), `schema`, `infra`, `analytics` → `builder`; `EXPERTS["escalation"]` `sc-<assignee>` → `sc-builder`. `stacks.py` KHÔNG đổi (stack ở đó là của repo khách: python/node). **Hai thứ đặc tả không nói, phát hiện khi chạy** — nêu thành lời: (1) `delivery-lead.md` v12 → v13, dòng dispatching còn dạy `assignee ∈ backend|…|data`, tức dạy model sinh ra `tasks` mà schema mới từ chối — ticket sẽ chết ở `invalid_output` chứ không ở test; nay nó dạy `assignee=builder` + `stack` và nói vì sao (`stack` chọn skill của lượt), nên PR này ghi lại eval của `delivery-lead` luôn; (2) `phase_for` bỏ đường lùi `payload["assignee"]` — sau PR-5d `assignee` luôn là `builder`, một giá trị không bao giờ là pha, nên giữ nó chỉ là mã chết che mất việc ticket thiếu `stack`. `evals/builder.yaml` = sáu yaml cũ gộp lại (mỗi ca `phase:` = `stack`) + ca **"nhầm pha"** bắt buộc theo §11 (ticket migration gửi kèm prompt pha `frontend`); xoá 6 yaml + 6 recording, `REQUIRED.txt` thay sáu dòng bằng `builder`. `evals/qa.yaml` đổi `assignee: backend` → `assignee: builder` + `stack: backend` (bus từ chối payload cũ) nên qa cũng phải ghi lại. Test mới bắt buộc `test_ticket_frontend_nap_dung_skill_cua_mang_khong_nap_mang_khac`: đi đúng chuỗi thật (route `tools="rw"` → `phase_for` → `system_prompt`) và khoá cả hai chiều — prompt của ticket `stack=frontend` có `Skill: frontend` và KHÔNG có `Skill: backend`. Bảy bước `CONTRIBUTING.md` §3 đủ, kể cả `make eval-record` bằng **model thật**. Số liệu cơ học: README gốc + package 17→12 agent, 21→16 subagent; `docs/architecture.md` bảng Consumer + vòng đời ticket; `docs/dac-ta-tro-ly-kiem-duyet.md`. Prose README/ARCHITECTURE/HUONG-DAN/DIEU-PHOI-MODEL để dành PR-6 đúng §7 (#164)
- refactor(company): ADR-0037 PR-5c — **agent `qa`** (gộp `test-author` + `reviewer` + `qa-debugger`). `agents/quality/qa.md` mang hai pha `author`/`review`: mỗi mục H2 (PHẢI / KHÔNG ĐƯỢC / Đầu vào / Đầu ra / Definition of done) có H3 theo pha, thân bài **chép nguyên văn** từ ba agent cũ (ADR-0004: mỗi dòng ấy là một bài học đã trả giá), chỉ đổi câu nói về "agent khác mà nay cùng là mình". Mục KHÔNG ĐƯỢC **chung** thêm dòng §10.3 — ở pha `review` không được nới assert của test do chính mình viết ở pha `author`; test sai đặc tả thì ghi `finding` cho builder mở `test_dispute`. `load_agents()` 19 → 17. `ROLE.QA` đổi GIÁ TRỊ thành `"qa"`, **xoá** `ROLE.TEST_AUTHOR`/`ROLE.REVIEWER` (gộp 3→1 như PR-5b), ba id cũ vào `MIGRATED`. Bốn route: `tasks`→test-suites và `pull-requests`(`test_dispute`)→test-suites mang `phase="author"`; `pull-requests`→review-results là **MỘT** route `phase="review"` cho MỌI ticket (enrich gộp `_with_diff` + `_with_chan_doan`, guard `_needs_qa` biến mất); release-events staging `phase="review"`. **`RISK_REVIEWS = {security}`** (ADR-0037 §3): `qa` chấm mọi PR dưới nhãn `source: reviewer` nên nó là review NỀN, không còn là review "thêm" của ticket rủi ro — giữ `qa` trong đó thì ticket có `risk_tags` chờ mãi một nhãn không ai phát. `REVIEW_AGENT` (company + console) trỏ cả `reviewer` lẫn `qa` về agent `qa`; `SOURCE.*` giữ nguyên vì `source` là **nhãn chấm**, không phải id agent. **Chốt chặn đặc tả không nói, phát hiện khi chạy**: hai chỗ giao lại review (`gates_flow._on_gate_decide`, `scheduler` khi quá hạn) dựng TAY `Route("pull-requests", agent, "review-results")` — Route dựng tay không mang `phase`/`enrich`/`tools`, nên lượt giao lại chạy bằng prompt pha `author` (không skill code-review, không diff, không tool) rồi trả ra `test-suites` sai topic; thay bằng `routes.review_route(agent)` lấy đúng dòng trong `ROUTES`. Kèm theo: `tests_authored_by` enum trong `topics/schemas/pull-requests.json` `test-author` → `qa`; `bus.TOPIC_PRODUCERS` `test-suites` → `{qa}` và `REVIEW_PRODUCERS` bỏ actor `reviewer`; `supervisor.md` v12 → v13 (bảng "nguồn review thiếu → agent" trỏ `qa-debugger`/`reviewer` là hai id không còn tồn tại, supervisor sẽ giao việc cho hư không) nên **eval-record cả `supervisor`**. Test mới bắt buộc `test_qa_hai_route_khac_tool` đo ba khác biệt của hai pha trên cùng một orchestrator: đầu vào (BLIND_STRIP gỡ `hint`/`diff`/`chan_doan` ở lượt author), quyền (author ghi được vùng test và `write_scope="tests"` từ chối `feature.py`; review chỉ-đọc), prompt (`cache_key` `qa[author]`/`qa[review]`). `evals/qa.yaml` = ba yaml cũ gộp lại + ca hồi quy staging (chỗ DUY NHẤT còn kỳ vọng `source: qa`) + ca **"nhầm pha"** bắt buộc theo §11; xoá 3 yaml + 3 recording cũ, `REQUIRED.txt` thay ba dòng bằng `qa`. Bảy bước `CONTRIBUTING.md` §3 đủ, kể cả `make eval-record` bằng **model thật** (`claude-code`, `claude-sonnet-5`: qa **8/8 pass**, supervisor **3/3 pass**). Máy eval (ghi/phát lại/gộp bản ghi) trong `test_tools_and_agentic` chuyển sang đo trên `security` — agent không pha duy nhất còn lại có đúng hai ca cùng một topic ra. Đo hai chiều 3 đột biến: (A) bỏ `phase=` khỏi hai route → `test_qa_hai_route_khac_tool` ĐỎ; (B) `phase_for` trả `None` cho route khai pha → cùng test ĐỎ ở `cache_key` (`('qa','qa')`); (C) `ROLE.QA` về `"test-author"` → 393 ca ĐỎ. Khôi phục → 1010 test / coverage 100%. Số liệu cơ học: README gốc + package 19→17 agent, 23→21 subagent; `docs/architecture.md` bảng Consumer + vòng đời ticket; `docs/dac-ta-tro-ly-kiem-duyet.md` `sc-qa-debugger` → `sc-qa`. Prose console ("Chờ qa-debugger…") và README/HUONG-DAN để dành PR-6 đúng §7 (#163)
- refactor(company): ADR-0037 PR-5b — **agent `ops`** (gộp `release-engineer` + `support-docs` + `account-manager`). `agents/operations/ops.md` mang ba pha `deploy`/`docs`/`account`: mỗi mục H2 (PHẢI / KHÔNG ĐƯỢC / Đầu vào / Đầu ra / Definition of done) có H3 theo pha, thân bài **chép nguyên văn** từ ba agent cũ (mỗi dòng ấy là một bài học đã trả giá — ADR-0004), chỉ bỏ câu nói về "gửi cho agent khác mà nay cùng là mình". `load_agents()` 21 → 19. `ROLE.OPS` đổi GIÁ TRỊ thành `"ops"` và **xoá** `ROLE.SUPPORT_DOCS`/`ROLE.ACCOUNT_MANAGER` — khác PR-5a (đổi tên 1:1), gộp 3→1 không giữ được ba hằng cùng một id (`test_hang_role_khop_front_matter_hai_chieu`). Bảy route đổi sang `ops` + `phase` (`STAGING_ROUTE`/`PROD_ROUTE` `deploy`; release-events production, external-feedback→incidents, incidents→research-requests `docs`; external-feedback→change-requests, acceptance-results conditional `account`); `_open_acceptance_gate` `created_by=ROLE.OPS`; `EXPERTS["acceptance"]` gộp còn `sc-ops`; `NAMESPACE_OWNERS` `docs`+`contract` và bốn dòng `TOPIC_PRODUCERS` → `{ops}`. **Hai chốt chặn đặc tả không nói, phát hiện khi chạy**: (1) `Orchestrator.partial` khoá theo TÊN AGENT nên khi `external-feedback` khớp HAI route cùng agent `ops` (docs→incidents, account→change-requests) route thứ hai bị nuốt **im lặng** — khoá nay là `"<agent>:<topic_out>"`, `_recall` bỏ mọi slot của agent, `rehydrate` dựng lại bằng `f"{actor}:{topic}"`; (2) `evals.py` chưa từng truyền `phase` (trước `ops` không agent nào có `phases`) — `AgentRunner.run` nhận `phase`, `_run_case` bắt buộc ca của agent có `phases` khai `phase:` hợp lệ, sai/thiếu là `RunnerError` chứ không âm thầm chạy prompt pha `None`. Sai khác có chủ ý so với đặc tả: `writes` của `ops` thêm `acceptance-results` (§1.1 liệt kê thiếu, §10.5 và account-manager cũ đều có — không thêm thì không route/eval nào tạo được topic đó nữa). `evals/ops.yaml` = ba yaml cũ gộp lại, mỗi ca gắn `phase`, **thêm ca "nhầm pha"** bắt buộc theo §11. Bảy bước `CONTRIBUTING.md` §3 đủ, kể cả `make eval-record AGENT=ops` bằng **model thật** (`claude-code`/`claude-sonnet-5`, **8/8 pass** — ca nhầm pha cũng pass: model tự nhận sai pha và ghi `rulings` thay vì làm bừa). Đo hai chiều 3 đột biến: (A) `partial` khoá lại theo agent → ca hai-route ĐỎ (change-requests rỗng); (B) bỏ kiểm `phase` trong `_run_case` → 2 ca eval-phase ĐỎ; (C) `ROLE.OPS` về `"release-engineer"` → 307 ca ĐỎ. Khôi phục → 1017 test / coverage 100%. Console đổi kèm (không tách được): `truth.py::NEXT_AGENT["acceptance"]` dùng hằng đã bị xoá, hai test console cập nhật kỳ vọng; console 232 xanh. Số liệu cơ học: README gốc + package 21→19 agent, 25→23 subagent (#162)
- refactor(company): ADR-0037 PR-5a — **agent `security`** (đổi tên `security-engineer`, gộp 1:1). Đây là PR-5 đầu tiên: mục đích của nó là chạy **quy trình đổi tên một agent** qua trọn CI trước khi làm các agent gộp nhiều nguồn, nên phạm vi cố ý hẹp — không đổi route, không đổi hành vi, không đổi một dòng nào của thân bài prompt ngoài chính cái tên. `agents/quality/security-engineer.md` → `agents/quality/security.md` (`id`, tiêu đề `# security`, `version` 7 → 8); `ROLE.SECURITY` đổi GIÁ TRỊ chứ không đổi tên hằng (PR-4 đã gom về `roles.py`), nên `THREAT_ROUTE`, `_threat_model`, hai route `pull-requests`/`release-candidates` và `NAMESPACE_OWNERS["threat-model"]` không phải sửa một chữ. `RISK_REVIEWS` giữ `{qa, security}` tới PR-5c theo đặc tả. **Chỗ bẫy duy nhất của PR này**: id agent mới `security` trùng nguyên văn nhãn `source` `"security"` của `review-results`, nên ba literal vốn hợp lệ (`delivery.py`, `orch/ticket_fsm.py`, `orch/routes.py`) bị `test_khong_con_id_agent_dang_chuoi_trong_src` bắt ngay — đúng ý test: từ nay chúng phải viết là `SOURCE.SECURITY` để người đọc thấy đó là *nhãn chấm*, không phải *agent*. `tests/test_roles.py` thêm bảng `MIGRATED` (id cũ → id mới, lớn dần một dòng mỗi PR-5x) làm chỗ duy nhất test biết đợt gộp đã đi tới đâu; `OLD_IDS` giữ nguyên 21 tên nên `security-engineer` không được quay lại `src/` dưới dạng chuỗi. Đủ 7 bước `CONTRIBUTING.md` §3: version ↑, `make golden` (88 xanh, golden cũ xoá tay vì `make golden` không tự dọn file dẫn xuất thừa), **`make eval-record AGENT=security` bằng model thật** (provider `claude-code`, `claude-opus-5`, 2/2 pass, 55.8k token) — `evals/security-engineer.yaml`/`.json` đổi tên, `REQUIRED.txt` thay dòng, `make assetscan` (101 file, 0 lỗi nặng), `make assetbudget` (security 8163 tok tĩnh / 80000 = 10%), `make subagents` (`sc-security-engineer.md` xoá tay → `sc-security.md`). Hai fixture eval của `delivery-lead`/`platform` ghi `actor: security-engineer` vào namespace `threat-model` phải đổi theo, nếu không bus từ chối quyền ghi khi phát lại (không làm bản ghi nào lệch — khoá bản ghi không tính context fixture). Đo hai chiều 3 đột biến: (A) `ROLE.SECURITY` về `"security-engineer"` → 296 ca đỏ; (B) `SOURCE.SECURITY` đổi thành id agent → 135 ca đỏ (chứng minh hai hằng trùng chữ vẫn là hai thứ khác nhau); (C) `REQUIRED.txt` giữ tên cũ → 2 ca cổng bản ghi đỏ. Khôi phục → xanh. Đã chạy: company 1013 test / coverage 100%, `make test` cả năm package xanh (console 232, gateway 225, studio 464+5 skip, core 109), ruff + mypy sạch, `subagents-check` khớp, `eval-replay --strict` mã thoát 0 (3 FAIL có sẵn từ trước, không phải của security) (#160)
- refactor(company): ADR-0037 PR-4 — **gom tên vai về một chỗ**. `src/company/roles.py` mới là NƠI DUY NHẤT id agent xuất hiện dưới dạng chuỗi trong `src/` (ngoài `agents/*.md`): `ROLE.*` (21 hằng, một per agent, đặt tên theo ĐÍCH ADR-0037 — `ROLE.SECURITY` hôm nay là `"security-engineer"`, PR-5a chỉ đổi giá trị), `SOURCE.*` (nhãn `source` của review-results, cố ý tách vì `reviewer|qa|security` trùng chữ với id agent nhưng không phải agent), `LEAD_ACTOR` (actor của event do `delivery.py` phát — code, không phải model). `Assignee`/`ReviewSource` (`Literal`) dời sang `roles.py` vì `typing` không nhận biến. 121 literal trong 15 file (`bus`, `events`, `delivery`, `demo`, `graph`, `supervisor`, `gate_checklists`, 8 file `orch/`, `platform/console/truth.py`) thay bằng hằng; `ENGINEERING`, `REVIEW_AGENT`, `NAMESPACE_OWNERS`, `EXPERTS`, `NEXT_AGENT` tham chiếu `roles`. **Không đổi hành vi, không đổi agent nào** — giá trị mọi hằng bằng chuỗi cũ. Test bảo vệ `tests/test_roles.py` (7 ca): quét bằng `tokenize` (chỉ token STRING, không bắt chú thích), một dòng miễn trừ duy nhất (`payload.get("data")` — trường của research-findings) khoá theo nguyên văn dòng và có test riêng kiểm dòng còn tồn tại; bộ quét tự chạy trên vi phạm biết trước (`TRAPS.md` §2); đối chiếu hai chiều `ROLE.*` ↔ `load_agents()`. Đo hai chiều: chèn lại literal ở `routes.py:329` + `truth.py:72` → đỏ đúng hai vị trí; khôi phục → xanh. Đã chạy: company 1013 test / coverage 100%, console 232 / 100%, ruff + mypy sạch cả hai, `make subagents-check` khớp (#159)
- refactor(company): ADR-0037 PR-2 — **bỏ `GateKind` `plan`**. `GateKind` còn bốn giá trị (`spec|release|acceptance|escalation`): hai gate công đoạn, một chữ ký của khách, một đường bất thường. `_plan` không mở gate nữa mà gọi `_dispatch_plan` ngay sau `plan.proposed` — mọi khoá "Code gửi kèm" của gate plan cũ đã thành `problems` của `_check_plan` ở PR-1 (#154), nên bỏ gate không mất kiểm nào. Guard **không** biến mất, chỉ đổi nguồn sự thật: `DeliveryLead.dispatch` hỏi `lead.plans_ok` (orchestrator ghi plan_id vào đó ngay sau khi `_check_plan` sạch) thay vì `gate.is_approved`, và `plan_id` lạ vẫn `PermissionError`. **Chỗ dễ mất trạng thái nhất là `rehydrate`**: ticket trước đây được dựng lại từ nhánh `gate.decide` approve; nay dựng ở nhánh `plan.proposed` — bỏ gate mà quên dời là mở lại bus thì ticket biến mất (khuôn 2 `TRAPS.md`), và dựng ở `plan.proposed` còn đúng thứ tự log hơn vì mọi `tasks`/`ticket.blocked` nằm sau nó. Hai mục người-tự-kiểm của gate plan cũ ("Ước lượng có cơ sở", "Ngân sách token") **dời sang gate release giữ nguyên `id`** `plan.uoc-luong-co-so`/`plan.ngan-sach-token` để hồ sơ `gate_brief` cũ trên đĩa còn đọc được; `_brief_plan` thành `_brief_estimates` đo trên chính ticket của release; checklist gate release thêm hai khoá `threat-model`, `architecture`. `checklists.md` đánh số lại (Gate 1 spec, Gate 2 release, gate nghiệm thu bỏ số) kèm dòng mapping số cũ → số mới, vì **system prompt của agent vẫn nói "Gate 3"** — sửa `agents/` là 7 bước `CONTRIBUTING.md` §3 (cần `eval-record` model thật), để PR-5x. Console: xoá nhánh `plan` trong `truth.py` sau khi kiểm `collect.py` xác nhận chỉ `CompanyView` dùng bảng đó (Studio **vẫn có** `GateKind` `plan` nhưng dùng mặc định rỗng); màn hướng dẫn đổi "bốn điểm dừng" → "ba điểm dừng" và nói rõ kế hoạch do code kiểm. `sc-gate-plan.md` xoá khỏi `.claude/agents/`. Phần lớn diff là test: `_drive_to_plan` cũ dừng ở gate plan nên hàng chục test dùng nó làm **mốc dừng** để chen sự kiện vào giữa (pause ticket, `max_steps`, ký gate từ tiến trình khác) — thêm `_drive_to_spec_gate` làm mốc dừng cuối cùng còn lại và chuyển những test đó sang dùng nó. Test mới `tests/test_bo_gate_plan_adr0037.py` (6 ca). Đo hai chiều 3 đột biến (trả lại gate plan trong `_plan`; bỏ guard `plans_ok`; `rehydrate` không giao lại) — mỗi đột biến làm đỏ đúng ca đo nó. Đã chạy: company 1006 test / coverage 100%, console 232 / 100%, `make test` cả năm package xanh, `make lint` sạch, `subagents-check` khớp, `assetscan` 0 lỗi nặng, `eval-replay` không đổi (3 FAIL có sẵn từ trước, prompt không đổi một byte) (#158)
- feat(company): ADR-0038 — **PR thật cho khách review trước khi ký UAT**. Cờ `--deliver-pr` (mặc định tắt; cần `--deliver` + `--push-remote` trỏ remote GitHub + `gh auth login`): sau khi `Integration.deliver` đã push nhánh release + tag, orchestrator mở PR `company/release → <--base>` bằng `gh pr create` — **mở, không merge**; PR đang mở cùng head/base thì dùng lại (release sau fast-forward vào chính PR đó; rollback `--force-with-lease` kéo PR lùi theo). `main` khách vẫn không bị chạm (ADR-0011/0027 giữ nguyên); review nội bộ giữa các ticket vẫn theo nhánh tích hợp. Kết quả là bằng chứng máy ghi trong `delivery.done.pr` (`{url, number, created, slug, base, head}` | `{skipped}` | `{error}`, `PrRecord` TypedDict) + audit riêng `delivery.pr_opened|pr_reused|pr_skipped|pr_failed`; mở lại bus dựng lại được, không gọi `gh` lần hai; `status → delivery → pr`. `gh` lỗi/không cài/remote không phải GitHub **không chặn bản giao** (cùng nguyên tắc `push_failed`). Module mới `github_pr.py` (`github_slug`, `open_pr`, `_gh` chạy với `clean_env` — token trong env bị lọc, xác thực phải ở đĩa) là ngoại lệ có lý do của test quy ước ADR-0035, có test chiều ngược. gate `acceptance` thêm mục tự kiểm "Khách đã xem bản giao trong PR thật" (`gates/checklists.md` → `make subagents` → `sc-gate-acceptance.md`; `gate_brief` trả lời từ `delivery.done.pr`, golden `gate_brief/acceptance.json` cập nhật). Prompt `release-engineer` **không đổi** — PR do code mở. Đo hai chiều: bỏ gọi `_delivery_pr` → 2 ca đỏ; bỏ ngoại lệ `CHI_GH` → test quy ước đỏ; bật lại → xanh. Đã chạy: 1023 ca / coverage 100 % (sau rebase lên #158/#159), ruff + mypy sạch, `make subagents-check` khớp; README company/gốc cập nhật 1023 test, ADR 0001–0038; `docs/HUONG-DAN-VAN-HANH.md` thêm đoạn `--deliver-pr` (#161)
- docs: ADR-0004 (**được chấp nhận**) — đối chiếu `neo4j-labs/agent-memory` @`0186a93` (44.8k dòng Python src / 45.9k test, mypy strict, coverage 55 %, bắt buộc Neo4j). Kiểm ngược với mã ta: vòng học estimate-vs-actual **đã đóng** (`ticket_fsm.py:83` đưa `calibration()` vào planning); nhưng `knowledge` mà agent nhìn thấy chỉ là **một** JSON của ticket đóng gần nhất (`blackboard.py::_latest`) → quyết định cho **K3.6**: `knowledge` là bộ sưu tập có truy vấn (`lessons_for(ticket)` lọc theo `assignee`/`risk_tags`, ≤ 5 bản, không vector), `snapshot()` không đưa `knowledge` vào prompt nữa. **Lấy ngay**: `docs/NGON-NGU.md` — file thứ 10 của bộ khung, bảng *thuật ngữ · nghĩa · tránh* 18 mục (khuôn `CONTEXT.md` của họ), ra đời vì hai lần nhầm cùng ngày (K1.x hai cách đánh số; bảng đối chiếu ghi hàm/cờ không tồn tại). Bảy thứ đã kiểm và loại (Neo4j/POLE+O, similar-trace embedding, `error_kind` — chỉ một đường mở lại ticket, `:TOUCHED`, eval harness, buffered writes, TCK/OpenWiki). Thêm một "việc để lại" vào tự kiểm 2026-09-07: `supervisor.md:28` nói quá về bài học trong prompt. Không đổi một dòng mã nào
- docs: ADR-0003 (**được chấp nhận**) — đối chiếu `ruvnet/ruflo` @`277c7bc0`, đo trên bản clone chứ không đọc README (847k dòng TS, coverage CI **tắt** ở `v3/vitest.config.ts:44`). Sàng theo "có ích cho dự án này" còn đúng **một** thứ: nghi thức tự kiểm chống chính mình (mẫu là bản kiểm của họ tự bác bỏ README — "HNSW 150x–12.500x" đo được 1,48×, một số sinh bằng `Math.random()`). Sáu thứ **đã kiểm và loại** có lý do, hai trong đó bản nháp đầu định lấy nhầm rồi rơi khi đọc `blackboard.py` (event-sourced, đánh version) và 21 file agent (ADR-0012 đã bơm toàn văn artifact vào prompt). **Lấy luôn trong cùng PR**: gói việc thường trực "tự kiểm số liệu" ở `docs/TASK-PACK.md`, và **lần tự kiểm đầu tiên** `docs/reports/2026-09-07-tu-kiem.md` — 5/10 dòng số liệu `README.md` gốc lệch với đĩa (850→**1001**, 424→**469**, 206→**225** test bằng `pytest --collect-only`; console ADR 0001–0002→**0003**; xagents-core thiếu ADR gốc 0003), đều lệch một chiều "nói ít hơn thật" và đúng những dòng **không có test CI canh**; đã sửa README, ba test canh README chạy lại xanh. Không đổi một dòng mã nào
- docs: `AGENTS.md` luật bắt buộc **10** — dòng `CHANGELOG.md`, `docs/sessions/<ngày>.md` và số liệu `README.md` nằm trong CHÍNH PR làm ra thay đổi; số PR chỉ có sau khi tạo PR nên điền `(#<n>)` rồi commit tiếp vào chính PR đó, không mở PR khác để vá số; dòng CHANGELOG xếp theo thời điểm **merge**. Kèm phần thông tin còn thiếu của PR-3: dòng CHANGELOG của nó được điền `(#155)` và xếp lại đúng chỗ, nhật ký phiên ghi PR đã merge + xung đột rebase duy nhất (số ca/file test trong README) (#157)
- docs: nhật ký phiên `docs/sessions/2026-09-07.md` cho ADR-0037 PR-1 (#154) — luật bắt buộc 9 của `AGENTS.md`
- feat(company): ADR-0037 PR-3 — **skill theo pha**. Front matter agent nhận trường `phases:`; `skills`/`skills_core` cấp agent nạp ở **mọi** lượt, `phases.<tên>.skills(_core)` chỉ nạp khi lượt chạy khai đúng pha đó. Đây là điều kiện trước của việc gộp 21 agent thành 5: không có nó, một `product` gộp bảy vai sẽ mang skill của cả bảy vào mọi lượt (prompt loãng). Pha của một lượt do `orch/routes.py::phase_for` quyết: `Route(phase=…)` khai sẵn, hoặc — với route sửa code — lấy theo `stack` của ticket (`Task.stack`, trường mới, `tasks.json` cùng lúc; chưa khai thì tạm lấy `assignee`). Hai quy tắc trùng lặp: **cấm** trùng trong cùng một cấp (agent, hay một pha), **cho phép** trùng giữa hai cấp và **pha thắng** — skill pha nạp đầy đủ thì bản rút gọn cấp agent biến mất khỏi prompt, không gửi hai lần. Kiểm chủ quản ADR-0008 nay tính trên hợp cấp agent ∪ mọi pha (`AgentSpec.owned_skills`), còn `check_routes` bắt route khai pha agent không có — lệch pha thì lượt chạy bằng bộ skill của vai khác, nên nó phải vỡ lúc khởi động chứ không phải giữa một ticket. Runner: `generate/generate_in_workspace/author_tests/run_context` nhận `phase`, prompt hệ thống và `fit` đo trên đúng prompt của pha, khoá prompt cache đổi theo pha, audit ghi cột `phase` mới, và payload đầu ra mang `_phase` do **code** ghi (guard hạ nguồn phân biệt hai lượt cùng agent khác pha bằng trường này, không bằng `actor`). `assetscan budget` đo **theo từng pha** (`agent[pha]`) — đo gộp mọi pha vào một dòng là báo động giả vì không lượt nào nạp bằng ấy skill. **Không đổi agent nào**: 21 agent hiện tại không khai `phases`, prompt và bản dẫn xuất (`tests/golden/`, `.claude/agents/`) không đổi một byte, nên PR này không cần 7 bước `CONTRIBUTING.md` §3. Đo hai chiều 9 đột biến (bỏ nhánh pha trong `system_prompt`, bỏ "pha thắng", chủ quản chỉ tính cấp agent, `check_routes` bỏ kiểm pha, `phase_for` bỏ `stack`, prompt không nạp skill pha, payload không mang `_phase`, audit không ghi `phase`, assetscan đo gộp) — mỗi đột biến làm đỏ đúng ca đo nó. Đã chạy: company 992 test / coverage 100%, ruff + mypy sạch, `make subagents-check` khớp, `make golden` 88 xanh, `assetscan` 0 lỗi nặng (#155)
- fix(company): ADR-0037 PR-1 — `_check_plan` (`orch/ticket_fsm.py`) nhận thêm `project_id`, chặn đủ các khoá "Code
  gửi kèm" của gate plan cũ (kind `plan`) bằng code trước khi plan tới người duyệt: ticket > 1 ngày/200k token
  (`MAX_TICKET_TOKENS`), ticket chạm từ khoá nhạy cảm (`RISK_HINTS`: auth/login/password/payment/pii/…) mà thiếu
  `risk_tags`, thiếu threat model (`review-results` key `SPEC-<project>`), thiếu `architecture`/`api-contract` trên
  blackboard. Chuẩn bị để PR-2 bỏ hẳn `GateKind` `plan` mà không mất kiểm nào. Test hai chiều mới ở
  `tests/test_check_plan_adr0037.py` (9 ca, mỗi ca có chiều tắt kiểm qua monkeypatch); cập nhật vài test hiện có
  va chạm trực tiếp với luật mới (threat-model giờ chặn plan thật, ticket giả thiếu context_writes). (#154)
- docs(company): ADR-0037 — gộp 21 agent thành 5 (`product`, `builder`, `qa`, `security`, `ops`; `supervisor` là code), hai human gate công đoạn `spec` và `release`, bỏ `GateKind` `plan` (khoá của nó → `_check_plan` chặn bằng code); `acceptance` (chữ ký khách, ADR-0017) và `escalation` giữ nguyên, không đếm là gate công đoạn. Kèm `docs/DAC-TA-TRIEN-KHAI-ADR-0037.md`: đặc tả từng PR để agent thực thi (thứ tự 6 nhóm PR, front matter 5 agent đối chiếu 45 skill, bảng route đích, file/dòng đổi, test hai chiều, thân bài prompt, eval theo pha, `checklists.md` đích, schema). Ba bất biến code đang cưỡng chế được giữ: test ≠ code (`qa` hai route, hai tool), review ≠ security, khách ký nghiệm thu. **Không đổi dòng code nào** — ADR ở trạng thái Đề xuất; README ghi ADR 0001–0037 (test đếm từ đĩa) (#153)

- refactor(core): K3.3c1 kịch bản B — `Completion` và **đường bóc JSON** lên `xagents_core.llm`. Đây là chỗ hai công ty *mâu thuẫn thật* chứ không chỉ trôi khỏi nhau (`difflib` 0.23, thấp nhất trong 22 symbol), nên PR này là một **quyết định hợp nhất** chứ không phải chuyển mã: company bóc fence bao ngoài rồi đòi JSON đứng ngay từ ký tự đầu — hỏng giữa cấu trúc thì ĐỎ, cố ý, vì cứu chỗ đó là đoán ý model và đoán sai thì ticket đi tiếp với một nửa dữ liệu; studio thì đi TÌM object trong văn xuôi, cứu được lượt model kể chuyện trước rồi mới trả JSON (hay gặp sau khi model chạy tool). Bản hợp nhất giữ **cả hai** bằng một điều kiện: *có văn xuôi đứng trước thì đi tìm; đầu ra tự nhận là JSON ngay từ ký tự đầu mà hỏng thì vẫn đỏ như cũ*. Bốn đường theo thứ tự: bóc fence + `json.loads` → object hoàn chỉnh thừa dấu đóng (bản company) → tìm trong văn xuôi (bản studio, chỉ khi không bắt đầu bằng JSON) → `LLMError` kèm trích đoạn quanh vị trí lỗi. **Bằng chứng đúng loại mà đặc tả đòi**: `evals ... --replay --strict` chạy trên bản trước và bản sau, hai công ty, danh sách PASS/FAIL **giống hệt từng dòng** — hợp nhất không đổi cách đọc bất kỳ đầu ra model đã ghi nào. Studio nhận thêm `cache_write_tokens` và `tool_mode` (mặc định 0 / `""`, mọi `Completion(...)` cũ vẫn dựng được). **Một ImportError im lặng suýt lọt**: `runner._co_ve_la_json` nhập `_strip_code_fence` *bên trong hàm*, nên xoá tên đó không làm ai đỏ lúc import — 73 test hỏng với triệu chứng hoàn toàn khác (đường ống dừng sai chỗ), không test nào chỉ vào cái tên vừa mất; nay helper là tên công khai (`strip_code_fence`) và được re-export ở cả hai package. Đo hai chiều 5 đột biến (bỏ điều kiện văn-xuôi, bỏ hẳn đường studio, bỏ đường company, cắt fence nằm giữa, bỏ trường mới) — mỗi cái đỏ đúng phần nó đo. Đã chạy: core 109 test / 100%; company 980 / 100%; studio 464 + 5 skip / 100%; console 232, không sửa một dòng

- refactor(core): K3.3b kịch bản B — `LLMConfig` và `load_config` lên `xagents_core.llm`; hai công ty nay là **lớp con** của khung chung. Đây là bước b của K3.3 (a đã tách theo mức rủi ro ở #150): phần này là chỗ hai bản chỉ khác nhau ở *tên biến môi trường* và *tập trường phụ*, chưa đụng tới bốn adapter và `Completion.json()` — nơi hai thuật toán thật sự khác nhau. **`difflib` chấm `LLMConfig` 0.56 chủ yếu vì kích thước**: bỏ 14 trường company có mà studio không (CLI/MCP theo ADR-0023/0024, retry ADR-0012, giá, ngân sách, nợ kiến trúc ADR-0032, sandbox ADR-0035) thì phần còn lại trùng gần nguyên văn, kể cả thứ tự dòng trong `backend_config`. **Kế thừa chứ không tham số hoá bằng cờ**: 14 trường ấy là DỮ LIỆU có kiểu, nhét vào một `dict[str, Any]` chung ở core là đổi 14 trường có kiểu lấy một túi `Any` — mất đúng thứ `strict` của core sinh ra để giữ; nên core giữ khung + khoá dùng chung, mỗi công ty ghi đè ba móc (`apply_backend_yaml`, `apply_yaml`, `apply_env`). Studio sau PR này **không còn trường riêng nào** và có test bánh cóc canh đúng điều đó. Kèm theo là `company/core.py` và `studio/core.py` — `CORE` đầu tiên của hai công ty, nguồn DUY NHẤT của (`prefix`, `root`, `db_name`) mà K3.4–K3.7 sẽ dựng lên trên; `llm.ROOT`/`llm.CONFIG_FILE` nay đọc từ đó thay vì tự dựng lại từ `__file__`. **Ba quyết định nhỏ đáng nhớ**: (1) `PREFIX` là `ClassVar` chứ không phải trường — `backend_config` sao chép `__dict__` xuống từng backend, và một `LLMConfig()` dựng tay trong test vẫn phải báo đúng `COMPANY_MODEL_STRONG` chứ không phải chuỗi rỗng; (2) `type(self)` trong `backend_config` — trả `LLMConfig` trần thì mọi trường riêng của company biến mất **ngay khi** cấu hình có `backends:`, im lặng, chỉ lộ ra khi backend đầu hết quota; (3) bộ lọc `<PREFIX>_LLM_BACKENDS` tách thành `select_backends` gọi SAU `apply_env` vì `LLM_PROVIDER` xoá sạch `backends` — thứ tự ở đây là hành vi, không phải khẩu vị, và có test riêng. `types-PyYAML` vào nhóm dev của core (bốn package kia chạy mypy với `--ignore-missing-imports` nên `yaml` im lặng thành `Any`; core cố ý không có cờ đó). Đo hai chiều 5 đột biến (bỏ `type(self)`, đọc `max_input_chars` ở cấp backend, đảo thứ tự `select_backends`, `PREFIX` rỗng, studio mọc lại một trường) — mỗi đột biến làm đỏ đúng một ca. Đã chạy: core 88 test / 100%; company 980 / 100%; studio 464+5 skip / 100%; console 232, không sửa một dòng (#151)

- refactor(core): K3.3a kịch bản B — **nền** của lớp LLM sang `xagents_core.llm`. **Đặc tả K3.3 sai giả định, đo lại mới thấy**: nó viết "gốc là `company/llm.py` (1.128 dòng), tham số hoá 8 điểm rồi studio thành shim", nhưng `difflib` trên từng symbol cho thấy hai bản đã trôi xa nhau — chỉ **6/22 symbol cùng tên trùng gần nguyên văn**; ba lớp nặng nhất lệch hẳn (`ClaudeCodeClient` 0.32, `OpenAICompatClient` 0.28, `Completion` 0.23 — **hai thuật toán bóc JSON khác nhau**, `LLMConfig` 0.56). Gộp trong một PR là đổi cách studio đọc mọi đầu ra model + đổi cấu hình + đổi bốn adapter cùng lúc, không có cách nào đọc diff đó mà biết chắc studio còn chạy. Nên K3.3 **tách theo mức rủi ro**: bước a là phần trùng thật và không đổi hành vi bên nào (lỗi `LLMError`/`Refused`/`TransientError`, `TIERS`, `TRANSIENT_HTTP`, `neutral_messages`, `strict_schema`, `reported_model`, `system_prompt_args`, `cli_effort_args`, `find_codex_binary`, hằng CLI); phần đã rẽ nhánh đi các PR sau, mỗi PR một quyết định hợp nhất nói rõ bên nào được nâng. **`reported_model` là hàm hợp nhất thật — chỗ duy nhất không bên nào là gốc**: `canonicalModel` là của studio (company thiếu nên model được CLI quy đổi alias bị coi là không khớp), còn fallback "khoá tiêu nhiều output token nhất" là của company (studio thiếu nên trả chuỗi RỖNG, và rỗng đi thẳng vào audit như thể CLI không báo model nào). Studio còn được nâng ba thứ tương thích ngược: `LLMError.status` (mặc định `None`), `TransientError` (chưa ai ném — điều kiện trước cho bước cho studio hoãn event thay vì dừng), và **xoá bản `SECRET_ENV` thứ ba** (K3.2 đã ghi nhận, nay đúng phạm vi). **Một test suýt vô dụng**: ca `canonicalModel` ban đầu vẫn xanh khi xoá chính nhánh nó đo, vì fallback vô tình trả cùng khoá — chỉ phép đo hai chiều lộ ra; đã thêm khoá thứ hai tiêu nhiều token hơn để ca đó thật sự phân biệt. mypy `strict` của core lại bắt một chỗ mypy lỏng của company bỏ qua (`strict_schema` trả `Any`). Đã chạy: core 73 test / 100%; company 976; studio 466 / 100%; console 230, không sửa một dòng

- refactor(core): K3.2 kịch bản B — `sandbox.py` và **khung** `ToolBox` sang `xagents_core`. Studio từng mang một bản sao 216 dòng của `company/sandbox.py` dán nhãn "bản tạm, xoá ở K3.2"; bản sao đó nay không còn, `RunSpec` ở core là **hợp** của nhu cầu hai bên (`network`+`port` cho `company.smoke`, `stdin` cho `studio.media.CommandTTS`, `read_only` cho `studio.qc`). `SECRET_ENV`/`clean_env` theo về core cùng sandbox — sandbox là chỗ CUỐI CÙNG env đi qua, nên danh sách chặn phải ở đó chứ không ở một trong các nơi gọi; `company/workspace.py` nay re-export chúng. **Chọn backend KHÔNG lên core**: `sandbox_from_settings(mode, runtime, image, env_var)` nhận giá trị đã đọc sẵn, còn `sandbox_from_config` ở lại mỗi bên vì ba thứ khác nhau thật — biến (`COMPANY_SANDBOX*` vs `STUDIO_SANDBOX*`), nguồn (`cfg.sandbox` vs `media.yaml render.sandbox`) và **mặc định** (`auto` vs `subprocess`, studio cố ý không auto vì ffmpeg nhận đường dẫn trải nhiều thư mục mà container chỉ thấy `cwd`). Đưa chúng vào core là đưa một câu `if prefix == …` vào lõi. **Một chỗ suýt đổi hành vi âm thầm**: khung company cắt đầu ra tool ở 6.000 ký tự, khung studio không cắt gì (`web_fetch` tự cắt ở 20.000 sau khi bóc HTML) — gộp khung mà lấy mặc định của company thì studio lặng lẽ mất 14.000 ký tự cuối mỗi trang, **không có lỗi nào nổi lên và 45 test tool cũ vẫn xanh**; nay `max_output` là tham số, studio khai `None` tường minh, và có test canh đúng chỗ đó (bỏ khai báo → chỉ ca mới đỏ). Test đơn vị đi theo mã: 13 ca hợp đồng sandbox chuyển sang `platform/xagents-core/tests/`, phần đo điểm gọi thật (media của studio, workspace/smoke của company) ở lại vì đó là test tích hợp. Thêm `test_shim_core.py` cho studio (trước chỉ company có) và khuôn bất biến thứ hai `SHIM_CO_CAU_HINH`: shim được phép mang hàm đọc cấu hình, **không** được phép mọc lại `class`/`@dataclass`. Core: 45 test, coverage 100%, mypy `strict` sạch; company 976 + studio 465 + console 230 test xanh, console không sửa một dòng

- feat(studio): K3.1b kịch bản B — studio dùng `fit` của `xagents_core.context`, đóng "nghiệm thu riêng" của K3.1. Đây là **đổi hành vi có chủ ý** theo nguyên tắc 1 của ADR gốc 0001 (company là gốc, studio được nâng): trước bản này studio **không có trần đầu vào nào** — `build_user_message` nối thẳng payload + dữ liệu enrich + toàn bộ blackboard, trần duy nhất là `max_tokens` (đầu **ra**) và `budget_tokens_per_task`, nên một kịch bản dài chỉ hỏng ở phía provider giữa phiên chạy thật. Nay `LLMConfig.max_input_chars` (mặc định 120k, khoá `llm.yaml`, biến `STUDIO_MAX_INPUT_CHARS`), `make_client` gắn lên client, `AgentRunner` đọc và cắt trước khi dựng prompt, kèm audit `context_trimmed`. **Hai quyết định thiết kế đáng ghi**: (1) `payload` và `extra` đi **chung một hạn mức** thay vì mỗi cái một trần — cả hai đều vào cùng một prompt, cắt riêng thì tổng vẫn vượt; (2) `max_input_chars` cố ý **không** nằm trong `_apply_yaml`, nên một phần tử `backends:` không ghi đè được — trần prompt là thuộc tính của cả hệ, để backend tự đặt thì cùng một agent bị cắt khác nhau tuỳ tài khoản nào còn hạn mức (giống `company/llm.py`). **Phần cố ý chưa làm, không phải bỏ sót**: `studio.events.SharedContext` chưa có trường `content` và `Blackboard` chưa có `path()`, nên phần blackboard hiện chỉ được đo chứ chưa bị cắt và nhãn "đọc đầy đủ ở …" chưa trỏ artifact — đó là đổi mô hình dữ liệu, thuộc bước sau. Trần riêng theo agent (kiểu ADR-0020 của company) cũng để lại: chưa có số đo nào nói 14 agent studio cần trần khác nhau. Test hai chiều: bỏ lời gọi `fit` và bỏ dòng gắn client → 3/7 ca đỏ (prompt về lại 200.661 ký tự nguyên vẹn, không có audit `context_trimmed`); bật lại → 7 xanh, cả bộ 475 ca, coverage 100%

- refactor(core): K3.1 kịch bản B — `context.py` (cửa sổ ngữ cảnh có hạn mức, ADR-0012) sang `xagents_core`; `company.context` còn lại là shim 2 dòng, 28 file test không đổi một dòng import. Test đơn vị chuyển theo mã sang `platform/xagents-core/tests/test_context.py` (bất biến 2), phần tích hợp ở lại company. **Hai thứ đặc tả không lường, đều tìm ra bằng cách chạy lệnh CI thật**: (1) thiếu **`py.typed`** thì mypy coi cả `xagents_core` là untyped → shim `import *` mang sang **0 tên** → `company/runner.py` gọi `fit` báo `Module "company.context" has no attribute "fit"`; nghĩa là `strict = true` của core chỉ bảo vệ chính core chứ không bảo vệ ai gọi nó — đã thêm marker + ép vào wheel + test canh, vì mất nó là mất kiểm kiểu **trong im lặng** cho cả hai công ty ở mọi bước K3 sau. (2) mypy `strict` bắt **3 chỗ `tuple` trần** trong `context.py` mà mypy lỏng của company bỏ qua nhiều tháng. Thêm `tests/test_shim_core.py` canh bất biến 1 (shim giữ đủ tên public, cùng đối tượng, và **không mang logic** — một dòng logic trong shim là bản fork thứ hai mọc lại). **Chưa làm, tách PR riêng:** studio dùng `fit` — studio không có `max_input_chars` nào cả, nên đó là thêm cấu hình + đổi hành vi chứ không phải chuyển mã

- docs: ADR gốc **0001 — lõi chung `xagents-core`** (điều kiện trước của K3 kịch bản B). Đo lại thực trạng thay vì chép số đặc tả: **1.707 dòng trùng nguyên văn** trên 14 module giữa `company` và `studio` (đặc tả ước ~1.200), **0 import chéo**, và chỗ nguy hơn phần trùng là phần company có mà studio **không có** — `context.py` (126 dòng) và `guard.py` (146 dòng) chưa từng sang studio, nên `LLMError` giữa chừng vẫn **dừng** orchestrator studio trong khi company đã chuyển sang hoãn event từ lâu. Quyết định: package thứ năm, company là gốc — studio được nâng (kể cả khi đổi hành vi, ghi rõ), `CoreConfig` tham số hoá thay cho `if prefix == …`, shim giữ mọi tên cũ để **console và gateway không sửa một dòng**, bảy bước mỗi bước một PR, `strict = true` + `fail_under = 100` ở core từ ngày đầu (K6.1) (#143)
- fix(company): K1.5 kịch bản B — `smoke.unverified` không còn là trạng thái trung lập. Spec `kind=application` (mặc định khi thiếu `kind`) mà orchestrator không smoke được (thiếu `runtime`, thiếu worktree tích hợp) → RC `status=failed` + mở gate `escalation`, đúng đường của smoke fail; `library`/`docs`, hoặc dự án khai cờ mới `legacy: true` trong `research-requests.payload`, vẫn đi tiếp với bằng chứng nói thẳng là chưa kiểm. **Bảng theo dõi trước đó ghi nhầm K1.5 là "xong (từ trước)"**: nó dẫn `verify.py:109-111` làm bằng chứng, nhưng đó là `verdict_with_run` (đường QA hồi quy) chứ không phải `smoke()` (đường deploy staging), và cờ `legacy` chưa từng tồn tại. Lý do chặn SỚM một chặng thay vì để QA hồi quy chặn như ADR-0029 mục 3: `Delivery.waive_release_findings` waive **mọi** nguồn chưa `pass` kể cả `qa`, nên người duyệt gate escalation — cơ chế dành cho finding không có code để sửa (DPIA, license) — waive luôn cả "chưa bao giờ kiểm sản phẩm có chạy không", Gate 3 mở, RC lên production; RC `failed` thì không có route đi tiếp nên waive không cứu được. ADR-0036 ghi lại quyết định và ghi rõ phần CHƯA sửa (waive vẫn theo nguồn, không theo từng finding). Test hai chiều, và ca ADR-0029 cũ được giữ nguyên vùng phủ qua đường `legacy`
- build(core): K3.0 kịch bản B — khung package thứ năm **`xagents-core`** (ADR gốc 0001): `CoreConfig`/`TopicACL` (chỗ DUY NHẤT core biết một công ty khác công ty kia ở đâu — thêm điểm khác biệt là thêm một *trường*, không thêm một câu `if`), hai job CI `core-static`/`core-unit` nối vào `quality.needs`, workspace + `Makefile` lên **năm** member, và `xagents-core` đã là phụ thuộc khai báo của cả hai công ty (chưa import dòng nào) để K3.1 là một bước chuyển mã thuần. Gồm luôn **K6.1**: `strict = true` từ commit đầu tiên của package — core chưa có mã nên đây là lần duy nhất bật `strict` mà không phải trả nợ chú kiểu; `types` của core cố ý **không** có `--ignore-missing-imports` (strict mà bỏ qua import thiếu là mất đúng phần vừa bật). Sáu test canh hợp đồng ADR-0001, không canh tính năng: đường dẫn suy từ `root` chứ không từ `__file__` của core (core biết mình nằm đâu so với công ty là buộc chặt vào bố cục repo), tên biến môi trường đi qua một chỗ, cấu hình bất biến, mặc định rỗng chứ không `None`, và mỗi `CoreConfig` có `TopicACL` riêng (console nhập cả hai công ty trong một tiến trình). **Ruleset không phải sửa** — required check chỉ có `quality` + `metadata` nên nối vào `needs` là đủ; đặc tả để ngỏ điều này
- docs(git): `docs/QUY-TRINH-GIT.md` §2c — **chỉ một PR mở tại một thời điểm**, và rebase `origin/main` lên nhánh mình ngay trước khi tạo PR. Nhiều phiên song song mở PR cùng lúc thì mỗi PR lệch `main` một hướng rồi đá conflict vào nhau khi merge lần lượt; kiểm `gh pr list --state open` trước là rẻ hơn gỡ conflict sau. Tóm tắt vào "sáu điều" của `CLAUDE.md` (#147)
- refactor(console): K7.1/K7.2/K7.5 kịch bản B — `index.html` 1850 → 759 dòng, khối `<script>` 1090 dòng tách thành **14 ES module** trong `static/js/` (dài nhất 173 dòng, không build step, không CDN). Bootstrap vẫn inline nhưng có **nonce** và trang nay gửi **Content-Security-Policy** chặn mọi script inline khác (chọn phương án nonce thay vì `GET /api/boot` để không đưa token phiên vào query string). `tests/test_es_module.py` canh bốn thứ dễ hỏng im lặng: đủ module, không module nào > 400 dòng, `main.js` nhập ĐỦ (kể cả nhập rỗng cho side-effect), và không module nào gán vào binding nhập từ module khác (#142)
- chore(company): K6.2/K6.3 kịch bản B — mypy siết `company.orch.*` (`disallow_untyped_defs` + `disallow_incomplete_defs`, khoá theo tiền tố nên module mới tự nằm trong phạm vi); 46 hàm nhận `o` trong `gates_flow`/`release_fsm`/`scheduler`/`ticket_fsm` nay có `o: Orchestrator`. `tests/test_ranh_gioi_kieu.py` chốt ba mặt: ba kiểu ở ranh giới còn là dataclass, mọi hàm nhận `o` có chú kiểu, cấu hình mypy còn nguyên. **Tiêu chí K6.3 vế 2 đổi có ghi lý do**: đích "`dict[str, Any]` trong orch/ ≤ 14" ép kiểu hoá payload bus — chép 19 schema sang hệ kiểu, tạo nguồn sự thật thứ hai; thay bằng chốt bánh cóc (trần 25, chỉ giảm). `warn_unused_ignores` cố ý không bật: `ctypes.windll` thừa trên Windows mà cần trên Linux (#141)
- docs: K8.5 kịch bản B — `docs/HUONG-DAN-VAN-HANH.md` §0 "Ngày đầu của người thứ hai": 6 bước, ~30 phút, provider giả (không API key, không tốn hạn mức), kết thúc bằng chính người mới **ký một gate** bằng `gate_cli`. Mọi lệnh đã chạy thật trước khi viết, kèm output thật. Bước 4 cố ý để `FakeClient` hết câu trả lời: phản ứng của hệ (pause dự án + mở gate `escalation`) dạy "máy làm được thì làm, không làm được thì hỏi" tốt hơn một đường chạy trơn. Là kịch bản của K9.3 (#140)
- chore(gateway): K8.2 kịch bản B — `make llm` của hai công ty từ chối cài hồ sơ `claude-gateway` khi máy chưa đăng nhập tài khoản Antigravity nào, gác bằng lệnh mới `python -m gateway ready` (exit 2 + đúng lệnh phải gõ + trỏ tới §Rủi ro tài khoản). Trước đó `make llm` chép file vô điều kiện, dựng sẵn một cấu hình trỏ `base_url` vào daemon chưa có tài khoản — hỏng MUỘN ở lượt gọi model đầu tiên giữa phiên chạy thật. `ready` không đòi daemon đang chạy: cài và chạy là hai bước (#139)
- fix(gateway): K8.6 kịch bản B — `stop` kiểm dòng lệnh trước khi giết trên CẢ BA nền (`/proc` Linux, `ps -o command=` macOS/BSD, `tasklist` Windows). Trước đó `_pid_is_gateway` trả `True` cho mọi hệ không phải Linux, nghĩa là `stop` giết bất kỳ PID nào trong PID file — kể cả PID đã bị hệ điều hành tái dùng cho tiến trình khác (Windows tái dùng PID nhanh hơn Linux nhiều). Ba giá trị trả về phân biệt rõ: không đọc được → giữ hành vi cũ, không tồn tại → không giết. Không thêm phụ thuộc (#138)
- docs(gateway): K8.1 kịch bản B — `platform/gateway/README.md` §**Rủi ro tài khoản** đặt ngay dưới khối `make login` (nhà cung cấp thường cấm nhiều tài khoản để vượt hạn mức; hậu quả nặng nhất là **khoá tài khoản Google** chứ không phải bị chặn request; trách nhiệm thuộc người vận hành) + `platform/gateway/docs/adr/0004-ranh-gioi-dieu-khoan.md` ghi vì sao repo cố ý KHÔNG cảnh báo lúc chạy và không đặt trần số tài khoản; dòng gateway ở README gốc dẫn thẳng tới mục đó (#137)
- test(console): K7.4 kịch bản B — `tests/test_hop_dong_schema.py` canh hợp đồng giữa console và `topics/schemas/` của hai công ty: quét `collect.py`/`truth.py` lấy 30 tên trường console đọc rồi khẳng định từng tên có trong schema; trường lồng một tầng (`local_checks.sandbox`, `smoke.sandbox`) canh riêng. Trước đó đổi tên một trường bên công ty thì test công ty vẫn xanh còn console vỡ ÂM THẦM — ô hiện rỗng chứ không báo lỗi. Kèm ghi nhận **hoãn có chủ ý K7.3** (danh tính người duyệt) với điều kiện kích hoạt lại rõ ràng (#136)
- docs: nhật ký phiên 2026-09-07 (K2.7 #133, K5 #134) + `TRAPS.md` §3 thêm bẫy **PR không có check nào chạy** — `mergeStateStatus=DIRTY` thì GitHub không tạo check run, kiểm nó trước khi nghi Actions hỏng
- feat(console): K2.7 kịch bản B (đóng K2) — ô trực ban cảnh báo lệnh của khách chạy ngoài container: `truth.sandbox()` đếm lượt trong 24h theo tên sandbox từ ba chỗ code điền bằng chứng (`local_checks.sandbox`, `smoke.sandbox`, audit `tools_used`), `sources.<công ty>.sandbox_available` nói máy có docker/podman không. Ô chỉ sáng khi CẢ HAI đúng, và nói thẳng lệnh cần gõ. Kèm nốt nửa còn lại của K2.8: `companies/software-company/README.md` mục "Chưa có" không còn nói sandbox chỉ là allowlist + env (#133)
- ci: K5 kịch bản B — `eval-record` chạy được từ GitHub Actions: workflow `workflow_dispatch` (package/agents/provider/jobs, `timeout-minutes: 45`, key từ Secrets, tên model từ Variables) ghi bản ghi bằng model thật rồi **mở PR** `chore(<package>): ghi lại eval <agents>` nhãn `no-changelog` — không push thẳng `main`. `--jobs N` ở cả `company.evals` lẫn `studio.evals` (chạy song song theo agent; thứ tự IN vẫn theo id để log so được giữa hai lần chạy), bảng điểm vào `$GITHUB_STEP_SUMMARY` (cổng vẫn chỉ là `gate_ok`, điểm chấm không làm CI đỏ). `CONTRIBUTING.md` §3 bước 3 nay ghi hai đường: máy cá nhân hoặc workflow — trước đó ghi lại eval là cửa hẹp một người có API key (#134)
- docs: nhật ký phiên 2026-09-07 (K2.4/K2.5+K2.8, K8.3/K8.4, K1.8 — #129–#131) + `TRAPS.md` §2 thêm bẫy **tiêu chí nghiệm thu cũng có thể là proxy sai**
- refactor(company): K1.8 kịch bản B (đóng K1) — `main` 162 → 29 dòng: 13 subcommand tách sang `orch/cli_cmds.py` với hai bảng dispatch `BUS_CMDS`/`ORCH_CMDS` (ranh giới là chỗ dựng `Orchestrator`, nên `metrics`/`trace`/`publish` không đòi SDK). **Tiêu chí K1.8 đổi có ghi lý do**: bỏ mốc `wc -l orchestrator.py ≤ 300` (đo được 250/498 dòng là import + re-export + bảng gán method — chính bề mặt shim K1.7/K1.1 cố ý tạo, và K1.7 yêu cầu `_call`/`process` ở lại nên hai tiêu chí mâu thuẫn nhau), thay bằng **thân hàm ≤ 260** (nay 245) — đo phần thật sự khó đọc. Bốn test chốt, hai chiều (#131)
- ci: K8.3/K8.4 kịch bản B — cổng `metadata` thêm hai bước: PR `fix(` chạm `companies/software-company/src/company/orchestrator.py` hoặc `orch/` mà thân không dẫn `ADR-0034` thì **đỏ** (đặc tả viết "ADR-0037" nhưng repo không có file đó; ADR tách máy trạng thái là 0034, chính nó đã ghi lại chỗ lệch số); thiếu `docs/sessions/<ngày UTC>.md` thì **cảnh báo**, không chặn merge. `docs/QUY-TRINH-GIT.md` §5 liệt kê đủ bốn bước của cổng `metadata` (#130)
- feat(company): K2.4/K2.5 kịch bản B (phần company, đóng luôn K2.8) — ba điểm chạy mã của khách đi qua `Sandbox` (ADR-0035): tool `run` của model (`tools.WorkspaceTools.run`), lint/test của `run_checks` (`TicketWorkspace._run`), lệnh khởi động smoke (`smoke.run_smoke`, `network=True` + cổng loopback vì nó phải trả lời được HTTP). Sandbox đi THEO worktree (`TicketWorkspace.sandbox`) nên `runner.py` không đổi dòng nào; `Orchestrator(sandbox=…)` mặc định `SubprocessSandbox` (hành vi cũ) và chỉ `run`/`redeploy` trong CLI mới đọc `sandbox_from_config` — `auto` chọn container ngay khi máy có docker, mà CI ubuntu có. Bằng chứng ghi lớp bảo vệ đã dùng: `pull-requests.local_checks.sandbox`, `release-events.smoke.sandbox` (hai schema đã khai trường), `ToolBox.sandbox` trong audit `tools_used`. `SECURITY.md` viết lại mục sandbox kèm ba giới hạn còn lại. Test quy ước grep `subprocess.run|Popen` toàn `src/company/` chặn PR sau lỡ thêm lệnh mới; ngoại lệ có lý do là `git` và CLI model (`claude`/`codex`) (#129)
- docs: nhật ký phiên 2026-09-07 (mục K1.4) + `TRAPS.md` §2 thêm bẫy **tin test canh quy ước kiểu grep** — mẫu của test khuôn 3 bỏ sót `once_key=` suốt hai PR vì `"once_key="` không chứa chuỗi con `"once="`
- fix(company): K1.4 kịch bản B (đóng K1.4) — ba khoá `once` còn thiếu thế hệ được thêm: `gate.escalate:{sid}` → `:{created_at của GateRequest}` (và `gate:{sid}:{pha}` cùng họ), `smoke.unverified:{rid}` → `:{rc.event_id}`, `delivery.skipped:{rid}` → `:{env.event_id}`. Mẫu kiểm khuôn 3 (`tests/test_orch_khuon_loi.py`) từng bỏ sót `once_key=` vì `"once_key="` không chứa chuỗi con `"once="` — `gate.escalate:{sid}` sống sót nhờ lỗ đó; mẫu mở rộng, `KHOA_MIEN` bỏ `delivery.skipped`/`smoke.unverified`. Ba test hai chiều mới (bỏ thế hệ → 4 test đỏ, khôi phục → 10 xanh; toàn bộ 927 pass/1 skip) (#127)
- docs: đối chiếu bảng theo dõi kịch bản B (`docs/DAC-TA-KICH-BAN-B.md` §6, `docs/DAC-TA-TRIEN-KHAI-KICH-BAN-B.md`) với 12 PR đã merge (#114–#125) — sửa nhầm lẫn giữa hai cách đánh số K1.x/K2.x (tiêu chí nghiệm thu ≠ PR-theo-PR); bổ sung số PR còn thiếu trong CHANGELOG; ghi rõ phần dở của K1 (3 khoá `once` thiếu thế hệ, đích dòng K1.8 chưa đạt) và K2 (K2.4/K2.5 phần company chưa nối Sandbox); nhật ký phiên 2026-09-07
- refactor(company): K1.7 kịch bản B (phần 2, đóng K1) — `orch/fsm.py` (`Transition`/`step()`) + `TICKET_TRANSITIONS`/`RELEASE_TRANSITIONS` làm bảng dữ liệu điều khiển `process()` (rút thành dispatcher thuần: bảng ticket → bảng release pre → `ROUTES` → bảng release post); `tests/test_orch_bang_chuyen.py` (9 ca) + `tests/test_orch_khuon_loi.py` (7 ca, 5 khuôn TRAPS.md §1 + chốt kích thước module). Phát hiện và sửa bug thật khi viết test khuôn 3: `once=f"no-test-author:{tid}"` thiếu thế hệ (bẫy đã ghi từ đặc tả K1.2, chưa ai sửa) — thêm `:{retry}`. `orchestrator.py` 957 → 491 dòng; mọi module `orch/` ≤ 400 dòng (có test chốt) nhưng CHƯA đạt đích ≤ 300 của chính `orchestrator.py` (còn `_call`/`__init__`/`status` ngoài phạm vi mọi PR K1.x đã duyệt) (#125)
- refactor(company): K1.7 kịch bản B (một phần, LỆCH ĐẶC TẢ có ghi chú) — tách `orch/ticket_fsm.py` và `orch/release_fsm.py` khỏi `orchestrator.py` (957 → 567 dòng); đây là di chuyển thuần, KHÔNG dựng bảng `TICKET_TRANSITIONS`/`RELEASE_TRANSITIONS` như đặc tả K1.7 mô tả (việc đó là thiết kế test-first, để phiên sau làm riêng, không rush) — `orchestrator.py` CHƯA đạt đích ≤ 300 dòng của K1 (#124)
- refactor(company): K1.6 kịch bản B — tách `orch/gates_flow.py` (quyết định gate: `_on_gate_decide`/`_check_escalations`/`_check_debt`/`_on_escalation_decided`/`_open|_close_acceptance_gate`, lỗi agent không nhánh nào nhận: `_stall`/`_after_error`/`_rework_after_error`/`_retry_stalled`/`_retry_unhandled`, và `_record_lessons`) khỏi `orchestrator.py` (1221 → 957 dòng); `_evidence` nhập lười cùng khuôn K1.5 (#123)
- fix(company): `generate_in_workspace` chấp nhận `no_changes_reason` (>= 20 ký tự, cùng tinh thần `test_dispute` ADR-0028) khi worktree không đổi nhưng việc đã xong thật từ lượt trước — không còn tự động invalid_output rồi blocked (TCK-CR-RUNTIME-01) (#121)
- refactor(company): K1.5 kịch bản B — tách `orch/scheduler.py` (vòng lặp chính: `run`/`tick`/`watch`/`_take_batch`/`_defer`/`_retry_deferred`/`_mark`/`_remember`/`_audit`…) khỏi `orchestrator.py` (1402 → 1221 dòng); `ReloadRequested`/`StepResult` nhập lười trong hàm để tránh vòng lặp import với `orchestrator.py` (#122)
- feat(studio): K2.3 kịch bản B — `studio/sandbox.py` (bản tạm, xoá ở K3.2 khi vào `xagents-core`); `CommandTTS`, `FFmpegAssembler._run`, `qc._run` chạy qua `Sandbox` thay vì `subprocess` trực tiếp; env lệnh con lọc khoá bằng `clean_env`/`sanitize_env`; ffmpeg có trần thời gian (`media.yaml render.timeout_s`, mặc định 600 s); qc mount chỉ đọc; audit `render.*` ghi tên sandbox đã dùng (#119)
- refactor(company): K1.4 kịch bản B — tách `orch/worktree_flow.py` (`_learn_repo`, `integration_for`, `workspace`, `_integrate_approved`, `_branch_ahead`, `_merge_ticket(_locked)`, `_read_only_tools`, `_author_tests`, `_engineer`, `comment`, `takeover`) khỏi `orchestrator.py` (1600 → 1402 dòng); lời gọi nội bộ giữa các hàm đi qua `o.<tên method>` để monkeypatch trên instance vẫn ăn (cùng khuôn K1.2) (#120)
- feat(company): K2.1 kịch bản B — ADR-0035 sandbox tiến trình; module `company/sandbox.py` (`RunSpec`/`Result`/`Handle`/`Sandbox`, `SubprocessSandbox` giữ nguyên hành vi cũ, `ContainerSandbox` docker/podman `--network none`), `sandbox_from_config` fail-closed, ba trường cấu hình `sandbox*` + ba biến `COMPANY_SANDBOX*`. Chưa nối vào tools/workspace/smoke (K2.2) (#116)
- refactor(company): K1 kịch bản B (tiếp) — `OrchState` gom 24 biến trạng thái RAM của orchestrator vào một dataclass (`orch/state.py`), bí danh property giữ nguyên bề mặt `o.<tên>` nên không file test nào phải đổi; mỗi trường khai nguồn dựng lại trong metadata và `tests/test_orch_state_rehydrate.py` duyệt `fields(OrchState)` — thêm trạng thái mà quên dòng rehydrate là CI đỏ ngay, không chờ một phiên chạy thật phát hiện hộ (#117)
- feat(company): kiến trúc phải bắt đầu bằng ước lượng tải nháp (DAU→QPS→đỉnh→lưu trữ→cache→số máy, mốc độ trễ vật lý, bảng sẵn sàng→thời gian chết) và kết thúc bằng mục "Hạn chế đã biết" có mã nợ + ngưỡng số; PRD thêm §6b bảng ước lượng và cột điều kiện đo; `docs/design-catalog.md` chỉ mục 14 bài toán hạ tầng thường gặp (#118)
- refactor(company): K1 kịch bản B (một phần) — ADR-0034 tách máy trạng thái; `orchestrator.py` 2269→1600 dòng, bốn module mới `orch/{routes,verify,cli,rehydrate}.py` không đổi hành vi. Phần rủi ro cao hơn (`worktree_flow`, `scheduler`, `gates_flow`, `ticket_fsm`/`release_fsm`, `OrchState`) để lại phiên sau (#115)
- chore: K0 kịch bản B — vệ sinh số liệu trôi (agent/ADR/test) giữa README gốc và đĩa, sửa cổng gateway mặc định trong `.env.example` (8100 → 1123), thêm `docs/adr/README.md` cho ADR cấp repo, test `platform/console/tests/test_readme_goc.py` canh README gốc khớp `companies/software-company/agents/` và `docs/adr/` (#114)
- docs: đặc tả kịch bản B (`docs/DAC-TA-KICH-BAN-B.md`, 9 epic K0–K9, thước đo T1–T4) và đặc tả triển khai PR theo PR (`docs/DAC-TA-TRIEN-KHAI-KICH-BAN-B.md`, 31 PR, file:dòng)
- docs: đánh giá sâu và tầm nhìn phát triển 09/2026 — bảy vấn đề cấu trúc ngoài đặc tả, ba kịch bản, ba chân trời, bốn quyết định phải ký (`docs/DANH-GIA-VA-TAM-NHIN-2026-09.md`)
- docs: đặc tả nâng cấp tháng 9 ghi rõ thứ tự đã bị kịch bản B đặt lại (E1→K1, D2→K2, S1 sau K3, C9 sau K7, E2 hoãn)
- docs: nhật ký phiên 2026-09-06 (đặc tả nâng cấp + đợt 0/1/3, 11 PR); gitignore `var/` log orchestrator
- feat(company): DoD của delivery-lead / release-engineer / account-manager gồm "sản phẩm khởi động bằng một lệnh ghi trong README và trả lời một request thật"; frontend đính ảnh chụp giao diện vào `evidence.screenshots[]`, không chụp được thì phải trả `skipped` kèm lý do (B6, ADR-0033) (#111)
- fix(company): lịch sử hồ sơ escalation xếp theo thứ tự ghi vào bus khi trùng dấu thời gian — hết test chập chờn 1/6 lần, và lỗi không còn hiện sau lần retry mà nó gây ra (TRAPS khuôn 5)
- chore: `.gitattributes` đặt `merge=union` cho CHANGELOG và bảng theo dõi đặc tả — nhiều phiên song song thêm dòng cùng lúc thì gộp, không dừng rebase
- feat(company): regression-staging mang evidence.run do orchestrator tự chạy — verdict không có bằng chứng thì hạ fail (B3, ADR-0029) (#102)
- feat(company): Gate 1 đòi runtime — spec ứng dụng thiếu lệnh khởi động thì request_changes, không mở gate (B1, ADR-0031) (#104)
- feat(company): supervisor đếm nợ kiến trúc treo — cùng mã nợ nhắc ≥ N review liên tiếp thì escalation cấp dự án (B5, ADR-0032) (#103)
- feat(console): thiết kế lại dashboard theo 10 ghi nhận vận hành — phễu release, hậu quả gate, bế tắc im lặng, commit vượt integration, gate_brief tại chỗ (C1–C8, C10) (#107)
- feat(console): thiết kế lại dashboard theo 10 ghi nhận vận hành — phễu release, hậu quả gate, bế tắc im lặng, commit vượt integration, gate_brief tại chỗ (C1–C8, C10) (#107)
- fix(console): sửa chuỗi `HINT_TMPL` vỡ cú pháp JS (nháy kép chứa xuống dòng thật) từ #107 — làm chết cả trang trực ban, mọi state hiện "chưa đọc được" dù server vẫn chạy đúng (#113)
- fix(company): ticket làm lại sau khi đã merge thì bản sửa vẫn vào nhánh tích hợp — `integrated` không còn che commit mới (#105)
- feat(company): gate_brief acceptance tự khởi động sản phẩm theo runtime, khách ký trên thứ đã chạy (B4) (#100)
- docs(gateway): 3 ADR (xoay vòng, giữ cổng, ranh giới bảo mật) + bộ khung CLAUDE/TRAPS/CODEMAP/ARCHITECTURE (E4) (#101)
- chore: đợt 0 đặc tả nâng cấp — CHANGELOG đủ số PR, gitignore `*.yaml.bak*`, mốc lịch sử repo trong ARCHITECTURE, CI `PR policy` bắt PR phải có dòng CHANGELOG (nhãn `no-changelog` để miễn) (#98)
- fix(company): `watch()` không nuốt `ReloadRequested` thành `tick_error` (#95)
- fix(company): audit `invalid_output` ghi kèm lời agent — "không sửa file nào" phải nói vì sao (#94)
- fix(company): delivery-lead v10 — kế hoạch là ticket trong `items` ngay lượt planning; trả rỗng để chờ duyệt là bị từ chối (#93)
- fix(company): duyệt escalation "kế hoạch bị từ chối" = delivery-lead lập lại kế hoạch, không "reopen" ticket ma (#92)
- feat(company): sổ Ruling — agent tự quyết ngoài bốn gate, ghi decision/why/cost_if_wrong vào audit; `status`, CLI `rulings`, mọi hồ sơ gate hiện sổ (ADR-0030) (#97)
- docs: đặc tả nâng cấp tháng 9/2026 — sáu đợt, 40 mục, bốn câu hỏi đo "hoàn thiện" (`docs/DAC-TA-NANG-CAP-2026-09.md`) (#96)
- docs: bộ khung repo 9 file — AGENTS/CLAUDE/TRAPS, ARCHITECTURE/CODEMAP/CHANGELOG, task pack/prompt sheet/session log; mỗi package con có CLAUDE/TRAPS/CODEMAP/ARCHITECTURE riêng (#91)
- feat(company): `deployed` ở staging phải qua smoke do orchestrator tự chạy — lời khai thành bằng chứng (ADR-0029) (#90)
- feat(company): `trace <id>` — dòng thời gian một ticket/release từ intake tới deploy (B7 đặc tả nâng cấp) (#99)

## 2026-09-06

- fix(company): tool ghi được `.env.development/.env.example/.env.sample/.env.test` — file mặc định công khai (#88)
- fix(company): reviewer và security-engineer có tool chỉ-đọc khi chấm PR — diff bị cắt thì đọc file, không BLOCK mù (#87)
- docs(git): mỗi phiên agent một worktree riêng, không dùng chung một clone (#86)
- docs(company): đối chiếu superpowers và các skill thiết kế web với quy trình công ty (#85)
- fix(company): HEAD là commit WIP mà lượt này không sửa gì → PR từ HEAD, không invalid_output (#84)
- feat(company): orchestrator tự khởi động lại khi mã nguồn đổi (`run --watch`) (#83)
- fix(company): lần giao lại giữ việc dở của lượt trước thành WIP, không vứt (#82)
- fix(company): agent lỗi trên event không phải ticket → duyệt escalation là chạy lại event, không "reopen" ticket ma (#81)
- fix(company,console): huỷ RC đã bị bản giao vượt qua; lượt production nhận bằng chứng; console khoá duyệt escalation lý do ngắn (#80)
- docs(company): báo cáo "bản giao đầu tiên không chạy được" — 6 đề xuất (#79)
- fix(company): sweep RC `pending_human` không gate ở mỗi nhịp (#78)
- fix(company): release-engineer tự dừng → gate escalation; duyệt là chạy lại ngay (#77)
- feat(console): lớp "sự thật giao hàng" — phễu release, bế tắc im lặng, quyết định chưa áp (#76)
- fix(company): review trên release lấy `ticket_id` từ ROUTE (#75)
- fix(company): CLI publish suy key: `change_id` trước `project_id` (#74)
- fix(company): `run()` nạp event tiến trình khác ở mọi vòng (#73)
- fix(company): `env`/`release_id` của release-event là của ROUTE (#72)

## 2026-09-05

- fix(company): `redeploy` cần client thật (#71); lệnh `redeploy <REL-xxx>` (#70)
- fix(company): Gate 3 chỉ gác production — gỡ deadlock giao hàng (#69)
- ci(software-company): pytest-xdist `-n auto` — job unit 346 s → ~100 s (#68)
- fix(company): giữ hint của người qua các lượt retry; ưu tiên mã nguồn khi cắt diff (#67)
- fix(company): trạng thái "đã tích hợp" sống sót qua restart (#66); duyệt escalation đánh dấu XONG khi code đã ở nhánh tích hợp (#65)
- fix(company): release bị chặn không tự đá ticket đã merged về rework (#64); xung đột merge không đốt retry nội dung (#63)
- fix(company): `CLI_NO_TOOL_TURNS` 3 → 6 (#62); `claude -p` không tool cần > 1 lượt (#60); phân loại thoát mã 1 theo thông điệp (#58); schema union → anyOf (#56)
- ci: guard đối chiếu file ruleset với rule đang áp (#61)
- fix(company): không mở gate escalation trùng sau khi mở lại bus (#57); duyệt escalation do review lỗi thì chạy lại review thiếu (#59); task cũ không giao lại sau takeover (#55)

## Trước 2026-09-05

- ci: canh gác bảo vệ nhánh `main` (#40); docs: runbook trực ban và dừng khẩn (#47); test: phủ 100% dòng cả bốn package (#48)
- feat(company): ADR-0028 vai viết test độc lập (#45, #50); docs: nhập Hallmark vào bốn skill giao diện (#49)
- fix(studio): TTS nhận đúng tiếng Việt trên Windows (#54); fix: số liệu README khớp thực tế (#46)
- Lịch sử đầy đủ: `git log --oneline main`.
