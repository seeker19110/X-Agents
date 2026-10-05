# Task pack — gói việc giao cho một phiên agent

Một phiên agent nhận việc như một lập trình viên mới đến ngày đầu: không biết vì sao, không biết ranh giới, không
biết "xong" nghĩa là gì. Gói việc là tờ giấy đặt lên bàn nó. **Điền đủ 7 mục, dán vào đầu phiên.** Mục nào để trống
**im lặng** là mục agent sẽ tự đoán — và đoán sai im lặng.

**Mục 1 (mục tiêu), 2 (kết quả mong đợi), 4 (bối cảnh) được phép viết một dòng "suy ra từ hạng mục lớn: <câu>"
thay vì điền đầy đủ, KHI VÀ CHỈ KHI mã này thuộc một hạng mục lớn (`QUY-TRINH-GIT.md` §2d, ADR-0012) mà ba mục
đó đã trả lời chung ở tầm hạng mục** — mọi mã trong cùng hạng mục thường chia sẻ cùng lý do, cùng "xong" nghĩa
là gì, cùng bối cảnh cần đọc. Đo được từ thực tế: 3/4 bản thi hành thật bỏ trắng ba mục này không nói lý do —
đó là chỗ luật cũ bị vi phạm, không phải chỗ ba mục thừa. "Suy ra: ..." là một câu **tường minh**, khác hẳn để
trắng: người đọc sau biết ngay đây là quyết định có chủ ý, không phải quên. Mã KHÔNG thuộc hạng mục lớn nào
(PR nhỏ độc lập) vẫn phải điền đủ cả 7 mục như cũ.

Mẫu (copy từ dòng này):

```markdown
# Task pack: <tiêu đề một dòng, dạng động từ>

## 1. Mục tiêu — vì sao làm việc này
<1–3 câu: chuyện gì đã xảy ra / đang thiếu gì. Có ngày, có ticket/PR/release nếu là sự cố.>

## 2. Kết quả mong đợi — "xong" nghĩa là gì
- [ ] <bằng chứng máy sinh: test nào xanh, lệnh nào chạy được, số nào đổi>
- [ ] <PR mở, auto-merge bật, CI xanh>
- [ ] <CHANGELOG + session log đã ghi>

## 3. Phạm vi — được chạm và KHÔNG được chạm
Được: <thư mục/file>
Không: <file cấm; ví dụ: không sửa prompt agent nếu không đi đủ 7 bước; không sửa .claude/agents/ tay>

## 4. Bối cảnh phải đọc trước (theo thứ tự)
1. `AGENTS.md`, `TRAPS.md` §<mục liên quan>
2. `<pkg>/CODEMAP.md` dòng "<muốn gì>"
3. <ADR / báo cáo / test hiện có liên quan>

## 5. Ràng buộc kỹ thuật
- <stack, ranh giới tin cậy phải giữ, schema không được phá, coverage 100>

## 6. Bẫy đã biết cho việc này
- <trích từ TRAPS.md; hoặc "chưa có — nếu mắc bẫy mới, ghi vào TRAPS.md">

## 7. Cách kiểm và cách báo
- Kiểm: <lệnh CI đúng; test hai chiều>
- Báo: <PR #, dòng CHANGELOG, session log>; việc bỏ dở → ghi rõ vì sao, không im lặng
```

## Ví dụ đã điền (việc thật, PR #90)

