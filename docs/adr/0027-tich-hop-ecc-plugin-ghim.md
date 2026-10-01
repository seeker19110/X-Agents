# ADR-0027: tích hợp ECC (`affaan-m/ECC`) bằng plugin ghim commit — luật repo thắng, runtime công ty cách ly

Ngày: 2026-10-01 · Trạng thái: **đề xuất** (người dùng yêu cầu "tích hợp sâu, tối đa"; chờ duyệt qua PR) ·
Liên quan: ADR-0003 (đối chiếu ruflo), `companies/software-company/docs/adr/0023`, `0024`, `0026` (claude -p)

## Bối cảnh

ECC (`affaan-m/ECC`, trước là `everything-claude-code`, giấy phép MIT) là bộ "harness" cho Claude Code nổi tiếng
nhất hiện nay: agent, skill, lệnh, hook vòng đời và rule. Đo trên bản clone tại tag `v2.2.2`
= `c70874fae9eb0e5ad0365beb7e2955899fd1d30f` (commit 2026-09-29), không lấy số từ README của họ:

| Thành phần | Số lượng | Ghi chú đo |
|---|---|---|
| skill | 293 | mô tả cộng lại ~89k ký tự |
| agent | 68 | ~14k ký tự mô tả |
| lệnh (`commands/`) | 94 | ~13k ký tự mô tả |
| hook | 24 mục trong `hooks/hooks.json` | đều là script `node`, lọc theo `ECC_HOOK_PROFILE` / `ECC_DISABLED_HOOKS` |
| rule | `rules/common`, `rules/python`… | plugin **không** ship được rule — chỉ cài tay mới có |

Tiền lệ của repo với repo ngoài là **đối chiếu rồi lấy chọn lọc** (ADR-0003 lấy 1 thứ của ruflo; báo cáo
superpowers 2026-09-06 từ chối chép skill). Lần này người dùng hỏi thẳng "tích hợp tối đa". Hai điều khiến tích
hợp sâu lần này **không** lặp lại lý do từ chối cũ:

1. **Plugin có namespace và đứng thấp nhất.** Skill/lệnh/agent của plugin mang tiền tố `ecc:` và không bao giờ đè
   skill/lệnh cùng tên của repo (`/gate`, `/debug`, `/adr`, `/thi-hanh`…). Không chép file nào vào `.claude/`,
   nên không sinh thêm "bản dẫn xuất sửa tay" (luật cấm 5) và gỡ là một dòng.
2. **Hook tắt được theo id, đo được từng cái.** Không phải nhận cả gói hay bỏ cả gói.

## Quyết định

### 1. Nạp ECC như plugin project-scope, ghim đúng một commit

`.claude/settings.json` khai marketplace tại chỗ `xagents-ecc` (nguồn `settings`, không trỏ marketplace của họ)
chứa đúng plugin `ecc` từ `github: affaan-m/ECC`, `ref v2.2.2`, `sha c70874fae9eb0e5ad0365beb7e2955899fd1d30f`, rồi
`enabledPlugins`: `ecc@xagents-ecc: true`, `ecc@ecc: false`. Vế thứ hai tắt bản marketplace chính chủ (trôi theo
`main` của họ) cho những ai đã cài nó ở scope user — không thì phiên trong repo chạy **hai** bộ hook ECC chồng nhau.
Lock: `docs/integrations/ecc.lock.json` (cùng khuôn `projects-template.lock.json`). Cổng:
`platform/console/tests/test_cong_ecc.py` canh SHA settings = lock, hai cờ `enabledPlugins`, tập hook tắt = tập có
lý do trong lock, không vendor tệp ECC nào vào `.claude/`.

**Nâng bản** chỉ qua PR: đổi `sha` + `ref` trong settings và `revision`/`tag`/`measured` trong lock **cùng lúc**, đo
lại mục §2 trên bản mới. Không dùng `/ecc:auto-update` (kéo `main` của họ, phá ghim).

### 2. Hook: giữ profile `standard`, tắt đúng hai cái trái luật repo

Đo bằng cách chạy thẳng script hook của ECC bằng `node` với stdin giả lập payload của Claude Code:

