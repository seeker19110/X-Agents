@AGENTS.md

# Ghi chú riêng cho Claude Code

Luật đầy đủ nằm ở `AGENTS.md` (nhập ở dòng đầu). Dưới đây chỉ là thứ khác biệt khi agent là Claude Code.

## Bảy điều nếu chỉ đọc được bảy dòng

1. Không commit lên `main`; nhánh → PR → auto-merge squash. Scope PR một từ chữ thường. Việc lớn nhiều task
   liên quan: **một nhánh cho cả hạng mục** (không phải một nhánh mỗi task), PR nháp ngay sau task đầu, `gh pr
   ready` khi hạng mục xong (`docs/QUY-TRINH-GIT.md` §2d, ADR-0012) — vẫn tính là một PR mở với luật 2b dưới đây.
2. Mỗi phiên một `git worktree` — có phiên khác đang mở cùng thư mục này (`git worktree list` để kiểm). Có tool
   worktree riêng của harness (`EnterWorktree`/tương đương) thì dùng nó trước, đừng tự `git worktree add` —
   tool native lo cả đặt chỗ, tạo nhánh, dọn dẹp mà `git` tay không biết tới.
2b. Chỉ một PR mở tại một thời điểm: `gh pr list --state open` trước khi mở PR mới; PR khác đang mở thì
   chờ nó merge, rồi `git fetch` + `git rebase origin/main` trên nhánh mình trước khi `gh pr create` (`docs/QUY-TRINH-GIT.md` §2c).
   Trước khi tạo PR: cũng kiểm PR/issue đã đóng cùng vấn đề (`AGENTS.md` luật bắt buộc 11) — trùng thì nói rõ
   cái gì khác đi, đừng lặng lẽ mở PR thứ hai.
3. Không commit `llm.yaml`, `*.sqlite*`, bí mật. Không hạ `fail_under = 100`.
4. Sửa `agents/`/`skills/` → 7 bước `CONTRIBUTING.md` §3, không bỏ bước.
5. **TDD cho mọi code, không riêng bugfix**: viết test đỏ trước → code tối thiểu cho xanh → refactor. Không có
   test đỏ đi trước thì chưa được viết code sản xuất (`AGENTS.md` luật bắt buộc 4). Vá 3 lần liên tiếp vẫn lòi
   vấn đề mới chỗ khác → dừng, hỏi người, đừng vá lần 4 một mình (luật bắt buộc 6).
6. "Xong" phải có output lệnh vừa chạy trong chính lượt này. Không có thì chưa xong. Một lệnh cho cổng:
   `scripts/dev-task.sh gate <gói>` (`company|gateway|console|core|keeper|all`) — nó khớp đúng `ci.yml`, đừng
   tự gõ `ruff`/`mypy`/`pytest` rời rồi nhớ nhầm biến thể của package.
7. Trước khi sửa lỗi lạ: đọc `TRAPS.md` — 80% khả năng nó đã có tên ở đó, kể cả câu bạn đang định tự biện hộ
   (`TRAPS.md` §6).

## Hàng rào tự động (chỉ Claude Code có)

`.claude/settings.json` nối ba hook ở `.claude/hooks/` — bảng đầy đủ ở `AGENTS.md` §"Hàng rào thi hành". Tóm
tắt: `block-dangerous-git.sh` chặn mọi thứ ghi vào `main` + `reset --hard` + `*--abort`; `pre-commit-gate.sh`
chặn commit khi đứng trên `main`, staged có file cấm, diff hạ `fail_under`, hoặc cổng đỏ — cổng chạy cho gói bị
đụng, gói import nó, và console (giữ cổng cấp repo nên chạy cả khi commit chỉ sửa tài liệu, ~1,5 phút);
`auto-format.sh` format file vừa sửa nếu file vốn đã sạch `ruff format` (file gọn một dòng thì để nguyên).
Bị chặn → **sửa cho đúng luật**, đừng lách bằng `--no-verify`/`ALLOW_DANGEROUS_GIT=1` rồi im lặng; hook chặn
oan thì sửa hook kèm test trong `test_cong_khung.py`.

