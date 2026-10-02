# ADR-0028: ECC vào repo bằng vendor chọn lọc, ghim commit, sinh lại được — bỏ đường plugin

Ngày: 2026-10-02 · Trạng thái: **đề xuất** (chờ duyệt qua PR) · Thay một phần ADR-0027: §1 (nạp bằng plugin), §2
(hook ECC) và gạch "chép skill/agent ECC vào `.claude/`" ở mục "Đã kiểm và loại". §3 (luật repo thắng) và §4
(`--restricted` ở mọi chế độ `claude -p`) của ADR-0027 giữ nguyên.

## Bối cảnh

Người dùng: "chọn theo hướng tốt, chất lượng nhất, ecc tích hợp vào repo kiểu không cần là plugin". Đường plugin
của ADR-0027 có ba vấn đề đã đo, không phải suy đoán:

| Vấn đề | Số đo |
|---|---|
| Không chạy ở nơi cần | Phiên Claude Code on the web: `init` chỉ có 2 plugin builtin, 0 lệnh `ecc:`; `claude plugin install ecc@xagents-ecc` → `not_found` (ADR-0027, đo 2026-10-01). Marketplace khai trong `extraKnownMarketplaces` cần bước tin tưởng tương tác. Trên máy thật vẫn chưa đo (mục a). |
| Kéo cả gói | 293 skill + 94 lệnh + 68 agent, mô tả cộng lại 116 816 ký tự (lock cũ), vượt ngân sách liệt kê skill nên skill hiếm dùng mất mô tả |
| Hook trái luật | 24 mục hook, đều là script `node`; 2 phải tắt vì trái luật repo, GateGuard chặn lần sửa đầu mỗi tệp |

ADR-0027 từng loại cách chép skill/agent vào `.claude/` vì ba lý do. ADR này giữ được cả ba bằng cơ chế khác:

1. **Mất namespace.** Giữ bằng tiền tố `ecc-`, thay cho `ecc:` của plugin. Cổng kiểm tên.
2. **Mất ghim.** Giữ bằng lock ghi đúng commit và sha256 từng tệp. CI sinh lại từ commit ghim rồi so.
3. **Hàng trăm bản dẫn xuất không ai sinh lại.** Chỉ vendor 23 mục; mọi tệp do `scripts/ecc_vendor.py` sinh.
   Luật cấm 5 mở rộng cho chúng.

ECC tự có một tập tuyển: `manifests/pi-core.json` gồm 123 skill và 24 lệnh "chỉ là prompt". Tập này đã loại thứ
cần mạng, khoá API hay SaaS, hook, vòng lặp riêng của Claude Code, và gói ngách. ADR này dùng nó làm sàn lọc đầu,
rồi lọc tiếp theo stack của repo: Python (aiohttp, httpx, pydantic, sqlite), console JS thuần, hệ agent LLM, MCP,
Docker. Agent của ECC (pi không có agent) lọc theo cùng tiêu chí.

## Quyết định

### 1. Vendor allowlist từ đúng commit ghim

`docs/integrations/ecc.lock.json` là nguồn duy nhất. Nó ghi ba thứ:

- bản ghim: `repository`, `tag`, `revision`;
- `select`: từng mục kèm một câu lý do;
- `rejected`: mục đã cân nhắc rồi loại, kèm lý do.

`scripts/ecc_vendor.py build` lấy ECC tại `revision` (fetch nông một commit, kiểm `HEAD == revision`). Nó chép
đúng các mục trong `select`:

| Mục | Chép vào |
|---|---|
| skill | `.claude/skills/ecc-<tên>/` (cả thư mục, chỉ `.md`) |
| lệnh | `.claude/commands/ecc-<tên>.md` |
| agent | `.claude/agents/ecc-<tên>.md` |
| giấy phép MIT | `docs/integrations/ecc.LICENSE` |

Rồi nó ghi `files` (đường dẫn, nguồn, sha256 tính sau khi chuẩn hoá xuống dòng về LF) và `measured` vào lock.
Mục mới trên upstream **không bao giờ tự lọt vào**: nâng bản chỉ đổi nội dung của mục đã chọn.

