#!/usr/bin/env bash
# pre-commit-gate.sh — hook PreToolUse (matcher: Bash).
#
# Khi Claude sắp `git commit`, kiểm bốn thứ TRƯỚC KHI nó vào lịch sử. Ba thứ đầu là luật cấm của `AGENTS.md`
# mà CI chỉ bắt được SAU khi đã push (luật cấm 3 còn tệ hơn: gitleaks quét cả lịch sử, lỡ commit rồi xoá vẫn đỏ
# vĩnh viễn). Thứ tự rẻ-trước: ba phép kiểm tĩnh chạy trong mili-giây, cổng nặng chạy sau cùng.
#
#   1. Đang đứng trên `main`/`master`      → chặn (luật cấm 1)
#   2. Staged có file cấm commit           → chặn (luật cấm 3: llm.yaml[.bak*|.tmp], media.yaml, *.sqlite*, company.artifacts/)
#   3. Diff staged HẠ `fail_under`         → chặn (luật cấm 6: thêm test, không hạ số)
#   4. `scripts/dev-task.sh gate` đỏ       → chặn (luật bắt buộc 3): gói bị đụng + gói import nó + console
#      (commit chỉ đụng tài liệu/config ngoài mọi gói: console chỉ chạy `dev-task.sh repo-gate`, F6)
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

# THỨ SẮP VÀO COMMIT — ba phép dưới đọc cùng một chỗ. Hook chạy TRƯỚC cả lệnh Bash: gõ `git add … && git commit`
# (hay `git rm`/`git mv` trước commit, hay `commit -a`) một lần thì lúc này index chưa có thứ lệnh ấy sắp stage —
# trước đây cả ba phép đọc index cũ và cho qua (đo 2026-09-28). Lệnh tự stage → xét thêm thay đổi chưa stage và
# file chưa track: thừa (chạy thêm gói) rẻ hơn thiếu (lọt cổng). `--no-renames`: dời file khỏi gói A phải kéo A,
# không chỉ gói đích.
tu_stage=0
printf '%s' "$cmd_scan" | grep -Eq '(^|[^-])git[[:space:]]+([^|&;]*[[:space:]])?(add|rm|mv)([[:space:]]|$)' && tu_stage=1
printf '%s' "$cmd_scan" | grep -Eq 'commit[^|&;]*[[:space:]](-[[:alpha:]]*a[[:alpha:]]*|--all)([[:space:]]|$)' && tu_stage=1
staged="$(git -C "$CAY" diff --cached --name-only --no-renames 2>/dev/null)"
them="$(git -C "$CAY" diff --cached -U0 2>/dev/null)"
if [ "$tu_stage" = 1 ]; then
  staged="$staged
$(git -C "$CAY" diff --name-only --no-renames 2>/dev/null)
$(git -C "$CAY" ls-files --others --exclude-standard 2>/dev/null)"
  them="$them
$(git -C "$CAY" diff -U0 2>/dev/null)"
fi

# --- 2. file cấm commit ---
if [ -n "$staged" ]; then
  cam="$(printf '%s\n' "$staged" | grep -E '(^|/)(llm|media)\.yaml(\.tmp|\.bak[^/]*)?$|\.sqlite|(^|/)company\.artifacts/' || true)"
  if [ -n "$cam" ]; then
    chan "staged có file cấm commit: $(printf '%s' "$cam" | tr '\n' ' ')" \
         "Luật cấm 3: chỉ commit *.example.yaml. gitleaks quét CẢ LỊCH SỬ — commit rồi xoá vẫn đỏ mãi."
  fi
fi

# --- 3. hạ ngưỡng coverage ---
ha_nguong="$(printf '%s\n' "$them" \
  | grep -E '^\+[[:space:]]*fail_under[[:space:]]*=' \
  | grep -Ev '=[[:space:]]*100([^0-9]|$)' || true)"
if [ -n "$ha_nguong" ]; then
  chan "diff staged hạ fail_under: $(printf '%s' "$ha_nguong" | tr '\n' ' ')" \
       "Luật cấm 6: fail_under = 100 ở cả năm package. Mất một dòng phủ thì THÊM TEST, không hạ số."
fi

