#!/usr/bin/env bash
# pre-commit-gate.sh — hook PreToolUse (matcher: Bash).
#
# Khi Claude sắp `git commit`, kiểm bốn thứ TRƯỚC KHI nó vào lịch sử. Ba thứ đầu là luật cấm của `AGENTS.md`
# mà CI chỉ bắt được SAU khi đã push (luật cấm 3 còn tệ hơn: gitleaks quét cả lịch sử, lỡ commit rồi xoá vẫn đỏ
# vĩnh viễn). Thứ tự rẻ-trước: ba phép kiểm tĩnh chạy trong mili-giây, cổng nặng chạy sau cùng.
#
#   1. Đang đứng trên `main`/`master`      → chặn (luật cấm 1)
#   2. Staged có file cấm commit           → chặn (luật cấm 3: llm.yaml, media.yaml, *.sqlite*, company.artifacts/)
#   3. Diff staged HẠ `fail_under`         → chặn (luật cấm 6: thêm test, không hạ số)
#   4. `scripts/dev-task.sh gate` đỏ       → chặn (luật bắt buộc 3)
#
# Lấy từ `seeker19110/project-template` (`.claude/hooks/pre-commit-gate.sh`); ba phép kiểm đầu là của repo này.
# Bỏ qua có chủ đích: thêm `--no-verify` vào lệnh commit.
set -uo pipefail   # cố ý KHÔNG -e: hook không được làm chết phiên

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"

# CÂY ĐANG COMMIT ≠ CHECKOUT CHÍNH. `CLAUDE.md` luật 2 bắt mỗi phiên một `git worktree`, nên `CLAUDE_PROJECT_DIR`
# (checkout chính) và cây mà `git commit` sắp chạy trên đó thường là HAI thư mục khác nhau. Dùng chung một biến
# cho hai nghĩa làm hàng rào hỏng cả hai chiều: phép 1 đọc nhánh của checkout chính (`main`) → chặn oan mọi
# commit đúng luật; phép 2-4 đọc index của checkout chính (rỗng) → file cấm và `fail_under` bị buông.
#   $ROOT → chỗ lùi về khi cây đang commit không có `scripts/dev-task.sh`.
#   $CAY  → mọi phép kiểm: đọc trạng thái git (nhánh, index, diff staged) VÀ cổng chất lượng của phép 4.
# Lấy từ cwd của hook: đó là cwd của lệnh `git commit` sắp chạy. Ngoài repo (hoặc không lấy được) thì lùi về
# $ROOT — lùi về chặt hơn là buông cổng.
CAY="$(git rev-parse --show-toplevel 2>/dev/null)"
[ -n "$CAY" ] || CAY="$ROOT"

# Đọc lệnh từ payload — xem chú thích `doc_lenh` ở `block-dangerous-git.sh` (máy phát triển không có jq).
doc_lenh() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$1" | jq -r '.tool_input.command // empty' 2>/dev/null
    return 0
  fi
  local py
  for py in python3 python; do
    if command -v "$py" >/dev/null 2>&1; then
      printf '%s' "$1" | "$py" -c 'import sys,json
try: sys.stdout.write(json.load(sys.stdin).get("tool_input",{}).get("command","") or "")
except Exception: pass' 2>/dev/null
      return 0
    fi
  done
  return 1
}

payload="$(cat)"
if ! cmd="$(doc_lenh "$payload")"; then
  echo "[pre-commit-gate] không có jq lẫn python → không đọc được lệnh, bỏ qua cổng." >&2
  exit 0
fi

cmd_scan="$(printf '%s' "$cmd" | sed "s/'[^']*'//g; s/\"[^\"]*\"//g")"

# Chỉ can thiệp khi đúng là `git commit` (bỏ qua commit-tree, --help…).
printf '%s' "$cmd_scan" | grep -Eq '(^|[^-])git[[:space:]]+([^|&;]*[[:space:]])?commit([[:space:]]|$)' || exit 0

if printf '%s' "$cmd_scan" | grep -Eq '(^|[[:space:]])--no-verify([[:space:]]|$)'; then
  echo "[pre-commit-gate] phát hiện --no-verify → bỏ qua cổng." >&2
  exit 0
fi

chan() {
  echo "🚫 Commit bị chặn: $1" >&2
  echo "   $2" >&2
  echo "   Bỏ qua có chủ đích: thêm --no-verify (và nói rõ lý do cho người dùng)." >&2
  exit 2
}