### 2. Biến đổi tất định, tối thiểu

Nội dung giữ nguyên văn upstream, trừ ba biến đổi:

- **Tên trong frontmatter**: `name: x` thành `name: ecc-x`.
- **Tham chiếu tới mục đã vendor**, chỉ ở dạng tường minh: `/lệnh`, `` `tên` ``, `**tên**`, `skill: tên`, đường
  dẫn `agents|skills|commands/…`, và tên agent có gạch nối viết trơn. Mỗi dạng đổi sang `ecc-…` hoặc
  `.claude/…`. Tham chiếu tới mục không vendor để nguyên. Từ thường trùng tên (vd "accessibility") không bị đổi.
- **Ghi chú nguồn** ngay sau frontmatter của tệp chính: commit nguồn, "không sửa tay", và "luật ở `AGENTS.md`
  thắng khi trùng". Ghi chú nêu rõ: coverage `fail_under = 100` chứ không phải 80%; test đỏ trước; PR theo
  `docs/QUY-TRINH-GIT.md`; không xoá code ngoài yêu cầu.

### 3. Hai lớp quét

**Lớp 1, trên nguồn, trong lúc build.** Build dừng nếu gặp symlink, tệp không phải `.md`, hoặc dấu hiệu "chỉ chạy
được khi là plugin": `CLAUDE_PLUGIN_ROOT`, `~/.claude`, `.claude/` (ghi tệp vào cây `.claude` của repo),
`node scripts/` (script ECC không vendor), `npx -y`, `ecc:`. Frontmatter phải có tên trùng tệp và có mô tả.

**Lớp 2, cổng `platform/console/tests/test_cong_ecc.py`, offline.** Các điều cổng kiểm:

- Mọi tệp `ecc-*` trong `.claude/` khớp `files` của lock theo sha256, không thừa, không thiếu.
- Tên mang tiền tố, frontmatter đúng.
- Tổng mô tả ≤ `budget_description_chars`.
- `select` và `rejected` không giao nhau.
- Có giấy phép.
- Settings không còn plugin, env hay hook ECC.
- `company.assetscan.scan_text` (cùng bộ mẫu `guard.PATTERNS`, ADR-0022) không ra lỗi `high` nào chưa miễn trừ.
  Miễn trừ nằm trong `assetscan_waivers` của lock, mỗi cái có lý do. Miễn trừ không còn khớp gì thì cổng đỏ.

**Ngoài hai lớp: CI chạy `scripts/ecc_vendor.py check`** trên bản ECC lấy tại commit ghim. Bước này chứng minh tệp
trong repo đúng là output của script, không ai sửa cả tệp lẫn hash trong lock.

### 4. Bỏ plugin và hook ECC

- Xoá `extraKnownMarketplaces.xagents-ecc` và hai biến `ECC_HOOK_PROFILE` / `ECC_DISABLED_HOOKS`.
- `enabledPlugins`: `ecc@ecc: false` (bản trôi theo `main` của họ), `ecc@xagents-ecc: false` (máy nào đã cài theo
  hướng dẫn cũ). Không đặt hai cờ này thì một phiên thấy cùng skill hai lần (`ecc:x` và `ecc-x`) và chạy hook không
  ghim.
- Không vendor hook nào: hook ECC cần `scripts/hooks` và `scripts/lib` (mã JS không test, không coverage). Hàng rào
  của repo (`.claude/hooks/`) đã canh đúng chỗ.

### 5. Tập chọn

