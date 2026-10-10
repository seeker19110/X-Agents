# Quy trình làm việc với Git — X-Agents

Áp từ quy trình của dự án `donghanh` (`CONTRIBUTING.md`, `docs/DEVELOPMENT_WORKFLOW.md`,
`CLAUDE.md` mục 11), rút gọn cho repo này: năm package Python trong một uv workspace (`companies/`,
`platform/`), làm việc chủ yếu một mình cùng AI, cổng chất lượng là `scripts/dev-task.sh gate <gói>` — một lệnh, khớp đúng `ci.yml`
(`gói`: `company|gateway|console|core|keeper|all`).

Luồng chuẩn: **Ý tưởng → Đặc tả → Nhánh → PR → CI/Review → Merge (squash) → Quan sát**.

## 1. Cổng đặc tả (chỉ với thay đổi lớn)

Thay đổi kiến trúc, thêm/bỏ agent, đổi schema topic, đổi hợp đồng event → viết ADR trong
`<công ty>/docs/adr/` (ví dụ `companies/software-company/docs/adr/`) **trước** khi code, và link ADR trong PR. Sửa lỗi nhỏ, chỉnh
prompt/skill, sửa tài liệu thì đi thẳng bước 2.

Không dùng "AI đề xuất" làm bằng chứng. Mọi khẳng định quan trọng phải truy được về code,
test, hoặc nguồn chính thống có ngày truy cập.

## 2. Nhánh

- Tách nhánh từ `main`, mỗi tính năng/sửa lỗi một nhánh.
- Đặt tên: `feat/<slug>`, `fix/<slug>`, `refactor/<slug>`, `perf/<slug>`, `docs/<slug>`,
  `chore/<slug>`. Có issue thì `feat/<issue>-<slug>`.
- **Không push thẳng `main`.** Mọi thay đổi vào `main` đều qua pull request, kể cả khi làm một mình.

## 2b. Nhiều phiên cùng lúc: mỗi phiên một worktree

Một clone chỉ có **một** HEAD. Hai phiên agent cùng mở một thư mục clone là hai tiến trình
lần lượt `git checkout` đè lên nhau, và commit của phiên này rơi vào nhánh của phiên kia — không lệnh nào
báo lỗi. Chuyện đã xảy ra (reflog 2026-09-06): `TRAPS.md` §3, dòng "Hai phiên chung một clone".

**Quy tắc: phiên nào không phải phiên đầu tiên thì làm trong worktree riêng.** Harness có tool worktree riêng
(Claude Code: `EnterWorktree`) thì dùng nó trước — nó lo cả đặt chỗ, tạo nhánh và dọn dẹp; không có thì tự tạo:

```bash
git worktree add -b <loại>/<slug> ../Claude-Agents-wt-<slug> origin/main
```

Rồi `cd` vào đó và làm bình thường; `.venv` ở gốc vẫn dùng được qua `uv run`. Xong việc thì dọn:

```bash
git worktree remove ../Claude-Agents-wt-<slug>
```

Kiểm trước khi bắt đầu, mất hai giây:

```bash
git worktree list
```

Cách nhận ra mình đang giẫm chân người khác: `git status` hay `git log` cho ra một nhánh mà lượt này không hề
tạo, hoặc `git reflog` có `checkout` mình không gọi. Gặp thì dừng, **đừng commit**, mở worktree riêng trước.

Điều này áp cho **phiên người lái**. Orchestrator đã cô lập sẵn: mỗi ticket một worktree dưới `.worktrees/`
(`companies/software-company/src/company/workspace.py`), và nó chạy trên repo của khách (`--repo`), không phải repo này.

## 2c. Nhiều phiên cùng lúc: chỉ một PR mở tại một thời điểm (áp toàn cục)

Nhiều phiên có thể **code song song** trên worktree riêng (§2b) như bình thường — quy tắc này chỉ khoá ở
bước **mở/merge PR**, để loại hoàn toàn xung đột nền do hai nhánh cùng lệch khỏi `main` một lúc.

- **Trước khi mở PR**: kiểm `gh pr list --state open`. Có PR khác đang mở (của phiên khác) → **không mở
  PR mới**. Tiếp tục code trên worktree của mình, chờ đến khi PR kia merge xong rồi mới mở.
