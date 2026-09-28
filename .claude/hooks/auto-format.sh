#!/usr/bin/env bash
# auto-format.sh — hook PostToolUse (matcher: Edit|Write).
# Sau khi sửa/tạo một file, format ĐÚNG file đó qua `scripts/dev-task.sh format-file` — và chỉ khi file vốn đã
# sạch `ruff format` (hoặc là file mới): giữ file sạch cho sạch. CI KHÔNG chạy `ruff format --check`, phần lớn
# repo cố ý viết gọn một dòng (`.pre-commit-config.yaml`), nên format cả file chưa sạch = diff phình (TRAPS.md §3).
# Luôn exit 0: hook này không được cản luồng vì bất cứ lý do gì.
#
# Lấy từ `seeker19110/project-template` (`.claude/hooks/auto-format.sh`).
set -uo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"

# Đọc đường dẫn file từ payload — xem chú thích `doc_lenh` ở `block-dangerous-git.sh` (máy không có jq).
doc_path() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$1" | jq -r '.tool_input.file_path // empty' 2>/dev/null
    return 0
  fi
  local py
  for py in python3 python; do
    if command -v "$py" >/dev/null 2>&1; then
      printf '%s' "$1" | "$py" -c 'import sys,json
try: sys.stdout.write(json.load(sys.stdin).get("tool_input",{}).get("file_path","") or "")
except Exception: pass' 2>/dev/null
      return 0
    fi
  done
  return 1
}

payload="$(cat)"
if ! path="$(doc_path "$payload")"; then
  echo "[auto-format] không có jq lẫn python → không đọc được đường dẫn, bỏ qua format." >&2
  exit 0
fi

[ -n "$path" ] || exit 0
if [ ! -x "$ROOT/scripts/dev-task.sh" ]; then
  echo "[auto-format] không thấy scripts/dev-task.sh → bỏ qua format." >&2
  exit 0
fi

"$ROOT/scripts/dev-task.sh" format-file "$path" >/dev/null 2>&1 || true
exit 0
