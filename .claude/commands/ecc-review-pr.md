---
description: Comprehensive PR review using specialized agents (ecc-code-reviewer, ecc-comment-analyzer, ecc-pr-test-analyzer, ecc-silent-failure-hunter, ecc-type-design-analyzer, ecc-code-simplifier). Use for a multi-agent PR review pass; for the adversarially-verified Workflow pass use /orch-review, and for the standalone step-by-step checklist review use /code-review.
---

<!-- Sinh bởi scripts/ecc_vendor.py từ affaan-m/ECC@c70874fae9eb0e5ad0365beb7e2955899fd1d30f (commands/review-pr.md) — không sửa tay; đổi thì sửa docs/integrations/ecc.lock.json rồi chạy lại (ADR-0028). -->
> **ECC (MIT), vendor vào X-Agents.** Luật ở `AGENTS.md` thắng khi trùng: coverage `fail_under = 100` (không phải 80%), test đỏ trước khi code, nhánh → PR theo `docs/QUY-TRINH-GIT.md`, không xoá code ngoài yêu cầu. Mục ECC được nhắc tới mà không có tệp `ecc-<tên>` trong `.claude/` thì repo không vendor — dùng `/gate`, `/debug`, `/adr`, `/thi-hanh` hoặc bỏ qua.

Run a comprehensive multi-perspective review of a pull request.

## Usage

`/ecc-review-pr [PR-number-or-URL] [--focus=comments|tests|errors|types|code|simplify]`

If no PR is specified, review the current branch's PR. If no focus is specified, run the full review stack.

## Steps

1. Identify the PR:
   - use `gh pr view` to get PR details, changed files, and diff
2. Find project guidance:
   - look for `CLAUDE.md`, lint config, TypeScript config, repo conventions
3. Run specialized review agents:
   - `ecc-code-reviewer`
   - `ecc-comment-analyzer`
   - `ecc-pr-test-analyzer`
   - `ecc-silent-failure-hunter`
   - `ecc-type-design-analyzer`
   - `ecc-code-simplifier`
4. Aggregate results:
   - dedupe overlapping findings
   - rank by severity
5. Report findings grouped by severity

## Confidence Rule

Only report issues with confidence >= 80:

- Critical: bugs, security, data loss
- Important: missing tests, quality problems, style violations
- Advisory: suggestions only when explicitly requested