```markdown
# Task pack: bằng chứng máy chạy cho `deployed` ở staging

## 1. Mục tiêu
QLKH 2026-09-06: 4 gate xanh, 389 test pass, 25 release, 0 điểm vào chạy được. `status=deployed` là lời khai của
release-engineer. Đề xuất 3 + 6 của docs/reports/2026-09-06-ban-giao-khong-chay-duoc.md.

## 2. Kết quả mong đợi
- [ ] `release-events{staging}.payload.smoke` do orchestrator điền, `verified_by=orchestrator`
- [ ] có runtime mà không chạy → status `failed` + escalation; không runtime → `unverified` kèm lý do
- [ ] test đo hai chiều; ruff + mypy sạch; PR + ADR-0029

## 3. Phạm vi
Được: src/company/smoke.py (mới), orchestrator._release, topics/schemas/{approved-specs,release-events}.json,
templates/prd.md, gates/checklists.md, docs/adr/0029.
Không: prompt release-engineer (bằng chứng do code sinh, ADR-0010 — không cần eval lại).

## 4. Bối cảnh
AGENTS.md; TRAPS.md §2 "bốn gate xanh"; companies/software-company/CODEMAP.md "smoke"; ADR-0010, 0013, 0027;
tests/test_staging_khong_doi_gate3.py (harness FakeClient).

## 5. Ràng buộc
runtime.command chạy như lệnh lint/test của khách: clean_env, timeout, kill; cùng worktree tích hợp.

## 6. Bẫy
Sửa checklists.md → make subagents (bản dẫn xuất); thêm file test/ADR → sửa số trong README (test đếm từ đĩa).

## 7. Kiểm và báo
uv run pytest -q -p no:cacheprovider; ruff; mypy. PR #90, CHANGELOG, docs/sessions/2026-09-06.md.
```

## Gói việc thường trực: audit toàn dự án (ADR-0003)

Mỗi chân trời một lần (hoặc ngay sau một đợt PR đổi cấu trúc thư mục, đổi số test/agent/ADR, hoặc thêm một
miễn trừ), dán gói này vào một phiên **chỉ làm việc này**. Lý do nó tồn tại: `AGENTS.md` luật cấm 8 nói "không tin
lời khai", mà mọi con số và mọi câu khẳng định trong tài liệu đều là lời khai của một phiên nào đó trong quá khứ.

Bản đầu (2026-09-07) chỉ đo **số liệu trong README gốc** — 5/10 dòng lệch. Lần rà sau đó cho thấy phạm vi ấy quá
hẹp: ba loại lệch nặng nhất đều nằm ngoài nó (README con sửa rồi README gốc quên sửa; hoá thạch còn lại sau khi
một package rời workspace; câu chữ trong prompt agent mô tả sai hành vi thật). Gói này mở phạm vi ra **tám phép
đo**, giữ nguyên luật cũ: *lệch thì sửa tài liệu, không bao giờ sửa phép đo cho khớp tài liệu*.

### Ranh giới với cổng máy

17 job CI (`.github/workflows/ci.yml`, hội tụ ở job `quality` — `skipped` cũng tính là đỏ) đã canh: lint/type,
coverage `fail_under = 100`, eval phát lại, bản dẫn xuất lệch nguồn (`golden-check` + `keeper.cli drift`), bí mật
và CVE (`audit`), tài sản prompt (`asset-scan`), ruleset nhánh `main` (`protection-guard`).

**Phiên audit không đo lại thứ CI đã canh** — ghi "đã có cổng canh" vào bảng và đi tiếp. Nó đo đúng phần còn lại:
những gì không cổng nào bắt được, và bản thân các lối thoát hợp lệ khỏi cổng.