- **Ngay khi PR trước merge xong, trước khi mở PR của mình**: `git fetch origin` rồi
  `git rebase origin/main` trên nhánh của mình (không merge `main` vào — rebase, giữ lịch sử thẳng).
  Giải conflict lúc rebase nếu có, chạy lại `scripts/dev-task.sh gate <gói>` sau rebase (§4/§7 vẫn áp).
- Rồi mới `gh pr create` + bật auto-merge như thường (§5).
- Nếu rebase xung đột nhiều/phức tạp → dừng, báo người dùng, đừng tự ý bỏ qua bằng merge thường hay
  `--no-verify`.

Vì mỗi PR luôn được rebase lên `main` mới nhất *ngay trước khi mở*, và không có PR thứ hai nào mở song
song để đá vào cùng nền — nhánh không bao giờ diverge lâu, nên xung đột merge gần như bị loại bỏ. Cái giá
đánh đổi: bước mở PR trở thành hàng đợi tuần tự giữa các phiên — phiên nào xong sau phải đợi phiên xong
trước merge trước.

**Cùng một phiên, làm việc kế tiếp trong lúc PR của chính mình còn mở**: được, và không cần đợi. Luật chỉ
khoá bước `gh pr create` (và merge), không khoá code hay commit — cứ mở nhánh/worktree cho việc kế tiếp,
viết code, chạy test, **commit tại chỗ** như bình thường. Chỉ giữ lại đúng hai việc cho tới khi PR trước
merge: (1) đừng `gh pr create` một PR thứ hai, (2) đừng push nhánh đó lên remote nếu commit sẽ phải viết
lại do rebase — an toàn nhất là commit cục bộ, `push` sau khi đã rebase. Ngay khi PR trước merge: `git fetch
origin` + `git rebase origin/main` trên nhánh việc kế tiếp (giữ lại các commit đã có), chạy lại
`scripts/dev-task.sh gate <gói>`, rồi mới `push` + `gh pr create`.

## 2d. Việc lớn: một nhánh cho cả hạng mục, PR nháp sớm, mỗi task một commit (ADR-0012)

Luồng chuẩn cho một việc đủ lớn để chia nhiều task nhỏ (không áp cho sửa lỗi một dòng, một PR nhỏ độc lập):

```
yêu cầu → phân tích hiện trạng → chốt yêu cầu → đặc tả kế hoạch + đặc tả triển khai chi tiết
        → chia hạng mục lớn → chia task nhỏ trong mỗi hạng mục
        → (mỗi hạng mục) một nhánh → task 1 (commit) → PR NHÁP → task 2..n (mỗi cái một commit + push)
        → `gh pr ready` → auto-merge squash
```

- **Đơn vị PR là hạng mục lớn, không phải task nhỏ.** Một hạng mục là một mục tiêu nghiệm thu được, thường 2–8
  task, chạm một mảng. Vượt trần này là hai hạng mục, không phải một PR to hơn — PR không ai review nổi và một
  CI đỏ ở cuối phải tháo ngược nhiều commit.
- **Mở PR ở trạng thái NHÁP ngay sau task đầu tiên**, không chờ xong cả hạng mục. Lý do: `pull_request.synchronize`
  vẫn kích CI thật trên PR nháp (không job nào lọc theo `draft`), nên mỗi task push lên vẫn có CI thật — không
  cần vòng "PR nháp riêng cho mỗi task rồi gộp lại". (Dòng CHANGELOG không cần mang `(#n)` — luật bắt buộc 10:
  commit squash trên `main` đã mang số.)
- **§5 bước 2 "không để nháp" vẫn đúng, chỉ đúng ở bước merge**: nháp trong lúc làm task, `gh pr ready` **rồi
  mới** bật auto-merge khi hạng mục xong — không mâu thuẫn với "GitHub từ chối bật auto-merge trên PR nháp".