| Hook ECC | Kết quả đo | Quyết định |
|---|---|---|
| `pre:bash:block-no-verify` | `git commit --no-verify` → rc=2 "BLOCKED"; có trong `ECC_DISABLED_HOOKS` → rc=0 | **tắt** — `--no-verify` là đường thoát tường minh của `AGENTS.md` §"Hàng rào thi hành"; `pre-commit-gate.sh` của repo đã canh commit |
| `pre:edit-write:suggest-compact` | nhắc `/compact` thủ công sau N lần sửa | **tắt** — trái chính sách auto-compact native 300k (`docs/AUTO-COMPACT.md`) |
| `pre:write:doc-file-warning` | rc=0 với `TRAPS.md`, `CODEMAP.md`, mọi đường dẫn `docs/`, `.claude/`, `agents/`, `skills/`; chỉ cảnh báo tên kiểu `NOTES.md`/`TODO.md` ở chỗ lạ, không chặn | giữ |
| `pre:config-protection` | chỉ chặn sửa tệp cấu hình linter riêng (`ruff.toml`, `.eslintrc*`, `biome.json`, `.prettierrc*`…); repo không track tệp nào trong số đó — ruff cấu hình trong `pyproject.toml` | giữ |
| `post:quality-gate` | với `.py` chỉ `ruff format --check` (không sửa, trừ khi `ECC_QUALITY_GATE_FIX=true`) — cùng chiều `auto-format.sh` | giữ |
| `stop:format-typecheck` | chỉ JS/TS (biome/prettier + `tsc --noEmit`), không đụng Python | giữ |
| `pre:*:gateguard-fact-force` | chặn lần sửa đầu mỗi tệp tới khi agent nêu importer/API/schema — đúng tinh thần "đo trước khi sửa" (luật bắt buộc 6) | giữ; ai thấy vướng: `ECC_GATEGUARD=off` hoặc `GATEGUARD_BASH_ROUTINE_DISABLED=1` trong `.claude/settings.local.json` |
| `pre:bash:commit-quality`, `pre:bash:git-push-reminder` | chỉ chạy ở profile `strict` | không bật `strict` cho tới khi đo hai hook này với quy ước commit có scope của repo |

### 3. Luật repo thắng khi trùng

ECC là **lớp thêm**, không phải luật. Khi trùng ý định, dùng của repo: `/gate` (không phải `/ecc:quality-gate`,
`/ecc:verify`), `/debug`, `/adr`, `/thi-hanh` (không phải `/ecc:orch-*`, `/ecc:multi-*`, `/ecc:epic-*`), quy trình
PR ở `docs/QUY-TRINH-GIT.md` (không phải `/ecc:pr`, `/ecc:prp-*`). Coverage là `fail_under = 100`, không phải 80% của
rule ECC; scope commit/PR theo `AGENTS.md` luật bắt buộc 7.

**Không dùng trong repo này** (ghi ra chỗ khác luật đã định): `/ecc:auto-update` (phá ghim), `/ecc:update-codemaps`
(`docs/CODEMAPS/` song song `CODEMAP.md` có cổng canh), `/ecc:hookify*` và `/ecc:project-init` (ghi hook/settings vào
`.claude/` không qua `test_cong_khung.py`), `/ecc:skill-create` và `/ecc:learn` khi đích là `.claude/skills/` của repo
(skill repo đi 7 bước `CONTRIBUTING.md` §3), `/ecc:save-session`/`/ecc:resume-session` thay cho `docs/sessions/`
(dùng thêm được, không thay), `/ecc:checkpoint` (tự `git stash`/commit ngoài quy trình nhánh).

**Dùng tự do**: lệnh review/kiểm theo ngôn ngữ (`/ecc:python-review`, `/ecc:fastapi-review`, `/ecc:react-review`,
`/ecc:security-scan`, `/ecc:test-coverage`, `/ecc:build-fix`, `/ecc:code-review`, `/ecc:review-pr`), skill kiến thức
(`ecc:python-testing`, `ecc:tdd-workflow`, `ecc:security-review`, `ecc:mcp-server-patterns`, `ecc:context-budget`…)
— hữu ích nhất khi người vận hành soi code mà công ty gia công sinh ra cho repo khách.