## Skill và trợ lý có sẵn trong repo

- `/gate` — cổng trước commit/PR; `/debug` — vòng chẩn đoán bug khó; `/adr` — viết ADR đúng khuôn repo.
- `/no-ky-thuat` — sổ nợ kỹ thuật cố ý: thu mọi marker `no-ky-thuat:` thành bảng, gắn cờ marker
  không nêu điều kiện quay lại (quy ước ở `AGENTS.md` mục "Nợ kỹ thuật cố ý").
- `/gate-brief <subject>` — hồ sơ bằng chứng chỉ đọc cho một human gate của software-company; không ký thay người.
- `/gate-review [subject]` — reviewer có chữ ký (ADR gốc 0024): một phiên Claude **mới, tách riêng** mở lại ticket/dự án
  bị chặn trong phạm vi hẹp; actor `reviewer:<id>`, không bao giờ `human:*`. Phiên đã sửa code/viết hint thì không chạy.
  Phạm vi `rong` (ADR gốc 0025, `COMPANY_GATE_REVIEWER_SCOPE=rong`): phiên chính quyết mọi gate trừ spec, ký `reviewer:phien-chinh`.
- `/thi-hanh <mã> [đề bài]` — thi hành một đề bài từ đặc tả tới mọi PR merge theo `docs/KHUON-THI-HANH.md`: phiên chính
  điều phối, subagent thực thi theo mức C1/C2/C3, người ra lệnh một lần. Trạng thái ở `docs/thi-hanh/<mã>.md`.
- `.claude/agents/sc-*` — 10 trợ lý kiểm duyệt chỉ đọc (một per agent + một per gate), sinh tự động; gọi khi cần
  góc nhìn chuyên môn về một PR/spec/release. Chúng **chỉ đọc**, không quyết định.
- `.claude/launch.json` — cấu hình dev server cho browser pane.

- `/product-goal <mã> <mục tiêu>` — hợp đồng chất lượng theo dự án/ngành, nối `/thi-hanh`; xem `docs/PRODUCT-EXCELLENCE.md`. Không che `/goal` native.

## ECC — vendor chọn lọc, lớp thêm chứ không phải luật (ADR gốc 0028)

23 mục chọn lọc của ECC (`affaan-m/ECC`, MIT) nằm thẳng trong `.claude/` với tiền tố `ecc-`. Ghim đúng một commit ở
`docs/integrations/ecc.lock.json`. Không có plugin, hook hay `node`. Phiên Claude Code on the web nạp đủ (đo
2026-10-02, ADR 0028 §"Đo").

- **Gọi:** lệnh `/ecc-python-review`, `/ecc-review-pr`, `/ecc-build-fix`; skill `/ecc-python-testing`,
  `/ecc-security-review`, `/ecc-agent-introspection-debugging`…; agent `ecc-code-reviewer`, `ecc-silent-failure-hunter`…
  Danh sách kèm lý do: `select` trong lock. Tiền tố `ecc:` của plugin cũ (ADR 0027) không còn.
- **Luật repo thắng khi trùng.** Coverage `fail_under = 100`, không phải 80%. Test đỏ trước. PR theo
  `docs/QUY-TRINH-GIT.md`. Không xoá code ngoài yêu cầu. Mỗi tệp vendor mang câu này ngay đầu.
- **Mục ECC bị nhắc mà không có tệp `ecc-<tên>`** là mục repo không vendor, có lý do trong `rejected` của lock (vd
  `tdd-workflow` lấy 80% làm trục, `orch-*` trùng `/thi-hanh`). Dùng `/gate`, `/debug`, `/adr`, `/thi-hanh` hoặc bỏ qua.