```markdown
# Task pack: audit toàn dự án

## 1. Mục tiêu
Đo lại mọi con số và mọi câu khẳng định kiểm chứng được đang nằm trong `README.md`, `AGENTS.md`,
`ARCHITECTURE.md`, README của từng package và các ADR trạng thái "được chấp nhận" — trên gói đã cài
(`uv sync` xong) chứ không trên ấn tượng đọc mã. Kiểm luôn các lối thoát khỏi cổng (miễn trừ, `omit`,
`pragma: no cover`) còn lý do đúng không. Lần trước: `docs/reports/<ngày>-tu-kiem.md`.

## 2. Kết quả mong đợi
- [ ] `docs/reports/<ngày>-audit.md` với bảng **phép · claim · đo được · chênh · lệnh** — mỗi dòng một lệnh đã
      chạy trong chính phiên này; đủ tám phép A1–A8 ở mục 5, phép nào sạch cũng phải có dòng ghi "0"
- [ ] số/câu nào lệch → sửa TÀI LIỆU trong cùng PR; không bao giờ sửa phép đo cho khớp tài liệu
- [ ] dòng lệch mà chưa có cổng canh → mục "Việc để lại" (không tự thêm test trong phiên này — luật cấm 7)
- [ ] "Việc để lại" của báo cáo **lần trước** được chép lại kèm trạng thái: đã đóng ở PR nào, hay còn treo
- [ ] PR mở, CHANGELOG + session log

## 3. Phạm vi
Được: `docs/reports/`, `README.md`, `AGENTS.md`, `ARCHITECTURE.md`, README/tài liệu package bị lệch, comment
trong `ci.yml`/`pyproject.toml` nếu chính comment đó là chỗ lệch.
Không: mã nguồn, test, prompt agent, `.claude/agents/` — đây là phiên **đo**, không phải phiên sửa. Lệch nằm
trong prompt agent (A4) cũng chỉ ghi vào "Việc để lại": sửa prompt phải đi đủ bảy bước `CONTRIBUTING.md` §3,
không sửa lẻ trong một PR tài liệu.

## 4. Bối cảnh
`docs/adr/0003-doi-chieu-ruflo.md`; báo cáo audit gần nhất trong `docs/reports/`; `platform/console/tests/test_readme_goc.py`
và `*/tests/test_readme*.py` (những gì CI đã canh); `.github/workflows/ci.yml` (danh sách cổng hiện có).

## 5. Ràng buộc — tám phép đo

**A1. Số liệu tài liệu gốc.** Số test đếm bằng `pytest --collect-only -q` (số **ca** thu được, không đếm
`def test_`). Agent/skill/topic/template/ADR đếm file trên đĩa. Coverage đọc `fail_under` trong `pyproject.toml`,
không đọc badge.
Từ 2026-09-15, **số test trong bảng của `README.md` gốc đã có cổng** (`test_so_test_trong_readme_khop_dia` —
nó tự chạy `--collect-only` cho từng package README có khai số). Nên phép này còn lại đúng phần chưa ai canh:
mọi con số KHÁC trong tài liệu (số màn console, số job CI, số dòng trùng, số ca eval) và các README con (A2).

**A2. README gốc so với README con.** Mỗi package tự mô tả mình ở README riêng; README gốc mô tả lại. Hai bản
phải khớp. Không cổng nào so chúng với nhau, nên đây là chỗ "sửa bản con, quên bản gốc" trú ngụ.
`find companies/*/agents platform/*/agents -name "*.md" | wc -l` rồi so với cả hai README.

**A3. Hoá thạch sau khi cấu trúc đổi.** Nguồn sự thật là `[tool.uv.workspace] members` trong `pyproject.toml`
gốc. Mọi câu văn đếm package ("năm package", "cả sáu package") phải khớp nó — grep **toàn repo**, kể cả comment
trong `ci.yml` và `AGENTS.md`, không chỉ file tài liệu:
`grep -rn "package" --include="*.md" --include="*.yml" --include="*.toml" . | grep -iE "năm|sáu|bảy|[0-9]+ package"`.
Một package rời workspace để lại tàn dư ở những chỗ không ai nghĩ là tài liệu.

**A4. ADR "được chấp nhận" so với mã thật.** Không đếm *số file* ADR — đọc **nội dung quyết định** của các ADR
trạng thái "được chấp nhận" và của prompt trong `agents/`, rồi kiểm từng câu khẳng định kiểm chứng được bằng mã.
Phép này chậm và không tự động hoá được; nếu hết giờ thì làm N ADR mỗi lần theo vòng và ghi rõ đã tới đâu.

**A5. Sổ miễn trừ — bốn lối thoát hợp lệ khỏi cổng.** Đếm cả bốn, ghi con số vào báo cáo, và với mỗi cái hỏi
"lý do ghi lúc thêm còn đúng không":
`grep -rn "pragma: no cover" --include="*.py" companies platform | wc -l` ·
`grep -rn "^omit" --include="pyproject.toml" .` ·
`cat companies/software-company/assetscan-waivers.txt` ·
`grep -rn "skipif\|@pytest.mark.skip\|xfail" --include="*.py" companies platform`.
Chỉ `assetscan-waivers.txt` tự dọn được (báo `waiver-unused`). Ba cái còn lại **đã có trần từ 2026-09-12**:
`platform/console/tests/test_cong_repo.py` giữ sổ `TRAN_PRAGMA`/`TRAN_SKIP` (tách theo từng package) và
`TRAN_OMIT`, so **BẰNG ĐÚNG** — thêm một lối thoát thì đỏ, mà **bớt** một cái cũng đỏ tới khi hạ sổ, nên sổ
không bao giờ nói quá. Vậy phép này KHÔNG còn là "đếm xem có ai lén thêm không" (cổng làm rồi), mà là phần cổng
không làm được: **đọc lý do ghi lúc thêm và hỏi nó còn đúng không**. Con số thay đổi ⇒ đã đi qua review; lý do
hết đúng thì không cổng nào biết.

**A6. Độ sâu phép đo, không chỉ con số.** `fail_under = 100` trên **dòng** vẫn để lọt nhánh chưa đi. Package nào
chưa `branch = true` **đã có cổng canh từ 2026-09-15** (`test_branch_coverage_dung_so_chua_phu_nhanh`, sổ
`CHUA_PHU_NHANH`, so bằng đúng). Sổ rỗng từ #366 (2026-09-28): cả năm package đo nhánh, và `# pragma: no
branch` được đếm chung sổ `TRAN_PRAGMA` với `no cover`. Phép này còn đúng một việc cổng không làm: câu "phủ 100%"
trong tài liệu vẫn phải nói rõ *100% dòng* hay *100% dòng và nhánh* — nói trống là một dòng lệch, và phần "dòng
lệch" ấy thì chưa cổng nào canh.

**A7. Hạn dùng của bằng chứng.** Bằng chứng có ngày, và ngày cũ đi thì bằng chứng nhạt đi kể cả khi không cổng
nào đỏ: ngày ghi eval recordings (`companies/*/evals/recordings/REQUIRED.txt` + `git log -1 --format=%ad` trên
thư mục recordings), ngày báo cáo audit gần nhất, sổ nợ quá hạn của keeper
(`cd companies/keeper && uv run python -m keeper.cli gate --db keeper.sqlite list`). CI chỉ đỏ khi **prompt** đổi
mà bản ghi cũ — nó không đỏ khi prompt đứng yên còn model đằng sau đã đổi.

**A8. Cổng còn hiệu lực không.** `protection-guard` canh ruleset, nhưng không ai canh việc một job bị `if` loại
hay bị gỡ khỏi `needs` của job `quality`. Đối chiếu danh sách job trong `ci.yml` với danh sách trong
`needs:` của `quality`: `grep -n "^  [a-z-]*:" .github/workflows/ci.yml` so với `grep -n "needs:" -A2` của job đó.
Job có trong file mà không có trong `needs` là một cổng xanh giả.

## 6. Bẫy
- Một dòng README có hai chỗ nói cùng một số (test package đã mắc: `pytest N ca` và `Test: N ca`) — sửa một chỗ
  là CI đỏ.
- Con số lệch một chiều "nói ít hơn thật" vẫn là lệch; đừng bỏ qua vì "ít nhất không nói quá".
- Đếm file `.md` trong `agents/` bằng `ls agents/*/*.md` cho kết quả khác `find agents -name "*.md"` khi có thư
  mục lồng — báo cáo 2026-09-07 và lần rà sau ra hai số khác nhau vì lý do này. Ghi rõ lệnh đã dùng.
- Phép A4 dễ trượt thành đếm file ADR cho nhanh. Đếm file là A1, không phải A4.
- Phép A3 dễ trượt thành grep mỗi `*.md`. Tàn dư sống lâu nhất nằm trong comment mã và comment CI.

## 7. Kiểm và báo
`uv run pytest -q platform/console/tests/test_readme_goc.py` và các `*/tests/test_readme*.py` liên quan sau khi
sửa tài liệu. Báo: PR #, dòng CHANGELOG `docs: audit <ngày>`, session log.
```