### 4. Runtime của công ty không nhận ECC: `--restricted` ở mọi chế độ `claude -p`

Company/keeper gọi `claude -p` làm backend LLM. Trước ADR này chỉ chế độ `cli_tools` có `--restricted`; chế độ
**không tool** (company, keeper) và **MCP** (company) đọc settings user/project của máy. Chế độ không tool chạy
với `cwd` của orchestrator — tức trong repo này, nơi ADR này vừa bật ECC ở project scope; người vận hành tự cài ECC
ở scope user thì mọi chế độ đều dính. Khi đó mỗi lượt agent chạy SessionStart của ECC (chèn ngữ cảnh), các hook
Stop (cost-tracker, evaluate-session…) và mang danh sách ~117k ký tự mô tả skill — lượt agent không còn đúng
prompt-là-code mà `companies/software-company/docs/adr/0004-prompt-as-code.md` giữ. Chế độ MCP chạy với `cwd` là
worktree **repo khách**, nên settings project của khách (hook, plugin họ bật) cũng có đường lọt vào.

Quyết định: thêm `--restricted` vào argv của chế độ không tool (company, keeper) và chế độ MCP (company). Theo
`claude --help` 2.1.286, `--restricted` bỏ qua settings user/project/local (managed settings và `--settings` vẫn
áp — deny-list file bí mật của `cli_settings_json()` không mất), chỉ gỡ tool **gốc** chạy lệnh (tool MCP của cầu
`companies/software-company/docs/adr/0024-cau-mcp-cho-claude-code.md` không phải tool gốc), và khoá tool file trong
thư mục làm việc. Chế độ `cli_tools` đã chạy với cờ này trong sản xuất cùng OAuth và cùng bộ cờ chung
(`--json-schema`, `--no-session-persistence`, `--effort`). Yêu cầu CLI ≥ 2.1.248 (bản có `--restricted`, ghi ở
`companies/software-company/docs/adr/0026-*`) nay áp cho cả ba chế độ chứ không riêng `cli_tools`. CLI cũ hơn → "unknown
option" → lỗi nói rõ (chế độ MCP đi qua nhánh `cli_lacks_mcp` sẵn có), không hỏng im lặng.

Rà cả họ (luật bắt buộc 5) — mọi chỗ dựng argv `claude -p` trong `src/`: company `llm.py` ba chế độ (giờ đều
`--restricted`), keeper `llm.py` (giờ `--restricted`), `xagents_core.llm` (chỉ transport, không dựng argv tool),
gateway `manage.py` `CLI_PROVIDERS` (lệnh **thăm dò tay** `models --probe-cli` của người vận hành, không phải lượt
agent — để nguyên, hook ECC chạy ở đó chỉ tốn vài giây).

## Đã kiểm và loại

- **Chép rule ECC vào repo** (`rules/common`, `rules/python`): trái `AGENTS.md` ở coverage (80% vs 100%) và khuôn
  commit (không scope). Hai bộ luật cùng nạp thì agent chọn theo câu nó đọc sau cùng.
- **Chép skill/agent ECC vào `.claude/`**: mất namespace (đè được skill repo), mất ghim, và thành hàng trăm tệp
  "bản dẫn xuất" không ai sinh lại.
- **Chạy `install.sh`/`install.ps1` của ECC**: ghi vào `~/.claude` của người chạy (scope user), ngoài repo và
  ngoài review.
- **Adapter ECC cho Cursor/Gemini/Codex**: các harness đó trỏ về `AGENTS.md` (`GEMINI.md`, `.cursorrules`…); thêm
  một nguồn luật thứ hai cho chúng là đúng lỗi "hai bộ luật" ở trên.
- **Cho agent của công ty dùng ECC** (nạp plugin vào `claude -p`): agent công ty là prompt-là-code có golden và
  eval ghi lại; một plugin 293 skill trôi theo bản ghim sẽ đổi hành vi mà không đi qua 7 bước `CONTRIBUTING.md` §3.
  Ngược lại hẳn: §4 cách ly chúng.