- **Bản dẫn xuất, không sửa tay** (luật cấm 5). Muốn thêm/bớt mục hay nâng bản: sửa lock, chạy `make ecc-vendor`, đọc
  diff `.claude/` như mã người lạ, mở PR. `test_cong_ecc.py` đỏ ngay khi sha256 lệch lock; job CI `ecc-check` sinh
  lại từ commit ghim rồi so.
- Agent của công ty (`claude -p`) **không** thấy mục `ecc-*`: mọi chế độ chạy `--restricted` (đo được 0, giống `sc-*`).

## Thao tác trên Windows

- Shell chính là PowerShell 7; Bash tool là Git Bash. `cd` trong Bash **không giữ** qua lệnh sau — dùng đường dẫn
  tuyệt đối hoặc `cd … && …` trong cùng lệnh.
- Heredoc bash chứa `'''` hoặc nhiều backtick hay vỡ: patch dài → ghi file vào scratchpad rồi `python file.py`.
- Lệnh `taskkill`/cron/wakeup có thể bị classifier chặn — không lách; hỏi người dùng đúng lệnh.
- In tiếng Việt lỗi mã hoá → `PYTHONIOENCODING=utf-8`.

## Khi vận hành công ty (không phải sửa code)

- Bật console thì bật ngay `orchestrator run --watch` — không thì việc giao nằm im.
- Duyệt gate: lý do = root_cause + decision + hint, ≥ 20 ký tự; "ok" là hint rỗng cho agent.
- Trước khi tin dashboard: hỏi *"chạy cho tôi xem"*. Số xanh có thể xanh vì rỗng.
- Sửa tay trong worktree của ticket: commit + takeover **trước**, duyệt gate **sau** (duyệt trước là bị reset).
- Muốn đổi hành vi agent: đổi tài liệu nó đọc qua đúng vai (CR → `product` pha spec ghi prd), không ghi tay blackboard.

## Bộ nhớ

Bộ nhớ dài hạn của Claude nằm ngoài repo (`~/.claude/projects/.../memory/`). Bài học đáng để repo giữ thì đưa vào
`TRAPS.md` — bộ nhớ là của một người, `TRAPS.md` là của mọi phiên.

## Compact Instructions

Dùng auto-compact native, cửa sổ **300000 token mỗi phiên** trong `.claude/settings.json`; không phải token
cộng dồn của ticket và không tăng giới hạn prompt của agent. Cách kiểm tra: `docs/AUTO-COMPACT.md`.

Khi compact, giữ mục tiêu, spec đã duyệt, giới hạn quyền/ngân sách, quyết định kiến trúc, việc dở và bước kế
tiếp; giữ branch/worktree/HEAD, file đã đổi, PR, lệnh test + kết quả + đường dẫn bằng chứng. Ghi rõ phần
chưa kiểm được; không biến lời khai thành bằng chứng. Không đưa khoá, token hay toàn văn log/diff vào bản tóm tắt.

Cập nhật `docs/thi-hanh/<mã>.md` và nhật ký phù hợp trong `docs/sessions/` ở mỗi mốc công việc, không đợi tới
khi cửa sổ đầy. Dữ liệu khách/bí mật không được ghi vào tài liệu đã theo dõi bởi git. Execution journal,
bus và artifact hiện có là nguồn trạng thái bền; bản tóm tắt chỉ dẫn đường, không ghi đè chúng.

Sau compact, **đọc lại** `AGENTS.md`, `CLAUDE.md` của package đang sửa và đúng hồ sơ thi hành/nhật ký; đối chiếu
`git status`, branch/worktree/HEAD, trạng thái task/gate và bằng chứng trước khi tiếp tục. Không chạy lại tác vụ
đã hoàn thành chỉ vì mất lịch sử hội thoại; không tự duyệt spec, đổi quyền hay đánh dấu xong vì vừa compact.