- **§2c "chỉ một PR mở" áp nguyên vẹn cho cả PR nháp** — nháp vẫn tính là một PR đang mở. Nhánh khác (kể cả
  hạng mục khác của cùng phiên) vẫn phải chờ PR trước merge rồi mới `gh pr create`, đúng lý do 2c tồn tại
  (không hai nhánh cùng lệch nền một lúc lúc merge). Cái giá: một hạng mục nhiều task chạy lâu thì giữ chỗ hàng
  đợi PR lâu — chấp nhận được vì mỗi task vẫn merge tuần tự với các phiên khác qua cùng một PR, không phải mỗi
  task một PR chờ riêng.
- **Mỗi task vẫn phải qua đúng lệnh CI cục bộ trước khi commit** (không đợi PR báo mới biết) — quyết định rõ khi
  chốt quy trình này: một task sai chỉ lộ ra khi cả hạng mục xong là đánh đổi không chấp nhận được.
- **Task hỏng giữa chừng** (luật bắt buộc 6: vá 3 lần lòi vấn đề mới ⇒ dừng, hỏi người): task 1..k đã xanh thì
  vẫn có thể `ready` + merge phần đã xong nếu chúng tự đứng được; task hỏng tách sang hạng mục mới, không giam
  cả hạng mục chờ một task không giải quyết được.
- **Nhược điểm đã biết, không có cách vòng**: squash gộp mọi task của một hạng mục thành **một** commit trên
  `main`. Task giữa gây lỗi thì `git revert` cuốn theo mọi task khác trong cùng hạng mục — mất độ mịn so với
  một-PR-một-task cũ. Đổi lại số PR mở/merge giảm hẳn, tài liệu (CHANGELOG, session log) không còn phải rải
  theo từng task nhỏ.
- **Trạng thái sống trong `docs/thi-hanh/<mã>.md`** khi hạng mục đi qua `/thi-hanh` (bảng B cột "khi nào"); việc
  không qua `/thi-hanh` thì trạng thái sống trong chính PR nháp (checklist task trong thân PR).

## 3. Commit

- Conventional Commits: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `style`, `perf`,
  `build`, `ci`, `revert`. Scope viết **chữ thường**: `feat(software-company): ...`.
- Một commit = một thay đổi logic. Commit nhỏ, thân bài nêu *vì sao*, không chỉ *cái gì*.

## 4. Cổng kiểm thử theo mức rủi ro

| Thay đổi | Bằng chứng tối thiểu |
| --- | --- |
| Tài liệu thuần (`*.md`, docs) | Đọc lại diff, `git diff --check` |
| Prompt agent / skill / template | Đủ 7 bước `CONTRIBUTING.md` §3 (golden, eval-record, assetscan, assetbudget, subagents) + `scripts/dev-task.sh gate <gói>` |
| Code `src/**` của bất kỳ package nào | `scripts/dev-task.sh gate <gói>` (ruff + mypy + pytest coverage 100); test đỏ viết trước (`AGENTS.md` luật bắt buộc 4) |
| Schema topic / hợp đồng event | Các cổng trên + ADR + kiểm test nhất quán registry↔events |
| Đổi cổng CI | Chạy thật trên PR đó rồi đọc thời gian từng job, không đoán |
| Thêm/đổi phụ thuộc (`pyproject.toml`, `uv.lock`) | Job `dependency-review` (`.github/workflows/dependency-review.yml`) tự chạy trên PR, chặn khi thêm mới có CVE mức `high`+ — không thay `pip-audit` trong `quality` (soi toàn bộ resolve mỗi lần), chỉ chặn sớm hơn ở đúng PR gây ra thay đổi |

Không commit secret, `llm.yaml`, khóa API, hay dữ liệu thật. Không gọi provider trả phí trong test.

## 5. Pull request — năm bước làm liền một mạch

