#!/usr/bin/env sh
# ADR-0013: entrypoint container hub. Git identity từ env nếu có (orchestrator commit thật lên repo khách
# khi tạo/gộp worktree), rồi chạy console — console tự spawn orchestrator qua --allow-engine (ADR-0004),
# argv chốt cứng trong platform/console/src/console/engine.py, không đọc gì từ đây.
set -eu

if [ -n "${GIT_AUTHOR_NAME:-}" ] && [ -n "${GIT_AUTHOR_EMAIL:-}" ]; then
    export GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-$GIT_AUTHOR_NAME}"
    export GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-$GIT_AUTHOR_EMAIL}"
fi

# Bind giao diện container để nhận port publish; compose chỉ mở cổng loopback trên host (O3, ADR-0013 §6).
# `--company-db`/`--keeper-db` trỏ vào thư mục `var/` được mount (ADR-0014 quyết định 4): WAL sinh `-wal`/`-shm`
# cạnh file DB, và blackboard ghi `<db>.with_suffix(".artifacts")` cạnh nó — cả ba phải nằm trong volume, nên
# chỗ chứa DB phải là một THƯ MỤC được mount, không phải một file được mount. `console/engine.py` truyền tiếp
# đúng đường dẫn này cho orchestrator con qua `--db`, nên không có chỗ nào phải khai lại.
COMPANY_DB="${COMPANY_DB:-/app/companies/software-company/var/company.sqlite}"
KEEPER_DB="${KEEPER_DB:-/app/companies/keeper/var/keeper.sqlite}"
mkdir -p "$(dirname "$COMPANY_DB")" "$(dirname "$KEEPER_DB")"

CONSOLE_ARGS="--host 0.0.0.0 --i-know --allow-decide --allow-submit --allow-config --allow-engine"
CONSOLE_ARGS="$CONSOLE_ARGS --company-db $COMPANY_DB --keeper-db $KEEPER_DB"
if [ -n "${DELIVER_REMOTE:-}" ]; then
    CONSOLE_ARGS="$CONSOLE_ARGS --deliver-remote ${DELIVER_REMOTE}"
fi

cd /app/platform/console
# shellcheck disable=SC2086
exec uv run python -m console $CONSOLE_ARGS "$@"