| Loại | Mục | Vì sao có ở repo này |
|---|---|---|
| skill | `python-patterns`, `python-testing` | năm gói đều là Python |
| skill | `error-handling`, `api-design` | gateway (proxy OpenAI-compatible) và HTTP của console |
| skill | `security-review` | checklist bảo mật đi kèm tệp `cloud-infrastructure-security.md` |
| skill | `agent-harness-construction`, `cost-aware-llm-pipeline`, `agent-introspection-debugging`, `agent-architecture-audit` | lõi của repo là hệ agent LLM: tool, định tuyến model, chẩn đoán lượt agent hỏng |
| skill | `production-audit`, `docker-patterns` | release/deploy của công ty; repo có `Dockerfile`, `docker-compose.yml` |
| skill | `accessibility` | console là UI web; vai qa chấm a11y |
| lệnh | `python-review`, `review-pr`, `build-fix` | review theo ngôn ngữ, review PR nhiều agent, sửa lỗi build |
| agent | `python-reviewer`, `code-reviewer`, `comment-analyzer`, `pr-test-analyzer`, `silent-failure-hunter`, `type-design-analyzer`, `code-simplifier`, `security-reviewer` | sáu agent `review-pr` gọi, một agent `python-review` gọi, cộng một reviewer bảo mật |

Mục đã loại đáng chú ý (đầy đủ trong `rejected` của lock):

| Mục bị loại | Lý do |
|---|---|
| `tdd-workflow`, `test-coverage` | lấy 80% coverage làm trục; `tdd-workflow` còn gọi `node scripts/setup-package-manager.js` |
| `refactor-clean` | xoá dead code, trái luật cấm 7 |
| `code-review` | ghi `.claude/reviews/`; Claude Code đã có `/code-review` |
| `verification-loop` | trùng `/gate` |
| `architecture-decision-records` | trùng `/adr` |
| `git-workflow`, `pr`, `prp-*` | trùng `docs/QUY-TRINH-GIT.md` |
| `orch-*` | trùng `/thi-hanh` |
| `security-scan` | bọc sản phẩm thương mại AgentShield |
| rule ECC | như ADR-0027 |

### 6. Nâng bản

Đổi `revision`, `tag`, `version` trong lock, thêm hoặc bớt `select` nếu cần, chạy `make ecc-vendor`, đọc diff của
`.claude/` như đọc mã người lạ, rồi mở PR. Không sửa tay tệp `ecc-*`.

## Phương án đã loại

- **Giữ plugin (ADR-0027).** Ưu điểm thật: gỡ chỉ một dòng, đủ 455 mục. Loại vì không nạp ở phiên web (đã đo), kéo
  cả gói, và kéo hook node.
- **Plugin và vendor song song.** Hai nguồn sự thật, cùng skill hiện hai lần dưới hai tiền tố.
- **Vendor toàn bộ.** 116 816 ký tự mô tả; hàng trăm tệp có nội dung trái luật (`orch-*`, `hookify*`, `checkpoint`,
  ghi `~/.claude`).
- **Vendor giữ nguyên tên, không tiền tố.** Ưu điểm thật: tham chiếu chéo tự khớp, không phải biến đổi gì. Loại vì
  đụng tên built-in của Claude Code (`/code-review`, `/security-review`), không nhìn ra nguồn khi gọi, và tên repo
  thêm sau có thể đụng.
- **git submodule hoặc symlink.** Claude Code tìm `.claude/skills/*/SKILL.md` trong cây làm việc. Clone của phiên
  web không kéo submodule. Symlink hỏng trên Windows, máy phát triển chính.
- **Vendor cả hook.** Thành mã JS trong repo mà không có test hay coverage. 2/24 hook trái luật. Hàng rào của repo đã
  đủ.
- **Sửa nội dung cho hợp luật repo** (dịch, cắt câu 80%). Mất tính "sinh lại được": mỗi lần nâng bản phải sửa tay
  lại. Ghi chú nguồn đầu tệp thay cho việc đó, còn mục trái luật ở lõi thì loại hẳn.

## Hệ quả

- `/ecc:<x>` đổi thành `/ecc-<x>`. Catalog chỉ còn 23 mục. Muốn thêm mục: sửa `select` (kèm lý do), chạy
  `make ecc-vendor`, mở PR.
- Luật cấm 5 mở rộng: `.claude/{skills,commands,agents}/ecc-*` và `docs/integrations/ecc.LICENSE` là bản dẫn xuất.
- Bước CI `check` cần tải được từ `github.com`. Mạng lỗi thì bước đỏ rõ, không xanh giả.
- Rủi ro còn lại: `python-testing` vẫn có câu "80%+" ở thân. Ghi chú đầu tệp nói luật repo thắng. Nếu thấy agent
  theo 80% thì chuyển mục sang `rejected`.