0. **Quét toàn repo trước khi tạo PR** — không chỉ đọc diff của chính mình. Bỏ bước này là chỗ đã sinh
   lỗi thật (PR #193 đỏ `metadata` vì thiếu dòng CHANGELOG khi cherry-pick sang nhánh khác, phải vá thêm
   một commit). Quét gồm:
   - `grep -rn` tên file/API vừa đổi (đổi tên, xoá, di chuyển) trên **toàn repo**, không chỉ package đang
     sửa — dẫn chiếu chết ở ADR, session log, CHANGELOG cũ vẫn được phép còn (đó là bản ghi lịch sử), nhưng
     dẫn chiếu ở tài liệu **đang sống** (README, ARCHITECTURE, CODEMAP, `.claude/`, `.gitattributes`) phải sửa.
   - `docs/thi-hanh/<mã>.md` hoặc bảng theo dõi liên quan (nếu có) đã cập nhật cột "khi nào" chưa.
   - Dòng CHANGELOG ở "Chưa phát hành" đã có cho đúng thay đổi này chưa (cổng `metadata` đỏ nếu PR không thêm
     dòng nào). Không cần ghi `(#<số PR>)`: commit squash trên `main` đã mang số.
   - `git status` sạch (không sót file định thêm mà quên `git add`, không sót file tạm không định commit).
   - `git diff --check` sạch trên **toàn diff** so với `main`, không chỉ file vừa sửa gần nhất.
   - `gh pr list --state open` — còn PR khác mở thì làm theo §2c, không tạo PR mới.
   - `gh pr list --state all --search "<từ khoá>"` + `gh issue list --state all --search "<từ khoá>"` — có PR/issue
     cũ (kể cả đã đóng) giải quyết cùng vấn đề thì đọc lý do đóng, nói rõ trong PR mới cái gì khác đi khiến lần
     này nên qua. Không mở PR thứ hai cho cùng một việc mà không nhắc tới cái trước.
1. **Kiểm tiêu đề trước khi tạo PR.** Cổng `metadata` chặn tiêu đề sai:
   ```
   ^(feat|fix|refactor|docs|test|chore|style|perf|build|ci|revert)(\([a-z0-9._/-]+\))?!?: .+
   ```
   Bẫy: scope chỉ nhận chữ thường — `fix(skillTiering)` trượt, `fix(skills)` đạt.

   Cổng `metadata` (`.github/workflows/pr-policy.yml`) còn bốn bước nữa, đọc trước khi viết thân PR:
   - **Dòng CHANGELOG**: PR phải thêm ít nhất một dòng vào `CHANGELOG.md` (`scripts/pr_changelog_check.py`;
     nhãn `no-changelog` để miễn) — đỏ nếu không thêm dòng nào. Không bắt `(#<số PR>)`: số đã nằm trong subject
     commit squash trên `main`, tra bằng `git blame CHANGELOG.md`/`git log -S"<dòng>"` (`AGENTS.md` luật bắt buộc
     10). Đừng đặt chỗ giữ kiểu `(#PENDING)` — `drift-check` đỏ.
   - **PR `fix(` chạm `companies/software-company/src/company/orchestrator.py` hoặc `orch/` phải dẫn `ADR-0034`**
     trong thân, nói rõ đụng bảng chuyển nào (K8.3). `refactor(` không bị soi: tách module là làm ĐÚNG
     theo ADR, còn `fix(` là sửa hành vi máy trạng thái — chỗ dễ lặng lẽ phá bảng chuyển nhất. Đặc tả
     gốc viết "ADR-0037"; ADR-0037 của repo là việc khác (gộp agent), ADR tách máy trạng thái là **0034**.
   - **Mục "Definition of Done" và "BÁO CÁO XÁC THỰC" của thân PR không còn ô `- [ ]`**
     (`scripts/pr_dod_check.py`; ô ghi rõ `(sau merge)` được miễn). Sửa thân PR là bước này chạy lại.
   - **Nhật ký phiên `docs/sessions/<ngày UTC>.md`** — chỉ **cảnh báo**, không chặn merge (K8.4): nhật ký
     là việc cuối phiên, không phải việc mỗi PR.
2. **Tạo PR ở trạng thái ready trước khi bật auto-merge.** GitHub từ chối bật auto-merge trên PR nháp. Việc
   một hạng mục lớn (§2d) mở PR nháp sớm rồi `gh pr ready` khi xong là ngoại lệ đã tính — bước "ready" chỉ dời
   lên trước bước này, không bỏ nó.
