# AGENTS.md — luật cho mọi agent làm việc trong repo này

Đọc file này trước khi chạm vào bất kỳ file nào. Nó ngắn vì mọi chi tiết đã có chỗ riêng; ở đây chỉ là
**điều cấm, điều bắt buộc, và đi đâu để biết thêm**. Bộ khung 10 file: `AGENTS.md` (luật) · `CLAUDE.md` (luật cho
Claude Code, nhập file này) · `TRAPS.md` (bẫy đã mắc) · `ARCHITECTURE.md` (bản đồ hệ) · `CODEMAP.md` (muốn đổi X thì
sửa ở đâu) · `CHANGELOG.md` (đã đổi gì) · `docs/TASK-PACK.md` (gói việc) · `docs/PROMPT-SHEET.md` (câu lệnh chuẩn) ·
`docs/sessions/` (nhật ký phiên) · `docs/NGON-NGU.md` (thuật ngữ và cách gọi phải tránh). Mỗi package con có bộ
`CLAUDE.md`, `TRAPS.md`, `CODEMAP.md`, `ARCHITECTURE.md` riêng — câu này có cổng canh
(`platform/console/tests/test_cong_repo.py`) nên không tự lệch được: thiếu file nào thì cổng đỏ, không phải
sửa câu cho khớp thực tế lệch.

## Repo này là gì

X-Agents: hub các "công ty AI" đa agent. Năm package Python trong **một uv workspace** (một `pyproject.toml`,
một `uv.lock`, một `.venv` ở gốc):