### Việc để lại đang treo

Sổ này là nơi "Việc để lại" của các báo cáo sống tiếp thay vì chết trong một file `docs/reports/` không ai mở
lại. Mỗi phiên audit **đọc sổ này trước, cập nhật nó sau**; đóng được dòng nào thì xoá dòng đó kèm số PR trong
CHANGELOG.

| Từ | Việc | Vì sao chưa làm trong phiên đo |
|---|---|---|
| 2026-09-12 | Canary keeper BT8 (phép A7) — **đã THỬ chạy thật, dừng đúng lúc vì hai phát hiện thật**: (1) chuỗi tự động signal→patch chưa nối hết — `watch` chỉ `triage`+`open_pr` (ý định, chưa gọi `gh pr create`/`git push` thật, xác nhận lại bằng đọc mã: `github.py` chỉ có `GitHubReader`, không class ghi nào); `dependency-scout`/`security-auditor` chưa nối CLI, chỉ `drift` chạy được. (2) Chạy thật `drift`/`dependency-scout`/`health-monitor` trên chính repo: `drift` SẠCH (kỷ luật CHANGELOG tốt), `dependency-scout` 0 tín hiệu (Dependabot alerts **bị tắt** ở repo này — `gh api .../dependabot/alerts` trả 403), `health-monitor` có 2 tín hiệu thật (flake rate 0.67, CI p50=58s/p95=330s) nhưng **không loại tín hiệu nào keeper vá tự động được** — thao tác duy nhất đã nối (`patcher.fix_docs`) chỉ thêm dòng CHANGELOG/session-log thiếu, và không có dòng nào thiếu lúc đo | Người dùng chọn dừng đúng chỗ thay vì dựng kịch bản giả (tự tạo lỗ hổng CHANGELOG hoặc mở rộng phạm vi vá) — canary cần tín hiệu THẬT, đây là kết quả thật: repo hiện quá sạch cho phạm vi vá quá hẹp. Việc còn lại là mở rộng phạm vi vá tự động (bump_dependency/regen_derived) hoặc nối thêm loại tín hiệu keeper sửa được — quy mô một hạng mục thi hành riêng. **Audit 2026-09-27:** phát hiện (1) đã cũ — `keeper/publish.py` nay có `git push` + `gh pr create`, `patcher.py` có `bump_dependency`/`regen_derived` |
| 2026-09-13 | Canary keeper BT8, lần hai — **tín hiệu thật xuất hiện (`pr-280`: PR #280 thiếu dòng CHANGELOG), chạy hết pipeline thật tới ngay trước publish, dừng đúng ở cổng I3 ngân sách** (bằng chứng đầy đủ ở `docs/reports/2026-09-12-audit.md` mục A7 "Cập nhật 2026-09-13"). Ticket `KEEP:13939458f6c04673b7e4bf4f5cfee647` (`risk_tier=low`, không cần gate) đã có patch commit `ef4380f` trong `../Claude-Agents-wt-keeper-KEEP-13939458f6c04673b7e4bf4f5cfee647` (nhánh `chore/keeper-KEEP-13939458f6c04673b7e4bf4f5cfee647`, CHƯA push) và bằng chứng hai chiều đo thật (đỏ/xanh) đã qua `require_two_way`. `orc.pr_blockers(ticket) == ["budget"]`: PR #246 (dependabot, không liên quan) đang mở, `budget.can_open_pr()` xét MỌI PR mở trong repo nên chặn đúng thiết kế (I3) | Không tự merge/đóng PR #246 (ngoài phạm vi canary — không phải PR của keeper, không phải việc của phiên này) và không tự publish khi `open_pr()` chưa phát hành `release-notes` thật. Việc còn lại: sau khi PR #246 đóng/merge, chạy lại `orc.tick()` rồi `keeper publish KEEP:13939458f6c04673b7e4bf4f5cfee647` để có PR bảo trì thật đầu tiên — người merge nó mới đóng được I7. **Audit 2026-09-27:** PR #246 đã đóng — chặn ngân sách I3 không còn, canary chạy lại được (Đợt 4.2 của báo cáo) |
| 2026-09-27 | Từ audit 27/09 còn S2 (egress, ADR gốc 0010), O1 (checkout watcher vận hành riêng), O3 (đường Docker chạy thật) | B2 #385, B4 #384, O2 #386, O4 #387 đã đóng; A3.4 #388 và A3.5 #389 xử lý hai việc động cơ. S2/O3 cần kiểm container/network thật; O1 cần chuyển watcher ở môi trường vận hành, không chỉ sửa mã trong worktree |
| 2026-09-27 | S1 — ADR gốc 0023 (F1) còn **Proposed**; reviewer phạm vi `rong` chạy trên máy không container. Chủ dự án chọn hướng (a) 2026-09-27 (cài container runtime) nhưng máy trực chưa có `docker` trên PATH Windows | Chờ runtime chạy được từ tiến trình orchestrator (Docker Desktop, hoặc chạy công ty trong WSL theo ADR gốc 0013) rồi mới làm bốn gói của ADR |
| 2026-09-27 | ADR gốc 0010 còn **Proposed** và chưa cài (gốc 0019, 0026 và company 0045 đã Accepted 2026-09-28, #367) | Trạng thái khớp mã: chưa cài thì chưa Accepted; đóng dòng này cùng PR cài ADR |
| 2026-10-05 | O1 và canary keeper BT8, đo lại trên `main` sau #389 (#390) | O1: checkout riêng `runtime-main` detached tại `origin/main@c54d9c83`, `uv sync --locked` thành công; chưa chuyển watcher vì checkout mới chưa có cấu hình/bus vận hành và Docker chưa dùng được trong WSL. BT8: `keeper.cli drift --repo .` sạch; `dependency-scout` trả 0 tín hiệu; `health-monitor` thấy flake rate 0,69 và CI p50=12,0s/p95=546,1s nhưng keeper chưa có thao tác vá loại tín hiệu này. Bus và worktree ticket canary cũ không còn ở đường dẫn đã ghi năm 2026-09-13, nên không thể tiếp tục ticket cũ; cần tín hiệu thật mà keeper vá được và PR bảo trì thật do người merge. S1/S2/O3 vẫn chờ Docker Engine dùng được từ tiến trình orchestrator. |


## Khi nào không cần gói việc

Sửa tài liệu một file, đổi một chuỗi, trả lời câu hỏi. Còn lại — kể cả "sửa lỗi nhỏ" — điền mục 1, 2, 3 tối thiểu;
ba mục đó là thứ hay bị bỏ qua nhất và đắt nhất khi bỏ qua.
| 2026-10-05 | S1 và O1 trên Docker Engine thật | Docker Desktop Engine 29.8.0 (Windows) và Engine 29.1.3 (WSL) đã chạy container thật. Watcher chuyển sang checkout Windows `X-Agents-runtime-main`, cấu hình LLM thật, bus và repo CAMPUS-UNI thật; tác vụ `XAgents-Company-Watcher` báo Running, Python đọc 4554 event, integration `5d0d7ca`, queue 0. PR S1: ADR 0023 Accepted (a), auto fail-closed, audit/status/console và ca F1 container thật. Sau merge phải cập nhật checkout watcher và kiểm audit mới. O3 build hub thành công nhưng HTTP ngoài container lỗi (bên trong 200) và image thiếu `docker compose`; còn phải sửa/đo lại. S2 cần egress enforce thật; BT8 chưa có tín hiệu keeper vá được; CAMPUS-UNI còn 6 escalation, chưa RC mới/chữ ký khách. |


| 2026-10-05 | O3 runtime hub | Đo ba lỗi thật: bind container, thiếu Compose plugin, ghi Git config chỉ đọc. Bản sửa build/compose fixture trả HTTP 200, socket Engine dùng được; cổng/PR còn cần hoàn tất. Đây không phải RC CAMPUS-UNI hay chữ ký khách. |
