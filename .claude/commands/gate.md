---
description: Cổng trước commit/PR — chạy lệnh CI thật của gói bị đụng, tự rà diff, xuất báo cáo có bằng chứng; còn ❌ thì không commit
---

Chạy cổng chất lượng rồi xuất **báo cáo có bằng chứng**, đúng `AGENTS.md` luật cấm 8 và luật bắt buộc 3.
Mục tiêu: không bao giờ nói "xong" khi chưa có output lệnh vừa chạy **trong chính lượt này**.

## Bước 1 — Xác định gói bị đụng (không chạy thừa, không chạy thiếu)

`git status --short` + `git diff --cached --name-only`. Ánh xạ khớp `.claude/hooks/pre-commit-gate.sh`:
`companies/software-company/`→`company` · `platform/gateway/`→`gateway` · `companies/keeper/`→`keeper` ·
`platform/xagents-core/`→`core` + `company` + `keeper` (hai công ty import core) · `docs/integrations/`,
`.claude/agents/`→`company` (test company đọc chúng). **Luôn thêm `console`**: nó giữ cổng cấp repo (README đếm
test mọi gói, link tài liệu, hook, workflow, mẫu PR) — kể cả khi chỉ sửa tài liệu.
File ở **gốc** không phải `.md` (`pyproject.toml`, `uv.lock`, `Makefile`) → `all`, không được chạy hẹp rồi báo xanh.

## Bước 2 — Chạy cổng, ĐỌC TOÀN BỘ output

```bash
scripts/dev-task.sh gate <gói>
```

Không tự gõ `ruff`/`mypy`/`pytest` rời — script giữ lệnh khớp đúng `ci.yml` (`--cov` cả năm gói, `-n auto`
riêng software-company). Đọc **cả** output, đếm số fail thật, không chỉ nhìn dòng cuối.

Sửa `agents/` hoặc `skills/` → cổng này **chưa đủ**: còn 7 bước `CONTRIBUTING.md` §3 (bump version → `make
golden` → `make eval-record` → `make assetscan` → `make assetbudget` → `make subagents`).

## Bước 3 — Tự rà diff

`git diff --cached`. Kiểm: đúng mục tiêu, không sửa nhầm chỗ · không code chết/print debug · không bí mật,
không `llm.yaml`/`media.yaml`/`*.sqlite*` · mỗi dòng đổi truy được về yêu cầu (luật cấm 7) ·
tiêu đề commit/PR đúng `^(feat|fix|...)(\([a-z0-9._/-]+\))?!?: ` với scope **một từ chữ thường**.

**Nếu là code mới hoặc `fix:`** — luật bắt buộc 4: có test đỏ đi TRƯỚC không? Có → dán output đỏ **và** output
xanh (đo hai chiều). Không, và không rơi vào ngoại lệ (tài liệu, bản sinh tự động, cấu hình thuần) → **dừng**,
viết test trước, đừng hợp lý hoá.

## Bước 4 — Báo cáo

```
Gói chạy: ...              (và vì sao đúng những gói đó)
Lint ✅/❌ | Typecheck ✅/❌ | Test ✅/❌ (X passed, Y failed) | Coverage ...%
Test đỏ-trước ✅/n-a       (dán cả hai chiều)
Tự rà diff ✅ | Không file cấm ✅ | Tiêu đề đúng regex ✅
Rủi ro: ... | KẾT LUẬN: sẵn sàng commit  /  cần xử lý: [...]
```

Một mục ❌ → sửa, chạy **lại toàn bộ**, không commit. `/gate pr` thì thêm: `git fetch` + rebase
`origin/main`, `gh pr list --state open` (luật 2b: chỉ một PR mở), tìm PR/issue trùng (luật 11), và dòng
`CHANGELOG.md` phải nằm trong **chính PR này** (luật 10; không cần `(#n)`). Nhật ký phiên theo luật 9 (cuối phiên).

Bắt đầu Bước 1 ngay.
