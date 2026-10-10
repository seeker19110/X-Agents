# Đối chiếu `seeker19110/projects-template` lần 4 — 2026-10-10

Yêu cầu: *"nghiên cứu repo project-template có gì tốt tích hợp sâu vào dự án này"*. Làm theo `docs/PROMPT-SHEET.md`
§H: ba cột **đã có và sâu hơn / đã có nhưng nông hơn / chưa có**; "chưa có" chỉ được lấy khi chỉ ra **sự cố đã xảy
ra ở đây**. Không cài gì; kết luận là sửa code/tài liệu của chính repo, test đỏ trước.

Nguồn: `seeker19110/projects-template` (repository ID 1283493926; `project-template` redirect tới đây) @
`c755c90e556e60b3ea7519c0dbffdb9816170d58` (2026-10-10), **88 commit sau mốc ghim** `23accce8` của
`docs/integrations/projects-template.lock.json`. Đích: `X-Agents` @ `433faa3` (`main` sau #400).

Ba lần trước: `2026-09-14-doi-chieu-projects-template.md` (lấy 1/25: khuôn BÁO CÁO XÁC THỰC), `2026-09-25-…-adoption.md`
(#335: DeliveryContract Ready/Done/Complete, ghim lock), #294 (chuyển hai hook sang). Lần này **chỉ xét phần template
đổi sau 23accce8**, không xét lại thứ đã kết luận.

## 1. Phương pháp — đo, không đọc

Tài liệu của template tự kể "đã vá 7 biến thể lọt" (TRAPS 62 của họ). Không tin: chạy từng biến thể qua **hook thật
của repo này** bằng payload JSON `{"tool_input":{"command":…}}` (script scratchpad, 29 ca chặn/không chặn + 4 ca
pre-commit). Kết quả trước khi sửa:

| Hook | Lệnh | Mong | Đo |
|---|---|---|---|
| `block-dangerous-git.sh` | `bash -c 'git push origin main'` · `eval "git push origin main"` · `sh -c "git reset --hard"` | chặn | **lọt** (rc 0) |
| | `git push origin 'main'` · `git push origin "main"` | chặn | **lọt** |
| | `x=$(git push origin main)` | chặn | **lọt** |
| | `git commit -m "don't break" && git push --force origin main && echo "it's done"` | chặn | **lọt** |
| | 14 ca khác (`-fu`, `+main`, `HEAD:refs/heads/main`, `--delete`, `<<-EOF` thụt tab, `echo "x <<EOF"`, `command git`, `\git`…) | chặn | chặn |
| | 8 ca đối chứng (`main:feat/x`, `+feat/x`, heredoc python, `-f origin feat/x`…) | qua | qua |
| `pre-commit-gate.sh` | `git commit -m x && rm --no-verify` | chạy cổng | **bỏ cổng** |
| | `bash -c 'git commit -m x'` | là commit | **không nhận** |
| | `git commit -F - <<EOF\nnhắc git add\nEOF` | không tự-stage | tự-stage oan (test `than_heredoc` đỏ) |

Vì sao lọt: bộ lọc "bỏ dữ liệu trước khi so khớp" của repo này là **hai lượt `sed` nối tiếp** (`'…'` rồi `"…"`), không
bỏ thân heredoc, không nhận vỏ bọc chạy chuỗi; khuôn tên nhánh dừng ở `[[:space:]]|$` nên `main)` không khớp. Template
đã mắc đúng bẫy này (TRAPS 62, audit 2026-10-09 của họ) — và họ mắc thêm một bẫy nữa đáng học hơn: **hai hook giữ hai
bản sao bộ lọc, sửa heredoc ở một hook, hook kia vẫn hỏng** (O-2 của họ, 2026-10-08).

Sự cố thứ hai, của chính repo này: `docs/sessions/2026-09-09.md` §"Bẫy: gitleaks quét cả lịch sử" — ca eval
`security-auditor` dùng `sk-live-<16 hex>` bịa, job `audit` đỏ, đổi placeholder trên cây **vẫn đỏ**, thêm allowlist
**vẫn đỏ**, phải dựng lại nhánh. Hook commit chỉ canh **tên** file cấm (`llm.yaml`…), không canh **nội dung**.

## 2. Cột 1 — đã có ở đây và sâu hơn (không lấy)

| Template (mới sau 23accce8) | Ở đây | Vì sao không lấy |
|---|---|---|
| ADR-0010 mức rủi ro S/M/L, "phiên chính tự làm" | `docs/KHUON-THI-HANH.md` C1/C2/C3 gắn theo *hình dạng việc*, model + cách chấm theo mức; audit tối giản 2026-10-10 (#400) | Cùng ý, ở đây có bảng model/chấm cụ thể và đã đo (ADR-0010 của họ trích chính X-Agents làm phản ví dụ "tốn token, reject nhiều" — phản hồi đó đã xử ở `2026-10-10-audit-token.md`, không phải việc của đối chiếu này) |
| ADR-0011 trần 5 subagent chạy song song | `/thi-hanh` giao theo hạng mục, mỗi nhóm một worktree, phiên chính gộp | Trần số là tham số vận hành; chưa có sự cố quá tải subagent được ghi |
| `strict-gate-contract.md` (`gate --evidence` JSON gắn HEAD/fingerprint, BLOCKED khi no-op) | DeliveryContract #335: receipt phải đúng argv, exit 0, `checks_executed > 0`; HMAC + exact-head trong journal | Đã lấy ở lần 2 ở dạng sâu hơn (ký máy, không tin JSON tự khai) |
| Kiểm ô bảng Markdown, hook nhận worktree (`rev-parse --show-toplevel`), tự-stage, bit thực thi | Có từ trước — template **lấy từ X-Agents** (báo cáo `2026-10-06-doi-chieu-x-agents-v2`, `…-v3` của họ ghi rõ) | Chiều ngược |
| `.cursor/rules`, `.codex/`, `GEMINI.md` trỏ về luật | `.cursorrules`/`.windsurfrules`/`.clinerules`/`GEMINI.md` + `test_file_luat_cho_harness_khac_tro_ve_agents_md` | Có cổng canh |

## 3. Cột 2 — đã có nhưng nông hơn: LẤY, đã đo

| Điểm | Khoảng trống đo được | Đã làm trong PR này |
|---|---|---|
| Bộ lọc lệnh của hai hook | 7 + 3 ca lọt ở §1; hai bản sao bộ lọc | `.claude/hooks/_lib.sh` một bản (`doc_lenh` jq/python, `bo_than_heredoc`, `bo_trong_nhay` một lượt — nháy MỘT TỪ giữ từ, nháy có khoảng trắng bỏ chuỗi — `VO_BOC_RE`, ngoặc/backtick → khoảng trắng); hai hook `source`; `--no-verify` chỉ tính cùng đoạn với `commit`. Khác template ở chỗ: họ giữ `strip_quoted` bỏ cả `'main'` rồi tính đích push riêng bằng awk; ở đây gỡ nháy quanh từ đơn nên khuôn `nham_nhanh_chinh` cũ dùng được, không thêm máy tính đích |
| Chặn bí mật trước commit | Hook canh tên file, không canh nội dung (sự cố 2026-09-09) | Phép 2b: dòng thêm `^+` của diff (và file chưa track khi lệnh tự stage) quét `KHOA_GIONG_THAT_RE` = regex `_commit-guard.sh` của template + `sk-(live\|test)-[0-9a-f]{16,}` của sự cố; dòng gỡ không quét (gỡ khoá phải commit được); placeholder entropy 0 (`sk-live-XXXX…` đang có ở `companies/keeper/evals/`) qua. **Không lấy** ngưỡng file > 1 MB và `scripts/githooks/pre-commit` (core.hooksPath): chưa có sự cố file lớn; harness khác không có hook là luật đã nêu ở `AGENTS.md` |

Bằng chứng hai chiều: 17 ca mới trong `platform/console/tests/test_cong_khung.py` đỏ với hook cũ (`17 failed, 39
passed`), xanh sau khi sửa (`188 passed`); 11 ca đối chứng không chặn oan xanh cả hai chiều. Probe 29/29 đúng chiều sau sửa.

## 4. Cột 3 — chưa có, xếp "chưa cần" kèm điều kiện quay lại

| Thứ | Vì sao chưa cần (không có sự cố) | Quay lại khi |
|---|---|---|
| PreCompact `precompact-checkpoint.sh`, SessionStart `session-resume.sh`/`session-guide.sh` | `CLAUDE.md` §"Compact Instructions" + `docs/AUTO-COMPACT.md` + `docs/thi-hanh/<mã>.md` làm file trạng thái; không nhật ký nào ghi mất việc vì nén | một phiên ghi "sau compact làm lại việc đã xong" vào `docs/sessions/` |
| Stop `usage-guard.sh`/`telemetry-record.sh` | Đã loại lần 1 (`platform/gateway` + `metrics.py`); audit token 2026-10-10 chỉ ra việc cần là R1 (ghi `num_turns`/cache vào bản ghi eval), không phải hook Stop | R1 xong mà vẫn thiếu số đo phiên Claude Code |
| Work ID → `docs/work/<id>/`, trần WIP 3 PR, FIFO, `progress-freshness`, `stale-pr-alert` | Đo 2026-10-10: 3 PR mở, **cả ba dependabot**; `docs/thi-hanh/` + `docs/sessions/` đã là Work ID. `PROGRESS.md` đã loại lần 1 | > 3 PR người/agent mở cùng lúc trong một tuần, hoặc một PR treo > 14 ngày không ai nhớ |
| pr-policy: mọi tiêu đề commit conventional + ≤ 72 ký tự; cấm `gh pr update-branch` (TRAPS 48 của họ) | Ruleset chỉ cho squash nên tiêu đề commit lẻ không vào `main`. Đo: **36/55** commit `main` gần nhất có tiêu đề > 72 ký tự — thói quen repo này là tiêu đề dài có nghĩa, đổi luật không ứng sự cố nào | Một merge commit không conventional lọt vào `main` (xem dòng dưới) |
| `protection-guard` so `allowed_merge_methods` | **Có sự cố nhưng không phải lỗ của guard**: #399 (`1573be4`) và #374 (`739ad32`) vào `main` bằng **merge commit** dù `.github/rulesets/main.json` chỉ cho `squash`; `merged_by: seeker19110` — tức người có quyền bypass/ruleset lúc đó không áp. Guard của cả hai repo đều chỉ so required checks; thêm so tham số không ngăn được bypass của chủ repo | Chủ repo xác nhận ruleset đang áp có `allowed_merge_methods=["squash"]`; nếu có thì thêm vế so tham số vào `protection-guard` (nhỏ, có test) |
| CodeQL, Scorecard, `secret-scan.yml` theo lịch | `audit` (gitleaks + pip-audit) chạy mọi PR, `dependency-review`; keeper là quét định kỳ có agent | một CVE/leak chỉ quét lịch mới thấy |
| ADR-0009 "nội dung ngoài là dữ liệu, không phải lệnh" cho phiên Claude Code | Runtime công ty có `guard.py`; phiên Claude Code chạy trong harness có luật riêng về nội dung ngoài | nhật ký ghi một lần phiên làm theo lệnh trong PR/issue/file tải về |
| `gate --evidence` + `evidence-check` CLI | Delivery receipt #335 đã làm điều này cho runtime công ty; cho phiên người thì BÁO CÁO XÁC THỰC + CI là cổng | một PR báo "gate xanh" mà CI đỏ ở đúng lệnh đó |
| `copy-framework`, spec-compiler, `/grill`, điều phối 3 tầng | Đã loại lần 1/2, không đổi | — |

## 5. Không nâng mốc ghim

`projects-template.lock.json` ghim **năm tài liệu hợp đồng delivery** (ADR company 0045), không phải "bản template
mới nhất". Đo `git diff --stat 23accce8..c755c90` trên năm file: `adopt-from-outside.md` và
`ui-ux-intelligence-provider.md` không đổi; `standard-delivery.md` +148/−6, `quality-gates-by-profile.md` +69/−6,
`FEATURE-SPEC.template.md` +14/−1. Phần thêm là §3c mức rủi ro S/M/L + trần 5 subagent, §3d ủy quyền phiên chính tự
quyết (theo yêu cầu chủ repo của họ 2026-10-07), mục C1 web app, phép kiểm cho hệ agent (C7), ma trận bằng chứng
AC-6, và hồ sơ `docs/work/<id>/working.md`. Định nghĩa Ready/Done/Complete mà adapter `template-delivery/1` mã hoá
**không bị viết lại** (chỉ thêm câu "worker báo xong/PR đã mở chưa phải Done" — đã là nghĩa của adapter). Nên lock
giữ nguyên; nâng mốc là PR riêng khi `template_handoff`/DeliveryContract cần nghĩa mới — ứng viên đầu tiên là ma trận
bằng chứng AC-6 nếu `quality_floor` theo profile cần thêm chiều.

Ba phần thêm ấy xếp cột 1: S/M/L ↔ C1/C2/C3 của `docs/KHUON-THI-HANH.md`; §3d ủy quyền ↔ `AGENTS.md` §"Khi bối rối"
+ sàn tự duyệt ADR-0043; ma trận bằng chứng ↔ `product_quality`/`quality_floor` theo profile (#335).

## 6. Đính chính trong quá trình làm

- Dự thảo đầu định lấy nguyên `strip_quoted` + máy tính đích push của template. Đo thấy gỡ nháy quanh **từ đơn** đủ
  cho mọi ca và giữ được khuôn `nham_nhanh_chinh` có sẵn — ít code hơn, cùng kết quả.
- Dự thảo xếp "merge commit trên `main`" là lỗ của `protection-guard`. Đọc PR qua API: `merged_by` là chủ repo, tức
  là bypass có chủ đích hoặc ruleset chưa áp — guard không ngăn được, nên chỉ ghi điều kiện quay lại.
- Regex `sk-[A-Za-z0-9]{32,}` của template **không** bắt được `sk-live-<16 hex>` của sự cố 2026-09-09 (có `-`, 16 ký
  tự). Thêm mẫu riêng, hex-only để placeholder `XXXX…` qua.

## 7. Kết luận

Template sau 88 commit cho **hai** thứ đo được là lỗ ở đây: bộ lọc lệnh của hook (10 ca lọt) và quét bí mật trước
commit (sự cố 2026-09-09). Cả hai vào PR này với test đỏ trước. Chín hạng mục khác xếp "chưa cần" với điều kiện quay
lại cụ thể; bốn hạng mục template lấy từ chính X-Agents. Không nâng lock, không thêm hook mới vào `settings.json`.