# --- 4. cổng chất lượng: gói bị đụng + gói import nó + console ---
# Cổng cả năm gói mất ~5 phút; hàng rào đắt quá thì agent sẽ tìm cách né và nó thành vô dụng. Nên chỉ chạy gói có
# thể đỏ vì diff:
#   - gói có file trong diff, cộng gói IMPORT nó (pyproject: company, keeper dùng core; console dùng company,
#     keeper) — `test_cong_khung.py` tính kỳ vọng từ pyproject, thêm phụ thuộc mà quên dòng dưới là đỏ;
#   - console LUÔN chạy: nó giữ cổng cấp repo (README đếm test mọi gói, trần pragma/skip, link tài liệu, hook,
#     workflow, mẫu PR). Commit chỉ sửa tài liệu trước đây bỏ qua mọi cổng — đo 2026-09-28: sửa một dòng README
#     làm đỏ test ở gói khác, commit chỉ đụng README ấy sẽ lọt. Commit như vậy nay chạy console CHẾ ĐỘ NHANH
#     (chỉ test marker `cong_repo`, xem khối `console_nhanh` dưới) thay cho cả suite có `--cov`;
#   - file ngoài company mà test company đọc: lock template (`test_delivery_contract.py`), subagent sinh ra
#     (`assetscan` quét `.claude/agents/`) → kéo company;
#   - file ở GỐC không phải `.md` (pyproject, uv.lock, Makefile) ảnh hưởng mọi gói → `all`.
# no-ky-thuat: test ngoài console đọc file ngoài gói mà dòng dưới không kéo gói của nó (danh sách TEST_DOC_NGOAI_GOI ở test_cong_khung.py), quay lại khi CI đỏ ở một test trong danh sách ấy trên commit hook đã cho qua
goi_bi_dung() {
  local goi="console" f
  while IFS= read -r f; do
    case "$f" in
      "")                                   : ;;
      platform/xagents-core/*)              goi="$goi core company keeper" ;;
      companies/software-company/*)         goi="$goi company" ;;
      companies/keeper/*)                   goi="$goi keeper" ;;
      platform/gateway/*)                   goi="$goi gateway" ;;
      docs/integrations/*|.claude/agents/*) goi="$goi company" ;;
      */*|*.md)                             : ;;   # console (có sẵn), tài liệu, .github, .claude, scripts
      *)                                    echo "all"; return 0 ;;   # file ngay ở GỐC → ảnh hưởng mọi gói
    esac
  done <<EOF
$staged
EOF
  printf '%s\n' $goi | sort -u | tr '\n' ' '
}

if [ -z "$(printf '%s' "$staged" | tr -d '[:space:]')" ]; then
  echo "[pre-commit-gate] không có thay đổi nào sắp vào commit → bỏ qua cổng chất lượng." >&2
  exit 0
fi
can_chay="$(goi_bi_dung)"

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

# Console CHẾ ĐỘ NHANH (F6, audit 2026-10-10): commit chỉ đụng tài liệu/config NGOÀI mọi gói (không `.py`, không
# file nào dưới `companies/`/`platform/`, không file gốc kéo `all`) không đổi được mã lẫn độ phủ — phần console có
# thể đỏ vì nó chỉ là các test đọc file ngoài gói, marker `cong_repo`. Chạy `dev-task.sh repo-gate` (~10 s) thay cho
# `gate console` (~110 s). File không phải `.py` TRONG gói (schema, prompt, mẫu của company/keeper) vẫn cổng đầy
# đủ: chúng chảy vào test console qua import, marker không phủ. `dev-task.sh` cũ chưa có task → cổng đầy đủ.
console_nhanh=0
if [ "${can_chay% }" = "console" ] \
   && ! printf '%s\n' "$staged" | grep -Eq '\.py$|^(companies|platform)/' \
   && grep -Eq '^[[:space:]]*repo-gate\)' "$GOC_CONG/scripts/dev-task.sh" 2>/dev/null; then
  console_nhanh=1
  echo "[pre-commit-gate] commit chỉ đụng tài liệu/config ngoài gói → console chế độ nhanh (pytest -m cong_repo)" >&2
fi

for g in $can_chay; do
  if [ "$g" = "console" ] && [ "$console_nhanh" = 1 ]; then set -- repo-gate; else set -- gate "$g"; fi
  CLAUDE_PROJECT_DIR="$GOC_CONG" "$GOC_CONG/scripts/dev-task.sh" "$@" && continue
  echo "❌ Cổng ĐỎ ở gói '$g' (lint/typecheck/test). Sửa hết rồi commit lại — AGENTS.md luật bắt buộc 3." >&2
  echo "   Bỏ qua có chủ đích: thêm --no-verify vào lệnh git commit." >&2
  exit 2
done

exit 0