# --- 1. nhánh hiện tại ---
nhanh="$(git -C "$CAY" branch --show-current 2>/dev/null)"
case "$nhanh" in
  main|master)
    chan "đang đứng trên nhánh '$nhanh'" \
         "Luật cấm 1 (AGENTS.md): không commit thẳng nhánh chính. Tạo nhánh riêng: git switch -c <loại>/<việc>"
    ;;
esac

# --- 2. file cấm commit ---
staged="$(git -C "$CAY" diff --cached --name-only 2>/dev/null)"
if [ -n "$staged" ]; then
  cam="$(printf '%s\n' "$staged" | grep -E '(^|/)(llm\.yaml|media\.yaml)$|\.sqlite|(^|/)company\.artifacts/' || true)"
  if [ -n "$cam" ]; then
    chan "staged có file cấm commit: $(printf '%s' "$cam" | tr '\n' ' ')" \
         "Luật cấm 3: chỉ commit *.example.yaml. gitleaks quét CẢ LỊCH SỬ — commit rồi xoá vẫn đỏ mãi."
  fi
fi

# --- 3. hạ ngưỡng coverage ---
ha_nguong="$(git -C "$CAY" diff --cached -U0 2>/dev/null \
  | grep -E '^\+[[:space:]]*fail_under[[:space:]]*=' \
  | grep -Ev '=[[:space:]]*100([^0-9]|$)' || true)"
if [ -n "$ha_nguong" ]; then
  chan "diff staged hạ fail_under: $(printf '%s' "$ha_nguong" | tr '\n' ' ')" \
       "Luật cấm 6: fail_under = 100 ở cả năm package. Mất một dòng phủ thì THÊM TEST, không hạ số."
fi

# --- 4. cổng chất lượng, HẸP theo gói bị đụng ---
# Chạy cổng cả năm package trước MỖI commit mất nhiều phút; hàng rào nào đắt quá thì agent sẽ tìm cách né và
# nó thành vô dụng. Nên: chỉ gói có file trong diff staged. File ở GỐC (pyproject/Makefile/CI) ảnh hưởng mọi
# gói → quay về `all`, không được chạy hẹp rồi báo xanh.
goi_bi_dung() {
  local goi="" f
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    case "$f" in
      companies/software-company/*) goi="$goi company" ;;
      platform/gateway/*)           goi="$goi gateway" ;;
      platform/console/*)           goi="$goi console" ;;
      platform/xagents-core/*)      goi="$goi core" ;;
      companies/keeper/*)           goi="$goi keeper" ;;
      docs/*|*.md)                  : ;;   # tài liệu: không gói nào phải chạy cổng vì nó
      */*)                          : ;;   # thư mục khác (.github, .claude, scripts) → xử ở dưới
      *)                            echo "all"; return 0 ;;   # file ngay ở GỐC → ảnh hưởng mọi gói
    esac
  done <<EOF
$staged
EOF
  printf '%s\n' "$goi" | tr ' ' '\n' | grep -v '^$' | sort -u | tr '\n' ' '
}

can_chay="$(goi_bi_dung)"
if [ -z "${can_chay// /}" ]; then
  echo "[pre-commit-gate] diff staged không đụng package nào → bỏ qua cổng chất lượng." >&2
  exit 0
fi

# Cổng chạy trên $CAY, không trên $ROOT: `dev-task.sh` lấy cây để `cd` + venv từ `CLAUDE_PROJECT_DIR`, không từ
# vị trí của chính nó — nên phải đổi CẢ đường dẫn script lẫn biến. Chạy trên checkout chính là chấm code khác
# code đang commit: xanh khi worktree đỏ, đỏ vì venv chính hỏng (đo 2026-09-27, `TRAPS.md` §3). Cây không có
# script (nhánh cũ, repo khác) thì lùi về $ROOT như trước.
GOC_CONG="$CAY"
[ -x "$GOC_CONG/scripts/dev-task.sh" ] || GOC_CONG="$ROOT"
echo "[pre-commit-gate] chạy cổng cho gói: ${can_chay% } (cây $GOC_CONG)" >&2

if [ ! -x "$GOC_CONG/scripts/dev-task.sh" ]; then
  echo "[pre-commit-gate] không thấy scripts/dev-task.sh → bỏ qua cổng chất lượng." >&2
  exit 0
fi

for g in $can_chay; do
  CLAUDE_PROJECT_DIR="$GOC_CONG" "$GOC_CONG/scripts/dev-task.sh" gate "$g" && continue
  echo "❌ Cổng ĐỎ ở gói '$g' (lint/typecheck/test). Sửa hết rồi commit lại — AGENTS.md luật bắt buộc 3." >&2
  echo "   Bỏ qua có chủ đích: thêm --no-verify vào lệnh git commit." >&2
  exit 2
done

exit 0