3. **Bật auto-merge (squash) ngay sau lệnh tạo PR** — gọi một lần, không hỏi lại. Thất bại thì
   **không bỏ mặc PR**: theo dõi CI, **xanh + không xung đột là merge (squash) ngay**.

   **Nhịp theo dõi CI: kiểm mỗi 2,5 phút (150 giây) cho tới khi có kết luận.** Không kiểm liên
   tục (tốn lượt gọi API, không nhanh hơn vì job mất vài phút), cũng không bỏ đi rồi quay lại
   sau nửa tiếng. Lệnh một vòng kiểm:

   ```bash
   gh pr checks <số PR> --watch --interval 150
   ```

   Hoặc kiểm rời từng nhịp: `gh pr checks <số PR>`. Xanh hết → merge (squash) ngay. Có check đỏ
   → đọc log (`gh run view <id> --log-failed`), tái hiện lỗi ở máy, sửa, push, rồi lại theo nhịp
   2,5 phút. Đang `queued`/`in_progress` → chờ nhịp kế tiếp, không kết luận sớm.
4. **Chỉ gộp `main` khi thật sự cần**: GitHub báo xung đột, hoặc `main` vừa đổi thứ PR này cũng
   đụng (nguy cơ xung đột ngữ nghĩa). Không gộp theo phản xạ.

**Cấm merge tay để đi tắt khi CI chưa xanh.** Đó là điều duy nhất bị cấm ở bước merge.

PR là của người tạo: CI đỏ thì đọc log, tái hiện lỗi ở máy, sửa và push cho tới khi xanh —
không để PR nằm đỏ chờ người khác.

Merge sạch (không xung đột) thì **không** chạy lại toàn bộ cổng ở máy — CI đã chạy trên kết quả
đã gộp. Merge có xung đột, hoặc `main` chạm file PR cũng chạm → chạy lại đủ cổng ở máy.

## 6. Definition of Done

- Thay đổi khớp đặc tả/ADR; điểm lệch được ghi rõ.
- Test mới chứng minh hành vi (đỏ trước, xanh sau); `scripts/dev-task.sh gate <gói>` xanh.
- Đã tự đọc lại diff; chỉ gồm thay đổi thuộc phạm vi.
- Không secret, không debug log, không file sinh tự động lọt vào.
- Tài liệu (`README.md`, `docs/`, ADR) cập nhật theo thay đổi.
- Breaking change được gọi tên kèm cách chuyển đổi.

## 7. Merge và sau merge

- Mặc định **squash merge**; xoá nhánh sau khi merge.
- Sau merge, kiểm `main` còn xanh; hỏng thì ưu tiên revert rồi điều tra trong PR mới.
- Tag `vX.Y.Z` khi phát hành mốc (`version` trong `companies/software-company/pyproject.toml`).

## 8. Việc cần bật trên GitHub (một lần) — và cách biết nó CÓ THẬT

Quy trình trên giả định `main` có bảo vệ nhánh. Cấu hình này **không nằm trong git**, nên "đã bật" phải kiểm được
bằng máy, không chỉ là lời hứa (chuyện đã xảy ra: `TRAPS.md` §3, ba dòng "ruleset"). Hai lớp:

1. **Ruleset import được** — `.github/rulesets/main.json` là nguồn sự thật, đi qua PR như code.
   Bật: Settings → Rules → Rulesets → **New ruleset → Import a ruleset** → chọn file đó → Create.
   Nội dung: bắt buộc PR (**0 approval** — xem ô dưới, thread review phải resolve) ·
   required status checks `quality` + `metadata` · cấm xoá và cấm force-push `main` ·
   **không ai được bypass, kể cả admin** (`bypass_actors` rỗng) · **tắt** "up to date" (`strict: false`) để PR khác
   merge không bắt mọi PR đang mở gộp `main` rồi chờ CI lại.
