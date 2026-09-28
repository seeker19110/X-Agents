#!/usr/bin/env bash
# block-dangerous-git.sh — hook PreToolUse (matcher: Bash).
#
# VÌ SAO CẦN: `AGENTS.md` có 8 luật cấm, nhưng trước hook này chúng chỉ tồn tại dưới dạng CHỮ — không cơ chế
# nào thi hành. Repo này tự viết luật cấm 8 "không tin lời khai, kể cả của chính mình" rồi lại để chính các
# luật cấm được canh bằng đúng thứ nó không cho tin: trí nhớ của agent. Hook là hàng rào, không phải lời nhắc.
#
# Lấy từ `seeker19110/project-template` (`.claude/hooks/block-dangerous-git.sh`), thêm khuôn (1b) của repo này.
#
# Chặn (exit 2 = chặn, báo lại cho Claude):
#   1.  force-push vào nhánh chính                     — luật cấm 1
#   1b. push THƯỜNG vào `main`/`master`                — luật cấm 1 (ruleset cũng từ chối, nhưng bắt sớm hơn)
#   2.  `reset --hard`                                 — mất thay đổi chưa commit, không hoàn tác
#   3.  `merge|rebase|cherry-pick --abort`             — né giải xung đột
# Cảnh báo (không chặn): force-push lên nhánh không phải nhánh chính — hợp lệ trên nhánh mình tạo.
#
# Đường thoát tường minh: ALLOW_DANGEROUS_GIT=1 (và phải nói rõ lý do cho người dùng).
set -uo pipefail   # cố ý KHÔNG -e: hook không được làm chết phiên

[ "${ALLOW_DANGEROUS_GIT:-0}" = "1" ] && exit 0

# Đọc lệnh Bash sắp chạy từ payload. Ưu tiên jq; thiếu jq thì dùng Python (repo này là repo Python nên chắc
# chắn có). KHÔNG grep JSON thô: sẽ khớp nhầm nội dung file/mô tả rồi chặn oan.
# Đo 2026-09-14: máy phát triển chính KHÔNG có jq — bản template chỉ dùng jq nên hàng rào của nó sẽ fail-open
# IM LẶNG suốt phiên, đúng khuôn "cổng chết im lặng" mà `test_cong_repo.py` sinh ra để canh.
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
  # Fail-open nhưng NÓI RA: fail-open im lặng là cái bẫy — người tưởng hàng rào đang canh cả phiên.
  echo "[block-dangerous-git] không có jq lẫn python → không đọc được lệnh, bỏ qua kiểm tra." >&2
  exit 0
fi
[ -n "$cmd" ] || exit 0

# Bỏ phần TRONG DẤU NHÁY trước khi so khớp: `git commit -m 'nói về git reset --hard'` không phải lệnh nguy hiểm.
cmd_scan="$(printf '%s' "$cmd" | sed "s/'[^']*'//g; s/\"[^\"]*\"//g")"

la_git() { printf '%s' "$cmd_scan" | grep -Eq "(^|[^-])git[[:space:]]+([^|&;]*[[:space:]])?$1([[:space:]]|$)"; }
co_co()  { printf '%s' "$cmd_scan" | grep -Eq "(^|[[:space:]])($1)([[:space:]]|$)"; }

chan() {
  echo "🚫 Lệnh bị chặn bởi block-dangerous-git.sh: $1" >&2
  echo "   Lý do: $2" >&2
  echo "   Nếu THỰC SỰ cần: chạy lại với ALLOW_DANGEROUS_GIT=1 và nói rõ lý do cho người dùng." >&2
  exit 2
}

# Nhánh chính xuất hiện như đích push: `origin main`, `HEAD:main`, `origin/main` không tính (đó là đọc, không ghi).
nham_nhanh_chinh() { printf '%s' "$cmd_scan" | grep -Eq '(^|[[:space:]:])(main|master)([[:space:]]|$)'; }

# --- 1 + 1b: mọi thứ ghi vào nhánh chính ---
# Xét TỪNG ĐOẠN lệnh (tách ở `&&` `||` `;` `|`): `git push -u origin x && gh pr create --base main` có `main` ở lệnh
# gh, không phải đích push — dò cả dòng thì chặn oan (đo được 2026-09-26). `cmd_scan` được gán lại theo đoạn nên
# `la_git`/`nham_nhanh_chinh`/`co_co` bên dưới chỉ nhìn đúng đoạn đó.
toan_bo="$cmd_scan"
while IFS= read -r cmd_scan; do
  if la_git push && nham_nhanh_chinh; then
    if co_co '--force|--force-with-lease|--force-with-lease=[^[:space:]]*|-f'; then
      chan "force-push vào nhánh chính" "Luật cấm 1: không đẩy thẳng nhánh chính; force-push còn xoá lịch sử người khác."
    fi
    chan "push thẳng vào nhánh chính" "Luật cấm 1 (AGENTS.md): mọi thay đổi đi nhánh → PR → CI xanh → squash merge."
  fi
done <<EOF
$(printf '%s\n' "$toan_bo" | sed 's/&&/\n/g; s/||/\n/g; s/[;|]/\n/g')
EOF
cmd_scan="$toan_bo"

# --- 2: reset --hard ---
if la_git reset && co_co '--hard'; then
  chan "git reset --hard" "Mất vĩnh viễn thay đổi chưa commit. Dùng commit WIP, hoặc 'git restore <file>' cho phạm vi hẹp."
fi

# --- 3: --abort để né giải xung đột ---
if printf '%s' "$cmd_scan" | grep -Eq '(^|[^-])git[[:space:]]+([^|&;]*[[:space:]])?(merge|rebase|cherry-pick)([[:space:]]|$)' \
   && co_co '--abort'; then
  chan "git ... --abort" "Né giải xung đột. Đọc cả hai phía rồi giải — hoặc hỏi người, đừng bỏ chạy."
fi

# --- 4: force-push nhánh khác: cảnh báo, không chặn ---
if la_git push && co_co '--force|-f'; then
  echo "⚠️  force-push (không phải nhánh chính): chỉ hợp lệ trên nhánh DO BẠN tạo — worktree của phiên khác thì không." >&2
fi

exit 0