- **Profile `strict`**: xem bảng §2.

## Hệ quả

- Phiên Claude Code trong repo có thêm 293 skill + 94 lệnh + 68 agent mang tiền tố `ecc:`. Danh sách mô tả
  (~117k ký tự) vượt ngân sách liệt kê skill (1% cửa sổ ngữ cảnh): Claude Code tự bỏ mô tả của skill ít dùng, tên
  vẫn còn — không tràn ngữ cảnh nhưng skill hiếm dùng sẽ khó được gọi tự động; gọi tường minh `/ecc:<tên>` vẫn chạy.
- Hook ECC cần `node` trên máy (đo với v22). Thiếu `node` thì hook ECC lỗi khởi động, hook của repo không ảnh
  hưởng. Muốn giữ skill mà tắt hết hook ECC: `ECC_HOOKS_ENABLED=false` trong `.claude/settings.local.json`.
- Hook quan sát/học (`pre:observe`, `post:observe:continuous-learning`, `stop:evaluate-session`) ghi vào `~/.claude`
  của máy — cùng lớp với transcript Claude Code vốn đã ghi ở đó, không vào repo. Phiên chạm dữ liệu khách nhạy cảm:
  thêm ba id đó vào `ECC_DISABLED_HOOKS` trong `.claude/settings.local.json`.
- Thêm hai cờ vào argv chế độ không tool/MCP: test argv (`test_routing.py`, `test_mcp_bridge.py`, keeper
  `test_llm.py`) khoá chúng — gỡ cờ là đỏ.

**Chưa đo trong phiên viết ADR này** (công cụ chạy `claude` thật bị từ chối quyền trong container): (a) Claude Code
thật sự tải plugin từ marketplace `settings` + `sha` — mới chỉ có `claude plugin validate` xanh trên bản clone; (b)
mức rò thực tế của hook/plugin vào `claude -p` khi thiếu `--restricted` — kết luận lấy từ ngữ nghĩa trong
`claude --help`, không phải bản ghi; (c) một lượt MCP thật có `--restricted`. Phiên đầu tiên có `claude` đăng nhập
phải chạy `/plugin` (thấy `ecc@xagents-ecc`) và một lượt agent MCP thật trước khi coi ADR này là "đã đo".

**Đo 2026-10-01, phiên Claude Code on the web** (CLI 2.1.286, container remote, `claude` đã đăng nhập):

- `claude plugin marketplace list` → "No marketplaces configured"; `claude plugin install ecc@xagents-ecc --scope local`
  → `failureCode: not_found`. Đọc chuỗi trong binary CLI (mã đã minify — là suy luận, không phải đo): `install` chỉ tra
  marketplace đã đăng ký trong `~/.claude/plugins/known_marketplaces.json`; marketplace khai ở `extraKnownMarketplaces`
  của project là nguồn hạng "repo", được đăng ký qua bước tin tưởng tương tác chứ không tự đăng ký khi chạy lệnh.
- Một lượt `claude -p` thật trong repo, không `--restricted`: sự kiện `init` chỉ có hai plugin builtin, 69 lệnh không
  lệnh nào `ecc:` ⇒ **phiên Claude Code on the web không nạp ECC**. Container đặt `CLAUDE_CODE_REMOTE_HERMETIC_MODE`;
  chạy lại với môi trường đã gỡ các biến remote bị từ chối quyền (coi là lách hermetic), nên chưa tách được nguyên
  nhân là chế độ hermetic hay thiếu bước tin tưởng.
- (a) trên máy người vận hành, (b) và (c) vẫn chưa đo: phép đo hook SessionStart/Stop từ settings có/không
  `--restricted` trong một thư mục tạm cũng bị từ chối quyền.

## Liên quan

- `docs/integrations/ecc.lock.json` — bản ghim + lý do từng hook tắt.
- `platform/console/tests/test_cong_ecc.py` — cổng canh settings ↔ lock ↔ ADR.
- `CLAUDE.md` §"ECC" — bản rút gọn cho phiên Claude Code.
- `companies/software-company/src/company/assetscan.py` — đã mượn ý "ngân sách ngữ cảnh" của ECC trước ADR này.