| Thư mục | Package | Là gì |
|---|---|---|
| `companies/software-company/` | `company` | công ty gia công phần mềm: yêu cầu → PRD → ticket → code thật trên worktree → review → release → khách ký |
| `platform/gateway/` | `gateway` | proxy OpenAI-compatible xoay vòng tài khoản Google Antigravity |
| `platform/console/` | `console` | trực ban hợp nhất: một trang web cục bộ nhìn công ty, duyệt gate tại chỗ |
| `platform/xagents-core/` | `xagents_core` | lõi chung công ty dùng (bus, llm, runner, guard, gate) — dựng xong qua bảy bước K3 (#198), xem `docs/adr/0001-loi-chung-xagents-core.md` |
| `companies/keeper/` | `keeper` | công ty bảo trì: tín hiệu → ticket bảo trì → patch có bằng chứng đo hai chiều → PR; khách hàng số 0 là chính repo này |

Nguyên tắc chung (chi tiết ở `ARCHITECTURE.md`): model quyết định – code hành động; prompt là code; guardrail có
hạn mức; self-hosted, resume được; trung lập provider.

## Mục tiêu chất lượng sản phẩm

Khi giao một mục tiêu sản phẩm, áp dụng `docs/PRODUCT-EXCELLENCE.md` (profile, Design Brief, tiêu chí đo,
Ready/Done/Complete). Dùng `/product-goal` hoặc nối `/thi-hanh`; không tạo command che `/goal` native.
Adapter `company.quality_execution` (ADR-0018) không thay HumanGate hay sàn tự duyệt ADR-0043. Thiếu bằng chứng
là chưa đạt, không hạ chuẩn để kết thúc. Nguồn template: `docs/reports/2026-09-25-projects-template-adoption.md`.

## Luật cấm

1. **Không commit thẳng `main`.** Mọi thay đổi: nhánh → PR → CI xanh → squash merge. `git push` lên `main` bị
   ruleset từ chối. Quy trình: `docs/QUY-TRINH-GIT.md`.
2. **Không dùng chung một clone với phiên khác.** Mỗi phiên agent một `git worktree` (`docs/QUY-TRINH-GIT.md` §2b).
   Thấy nhánh mình không tạo, hay `checkout` trong reflog mình không gọi → dừng, đừng commit.
3. **Không commit** `llm.yaml`, `media.yaml`, `*.sqlite*`, `company.artifacts/`, khoá/token, dữ liệu khách thật.
   Chỉ commit `*.example.yaml`. gitleaks quét cả lịch sử — lỡ commit rồi xoá vẫn đỏ (`SECURITY.md`).
4. **Không gọi provider trả phí trong test.** Provider `fake` + bản ghi eval đủ chạy offline toàn bộ.
5. **Không sửa tay bản dẫn xuất**: `.claude/agents/sc-*.md` sinh từ `companies/software-company/agents/`, `skills/`,
   `gates/checklists.md` bằng `make subagents`; `tests/golden/` sinh bằng `make golden`; tệp `ecc-*` trong
   `.claude/skills/`, `.claude/commands/`, `.claude/agents/` cùng `docs/integrations/ecc.LICENSE` sinh từ
   `docs/integrations/ecc.lock.json` bằng `make ecc-vendor` (ADR gốc 0028). Sửa nguồn rồi sinh lại.
6. **Không hạ ngưỡng coverage để PR qua cổng.** `fail_under = 100` ở cả năm package; mất một dòng phủ là CI đỏ
   — thêm test, không hạ số.
7. **Không "sửa" code cạnh bên.** Mỗi dòng đổi phải truy được về yêu cầu. Thấy dead code thì nói, đừng xoá.
8. **Không tin lời khai.** Của model, của agent, của chính mình. "Tests pass" cần output lệnh vừa chạy; "đã
   deploy" cần bằng chứng máy sinh (`verified_by=workspace|orchestrator`). Chưa chạy thì chưa được nói.
   Trước khi nói bất kỳ câu nào kiểu "xong/đã sửa/pass/đã deploy" — kể cả một câu cảm thán ("Ổn rồi!", "Ngon!") —
   đi qua đúng năm bước, không bỏ bước nào:
   1. Xác định lệnh nào **chứng minh** được câu này.
   2. Chạy lệnh đó **đầy đủ**, ngay trong lượt hiện tại — không dùng kết quả của lượt trước.
   3. Đọc **toàn bộ** output, không chỉ dòng cuối; đếm số lỗi/số fail thật.
   4. Output có khớp đúng câu định nói không? Không khớp → nói đúng trạng thái thật kèm bằng chứng, không nói
      câu ban đầu.
   5. Chỉ sau bước 4 mới được nói câu đó — và nói kèm bằng chứng, không nói suông.
   Bỏ một bước ở trên = nói dối, không phải "gần đúng".

   Bước 4 là bước hay bị bỏ nhất vì nó chỉ diễn ra trong đầu — không có vật thể nào để người sau kiểm. Khi
   câu định nói là "xong / sẵn sàng merge", viết bước 4 ra thành khối này, **điền bằng output vừa chạy trong
   lượt hiện tại**, không chép lại từ lượt trước:

   ```
   BÁO CÁO XÁC THỰC — <nhánh> @ <sha>
   make lint ✅/❌ (ruff: .. | mypy: .. file)
   make test ✅/❌ (X passed, Y failed, Z skipped)
   make cov  ✅/❌ (fail_under = 100 — đạt/thiếu <n> dòng ở <file>)
   evals --replay --strict ✅/❌/n-a   | subagents check ✅/❌/n-a   | assetscan scan ✅/❌/n-a
   Test đỏ TRƯỚC khi sửa (luật bắt buộc 4, đo hai chiều) ✅/❌/n-a — tên ca: <..>
   Bảy bước CONTRIBUTING §3 (nếu chạm agents/ hoặc skills/) ✅/n-a
   CHANGELOG + docs/sessions/<ngày>.md trong CHÍNH PR này (luật 10) ✅/❌
   KẾT LUẬN: Sẵn sàng  /  Cần xử lý: <..>
   ```

   `n-a` chỉ hợp lệ khi PR không chạm phần đó (vd PR thuần tài liệu không đụng agent → `evals`/`subagents`/
   `assetscan` là `n-a`); `n-a` không phải cách viết khác của "chưa chạy". Bất kỳ ❌ nào ⇒ **chưa được nói
   "xong", chưa bật auto-merge** — sửa, chạy lại toàn bộ, điền lại khối. Khối này không thay cổng CI; nó là
   cách biến bước 4 thành việc cơ học thay vì một phán đoán tự chấm.

## Luật bắt buộc

1. **Sửa `agents/` hoặc `skills/` → checklist 7 bước** ở `CONTRIBUTING.md` §3: tăng `version` → `make golden` →
   `make eval-record AGENT=<id>` (model thật) → `make assetscan` → `make assetbudget` → `make subagents` → commit cả
   golden + recordings + `.claude/agents/`. Bỏ một bước là CI đỏ có chủ đích.
2. **Thay đổi kiến trúc → ADR trước** (`<công ty>/docs/adr/`), link trong PR. Sửa lỗi nhỏ, chỉnh prompt, sửa tài
   liệu thì không cần.
3. **Chạy đúng lệnh CI trước khi push** — một lệnh, không phải ba: `scripts/dev-task.sh gate <gói>`
   (`gói`: `company|gateway|console|core|keeper|all`; bỏ trống = `all`). Script giữ lệnh khớp đúng `ci.yml`
   (`ruff check src tests` → `mypy src/<module> --ignore-missing-imports` → `pytest -q --cov`, riêng
   software-company thêm `-n auto`) nên không phải nhớ biến thể của từng package; `DEV_TASK_DRY_RUN=1` để xem
   trước lệnh sẽ chạy. Windows thiếu 2 dòng POSIX trong coverage là bình thường.
4. **TDD là quy trình mặc định cho MỌI code, không chỉ khi sửa lỗi: viết test trước, thấy nó đỏ, rồi mới viết code
   để nó xanh.** Luật cứng:
   ```
   KHÔNG CODE SẢN XUẤT NÀO ĐƯỢC VIẾT TRƯỚC KHI CÓ TEST ĐỎ CHO NÓ
   ```
   - **ĐỎ** — viết một test tối thiểu tả đúng hành vi còn thiếu (một hành vi, tên rõ, code thật — không mock
     trừ khi không tránh được). Chạy nó, đọc kỹ lý do đỏ: đỏ vì tính năng chưa có, không phải vì gõ sai tên.
     Test xanh ngay từ đầu ⇒ đang test hành vi đã tồn tại, sửa lại test.
   - **XANH** — viết code **tối thiểu vừa đủ** để qua đúng test đó. Không thêm tham số/nhánh mà test chưa đòi,
     không "tiện tay" refactor chỗ khác. Chạy lại, xác nhận xanh và các test khác không đỏ theo.
   - **REFACTOR** — chỉ sau khi xanh: gọn tên, gỡ trùng lặp, tách hàm. Giữ nguyên tập test xanh, không thêm
     hành vi mới ở bước này.
   - Việc "quá đơn giản nên khỏi test", "test sau cũng như nhau", "đã tự tay thử rồi" đều là chỗ né luật —
     test viết sau khi code đã chạy chỉ chứng minh nó xanh ngay từ lần đầu, không chứng minh nó **từng bắt
     được lỗi**. Xem bảng biện hộ ở `TRAPS.md` §6 trước khi tự thuyết phục mình là ngoại lệ.
   - Ngoại lệ cần hỏi người trước: prototype vứt đi, code sinh tự động (`.claude/agents/sc-*`, `tests/golden/`
     — luật cấm 5 đã cấm sửa tay), file cấu hình thuần.
   - Bẫy: đây vẫn là **luật 4 cũ** (đo hai chiều) mở rộng ra toàn bộ code, không chỉ bugfix — tắt bản sửa/tính
     năng → test phải đỏ; bật lại → xanh; ghi kết quả cả hai chiều vào commit message.
5. **Sửa một lỗi thì rà cả họ lỗi đó**: viết câu hỏi kiểm tra rút từ lỗi vừa sửa, grep mọi chỗ dùng cùng cơ chế,
   ghi lại cả chỗ an toàn và vì sao (`TRAPS.md` §1).
6. **Đo trước khi sửa**: gặp lỗi không rõ → tái hiện với đối chứng, tách từng biến. Suy từ thông điệp lỗi đã sai 6/6
   lần (`TRAPS.md` §2). **Thử vá 3 lần liên tiếp mà mỗi lần lại lòi ra vấn đề mới ở chỗ khác ⇒ dừng, đây không còn
   là bug, đây là kiến trúc sai.** Không thử vá lần 4 một mình — mang giả thiết ra hỏi người trước khi vá tiếp.
7. **Tiêu đề PR**: `^(feat|fix|refactor|docs|test|chore|style|perf|build|ci|revert)(\([a-z0-9._/-]+\))?!?: .+` —
   scope **một từ, chữ thường** (`fix(company,console)` bị chặn). Bật auto-merge squash ngay sau khi tạo; thất bại
   thì theo dõi `gh pr checks <n> --watch --interval 150` tới khi kết luận.
8. **Sau `git push`, kiểm commit đã vào PR** (`gh pr view <n> --json commits`) trước khi báo xong.
9. **Cuối phiên**: ghi `docs/sessions/<ngày>.md` (việc dở, PR mở, thứ người sau không được quên) và một dòng
   `CHANGELOG.md` cho mỗi PR đã merge.
10. **Tài liệu đi CÙNG PR, không đi sau nó**: dòng `CHANGELOG.md`, `docs/sessions/<ngày>.md` và số liệu
   `README.md` nằm trong **chính PR** làm ra thay đổi, không để lại cho một PR dọn dẹp. Số PR chỉ có sau khi
   tạo PR, nên ngay sau `gh pr create`: điền `(#<n>)` vào dòng CHANGELOG (và nhật ký phiên) rồi **commit tiếp
   vào chính PR đó** trước khi nó merge — không phải mở PR khác để vá số. Đẩy xong thì kiểm commit đã vào PR
   (luật 8). Dòng CHANGELOG xếp mới nhất trên cùng theo **thời điểm merge**, không theo thứ tự tạo PR.
11. **Trước khi mở PR, tìm PR/issue trùng — đóng hay mở đều tính.** `gh pr list --state all --search "<từ khoá>"`
   và `gh issue list --state all --search "<từ khoá>"`. Có PR cũ từng đóng vì cùng vấn đề → đọc lý do đóng, nói
   rõ trong PR mới cái gì khác đi khiến lần này nên qua; không lặng lẽ mở PR thứ hai cho cùng một việc.

## Nợ kỹ thuật cố ý

`TRAPS.md` ghi **bẫy đã mắc** — thứ đã cắn rồi, viết lại để lần sau đừng cắn nữa. Repo không có chỗ nào ghi thứ
ngược lại: **nợ cố ý tạo ra** — một đơn giản hoá hôm nay *không sai*, nhưng có **trần đã biết**, và sẽ sai khi
vượt trần đó. Nó không phải bẫy (chưa ai vấp), không phải TODO (TODO không nói vượt cái gì thì phải quay lại).
Không ghi thành hình thì cái trần chỉ nằm trong đầu một người, và mất cùng phiên của người đó.

Khuôn: **một dòng, ngay tại chỗ cắt góc**, không phải ở file kế hoạch nào khác.

```
# no-ky-thuat: <trần đã biết>, <điều kiện quay lại>
// no-ky-thuat: <trần đã biết>, <điều kiện quay lại>
```

Ví dụ đúng khuôn:

```python
# no-ky-thuat: quét tuyến tính cả bảng, ổn tới ~2k ticket, quay lại khi company.sqlite vượt 2k dòng ticket
```

Ba luật của marker:

1. **Phải có dấu phẩy.** Trước phẩy là trần (đo được), sau phẩy là điều kiện quay lại (kiểm được). Thiếu vế sau
   thì marker tự mục — `/no-ky-thuat` gắn cờ `no-trigger` cho đúng những dòng đó.
2. **Chỉ cho cắt góc có trần đã biết**, không phải mọi TODO. "Chưa làm" dùng TODO; "đã làm, biết nó gãy ở đâu"
   mới dùng marker này.
3. **Tên không dấu** để `grep` được trên mọi shell (Windows `PYTHONIOENCODING`, `CLAUDE.md`). Regex thu hoạch:
   `(#|//) ?no-ky-thuat:`.

Đọc sổ: `/no-ky-thuat` (`.claude/commands/no-ky-thuat.md`) — chỉ đọc, không sửa gì. Sổ rỗng nghĩa là **0
marker**, không phải 0 nợ.

## Hàng rào thi hành (không phải lời nhắc)

Luật cấm 1, 3, 6 và luật bắt buộc 3 ở trên **có cơ chế chặn**, không chỉ là chữ. Claude Code nạp
`.claude/hooks/` qua `.claude/settings.json`:

| Hook | Chặn gì |
|---|---|
| `block-dangerous-git.sh` | `git push` (kể cả force) vào `main`/`master`; `reset --hard`; `merge\|rebase\|cherry-pick --abort` |
| `pre-commit-gate.sh` | commit khi: đang đứng trên `main` · staged có `llm.yaml`/`media.yaml`/`*.sqlite*`/`company.artifacts/` · diff hạ `fail_under` · cổng đỏ ở gói bị đụng, gói import nó, hoặc console (luôn chạy, kể cả commit chỉ sửa tài liệu) |
| `auto-format.sh` | (không chặn) format file vừa sửa qua `dev-task.sh format-file` — chỉ khi bản trong index vốn đã sạch `ruff format` hoặc file mới chưa track |

Đường thoát tường minh: `ALLOW_DANGEROUS_GIT=1`, hoặc `--no-verify` trong lệnh commit — dùng thì **phải nói rõ
lý do cho người dùng**, không lặng lẽ lách. Hook chặn oan → sửa hook kèm test, đừng tắt nó.

**Agent không phải Claude Code không có hook** (Codex, Cursor, Gemini/Antigravity…): bốn phép kiểm trên phải tự
làm bằng tay như luật cứng — xem `GEMINI.md`, và luật ở `.cursorrules`/`.windsurfrules`/`.clinerules` cùng trỏ
về file này.

## Chạy cái gì ở đâu

```bash
uv sync                          # một lần ở gốc
make test                        # cả năm package; hoặc cd <pkg> && uv run pytest -q
cd companies/software-company && uv run python -m company.orchestrator status      # PHẢI ở trong companies/software-company/ (gốc có company.sqlite rỗng)
cd platform/console && uv run python -m console --allow-decide                    # trực ban; bật console thì bật luôn orchestrator run --watch
```

Lệnh dừng khẩn, lịch trực, giới hạn đã biết: `docs/TRUC-VA-DUNG-KHAN.md`. Cấu hình model theo gói tài khoản:
`docs/DIEU-PHOI-MODEL.md`. Hướng dẫn vận hành từ đầu: `docs/HUONG-DAN-VAN-HANH.md`.

## Khi bối rối

Nêu giả định thành lời và đi tiếp với giả định đó, trừ khi sai thì công việc thành vô dụng — lúc đó hỏi.
Không hỏi "tiếp không?"; không tóm tắt tiến độ thay cho làm việc. Bốn thứ được phép dừng lại hỏi người:
thao tác không đảo ngược được, việc nhạy cảm bảo mật, tác động ra ngoài worktree (merge/push/publish), và kế
hoạch hỏng tới mức mọi hướng đều là đoán.