- `claude -p` của company/keeper vẫn chạy `--restricted` (ADR-0027 §4). Mức nhìn thấy tệp vendor khi chạy cờ này:
  xem mục "Đo" dưới.

## Đo

Đo ngày 2026-10-02 trong phiên Claude Code on the web (CLI 2.1.287), tại gốc repo. Nguồn là ECC v2.2.2 @
`c70874fae9eb0e5ad0365beb7e2955899fd1d30f`.

**Tập sinh ra** (`make ecc-vendor`, số trong `measured` của lock):

| Đo | Số |
|---|---|
| tệp | 25 (12 skill, 3 lệnh, 8 agent, 1 tệp phụ của `security-review`, 1 giấy phép), 197 621 byte |
| mô tả cộng lại | 5 035 ký tự, tức 4,3% của 116 816 (cả gói), ngân sách 6 000 |
| biến đổi so với upstream | 20 dòng `name:` và 25 dòng tham chiếu |
| tham chiếu tường minh tới mục không vendor | 20 (vd `tdd-workflow`, `/orch-review`, `verification-loop`). Để nguyên; ghi chú đầu tệp chỉ đường sang `/gate`, `/debug`, `/adr`, `/thi-hanh` |
| quét lớp 1 trên 23 mục đã chọn | 0 dấu hiệu "chỉ chạy được khi là plugin" |
| `company.assetscan` | 1 phát hiện `high` (`injection`) ở `ecc-agent-architecture-audit`. Đó là đoạn tài liệu mô tả kiểu tấn công, không phải lệnh. Đã miễn trừ có lý do trong lock |

**Hành vi của `scripts/ecc_vendor.py`:**

| Đo | Kết quả |
|---|---|
| `check` (tải nông từ github.com, sinh lại, so) | `ECC vendor khớp nguồn ghim.`, rc=0, 3,2 s |
| thêm một dòng vào `.claude/agents/ecc-code-reviewer.md` rồi `check` | `lệch: .claude/agents/ecc-code-reviewer.md`, rc=1 |
| `build` lần hai trên cùng nguồn | sha256 của 25 tệp cộng lock trùng từng byte với lần trước |

**Claude Code thấy gì.** Cùng repo, chạy `claude -p` một lượt với model nhẹ và `--tools ""`; số đếm lấy từ sự kiện
`init`:

| Chạy | lệnh slash | `/ecc-*` | skill | skill `ecc-*` | agent | agent `ecc-*` | agent `sc-*` | plugin |
|---|---|---|---|---|---|---|---|---|
| thường | 85 | 15 | 43 | 12 | 24 | 8 | 10 | chỉ builtin |
| `--restricted` | 53 | 0 | 21 | 0 | 6 | 0 | 0 | chỉ builtin |

Hai lượt đều trả `OK`. Kết luận:

- Phiên web nạp đủ 23 mục mà không cần plugin, marketplace hay `node`. 15 lệnh `/ecc-*` gồm 12 skill và 3 lệnh.
- Phiên này cũng liệt kê các skill `ecc-*` ngay sau khi build, không phải khởi động lại.
- Ở `--restricted` (chế độ mọi `claude -p` của company và keeper đang chạy, ADR-0027 §4), số mục `ecc-*` là 0, giống
  `sc-*`. Vendor không đổi những gì agent của công ty nhìn thấy.

**Chưa đo:** Claude Code trên máy thật (Windows). Cơ chế quét `.claude/` giống nhau trên mọi nền tảng. Riêng xuống
dòng thì `read_text` tự chuẩn hoá CRLF về LF, có test `test_ecc_vendor.py` cho trường hợp này.

## Liên quan

- `docs/integrations/ecc.lock.json`: bản ghim, `select`/`rejected`, `files`, `measured`.
- `scripts/ecc_vendor.py`; test ở `platform/console/tests/test_ecc_vendor.py`.
- `platform/console/tests/test_cong_ecc.py`: cổng offline.
- ADR-0027: §3 và §4 còn hiệu lực; ADR-0022 (`company.assetscan`).