2. **Job `protection-guard` trong CI**, hai vế. `quality` cần nó xanh.
   - **Vế 1 — đã có hiệu lực chưa:** đọc rule đang áp lên nhánh mặc định qua API, **đỏ khi thiếu** bốn rule bất
     biến hoặc thiếu bất kỳ required status check nào **khai trong file**. Chưa import ruleset thì mọi PR đỏ —
     đó là chủ đích. Danh sách check đọc từ file chứ không hard-code, nên thêm/bớt check không cần sửa workflow.
   - **Vế 2 — file và ruleset thật có khớp không (đối chiếu hai chiều):**
     rule khai trong file mà **không** áp trên nhánh ⇒ **đỏ** (bảo vệ yếu hơn thứ repo khai);
     rule đang áp mà **không** có trong file ⇒ **cảnh báo** (không yếu đi, nhưng import lại sẽ xoá mất nó);
     `allowed_merge_methods` thật khác file ⇒ **đỏ** (so tham số, không chỉ loại rule — #374 và #399 vào `main`
     bằng merge commit trong khi file chỉ cho `squash`, job vẫn xanh tới audit 2026-10-10).
     **Hiện trạng 2026-10-10:** ruleset đang áp cho cả `merge`, `rebase`, `squash` (đo qua
     `GET /repos/<owner>/<repo>/rules/branches/main`), nên file khai đúng ba giá trị đó — file là bản chụp của
     thứ đang áp, không phải điều ước. Quy trình vẫn là squash (`AGENTS.md` luật cấm 1); muốn ruleset ép squash
     thì chủ repo sửa trong Settings → Rules → Rulesets → ruleset `main` → "Allowed merge methods" chỉ còn
     Squash, **rồi** đổi file về `["squash"]` trong cùng một PR — job này đỏ ngay khi hai bên lệch, theo cả hai
     chiều.
     Cần vế này vì sửa ruleset trong UI có thể làm rơi một rule mà không báo gì (`TRAPS.md` §3).

Hai nút vẫn phải bật tay trong Settings → General (không thuộc ruleset): **Allow auto-merge** và
**Automatically delete head branches**.

### Vì sao `required_approving_review_count` = 0

Không phải hạ tiêu chuẩn: repo có **đúng một cộng tác viên**, GitHub không cho tự duyệt PR của chính mình và
`bypass_actors` cố ý rỗng, nên 1 approval **khoá vĩnh viễn mọi PR** vào `main`. Đặt 0 vẫn giữ
`required_status_checks` và rule `pull_request` (bắt buộc qua PR — số approval chỉ là một tham số của nó); thứ mất
đi là **four-eyes**, vốn không tồn tại khi chỉ có một người. Chuyện đã xảy ra (PR #29, #40): `TRAPS.md` §3.

**Nâng lại lên 1 (hoặc 2) ngay khi có người thứ hai thật** trong repo — lúc đó nó mới có nghĩa. Cách đổi: sửa
`required_approving_review_count` trong file JSON qua PR **rồi import lại** (ruleset cùng tên sẽ được cập nhật).
Guard không kiểm số approval, chỉ kiểm **có** rule `pull_request` — nên đổi số không làm CI đỏ.

⚠️ **Thứ tự bắt buộc nếu lỡ khoá lại:** file JSON trong repo chỉ là bản nguồn để nhập; sửa nó cũng cần một PR,
mà PR thì đang bị khoá. Phải **sửa ruleset đang chạy trong Settings trước**, rồi mới sửa được file.

### File và ruleset thật phải khớp

File này được **đối chiếu với `GET /repos/:owner/:repo/rulesets/:id`** bằng máy, không viết theo trí nhớ — GitHub
tự thêm tham số mà bản viết tay hay thiếu (`required_reviewers`, `require_extra_approval_for_unattributed_changes`
của rule `pull_request`).

**Bốn rule là đủ:** `deletion` · `non_fast_forward` · `pull_request` · `required_status_checks`.
`copilot_code_review` **đã quyết định không dùng** (2026-09-05), gỡ khỏi cả ruleset lẫn file. Muốn dùng lại thì
thêm vào **cả hai chỗ** — thêm một chỗ thôi sẽ bị vế 2 của `protection-guard` bắt.

🔍 PR **vẫn** `blocked` dù mọi check xanh và approval = 0 → nghi `require_extra_approval_for_unattributed_changes =
true` trước tiên: nó đòi thêm một approval khi PR chứa thay đổi không gán được cho một tài khoản (`author.login`
của API commit), nhất là khi người mở PR và người tạo commit là hai tài khoản khác nhau. Hiện không cắn: commit
gán đúng vào tài khoản `claude`.
