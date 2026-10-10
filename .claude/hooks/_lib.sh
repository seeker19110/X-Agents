#!/usr/bin/env bash
# _lib.sh — hàm dùng chung cho hai hook PreToolUse soi lệnh Bash (`block-dangerous-git.sh`, `pre-commit-gate.sh`).
# CHỈ để `source "$(dirname "$0")/_lib.sh"`: không tự chạy, không nối vào `settings.json`, không `set` gì ở đây
# (hook gọi tự đặt shell option — cố ý KHÔNG -e).
#
# VÌ SAO TÁCH RA (đối chiếu `seeker19110/projects-template` 2026-10-10, TRAPS 62 của họ): hai hook từng giữ HAI bản
# sao bộ lọc "bỏ dữ liệu trước khi so khớp", và bản sao lệch nhau là cách hàng rào hỏng theo chiều NGUY HIỂM
# (để lọt) mà không ai thấy. Đo trên hook cũ của repo này 2026-10-10, bảy lệnh ghi vào `main`/`reset --hard` lọt
# (exit 0) — `platform/console/tests/test_cong_khung.py::test_chan_git_chan_dung_khuon_cam` giữ đủ bảy ca.

# Đọc lệnh Bash sắp chạy (`.tool_input.command`) từ payload JSON ($1). Ưu tiên jq; thiếu jq thì Python (repo này
# là repo Python nên chắc chắn có). KHÔNG grep JSON thô: sẽ khớp nhầm nội dung file/mô tả rồi chặn oan.
# Đo 2026-09-14: máy phát triển chính KHÔNG có jq — bản template chỉ dùng jq nên hàng rào của nó fail-open IM LẶNG
# suốt phiên, đúng khuôn "cổng chết im lặng" mà `test_cong_repo.py` sinh ra để canh. Trả 1 khi không có cả hai —
# hook gọi phải NÓI RA rồi mới bỏ qua.
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

# Bỏ THÂN heredoc (`<<EOF … EOF`, `<<-EOF` thụt tab, `<<'EOF'`): thân là dữ liệu — commit message nhắc `git add`,
# script python nạp qua `python3 - <<PY` chứa chuỗi `git commit`. Hai bẫy đã biết khi viết hàm này (template đo được):
#   - KHÔNG cho khoảng trắng giữa `<<` và delimiter: `echo "a << b"` sẽ thành heredoc với delimiter `b` và MỌI
#     dòng sau bị nuốt, kể cả `git reset --hard` ở dòng kế.
#   - `<<` nằm TRONG chuỗi nháy (`echo "x <<EOF"`) không phải heredoc: chỉ nhận khi phần đứng trước nó, sau khi bỏ
#     các cặp nháy đã đóng, không còn ký tự nháy lẻ.
#   - `<<-EOF`: bash bỏ TAB đầu dòng trước khi so terminator → so sau khi bỏ tab, không thì terminator thụt tab
#     không bao giờ khớp và mọi dòng sau bị nuốt.
# \047 = nháy đơn, \042 = nháy kép (escape bát phân của awk) để cả chương trình nằm gọn trong một cặp nháy đơn.
bo_than_heredoc() {
  awk '
    BEGIN { delim = ""; dash = 0 }
    {
      if (delim != "") {
        line = $0
        if (dash) sub(/^\t+/, "", line)
        if (line == delim) delim = ""
        next
      }
      rest = $0; pre = ""
      while (match(rest, /<<-?[\047\042]?[A-Za-z_][A-Za-z0-9_]*[\047\042]?/)) {
        before = pre substr(rest, 1, RSTART - 1)
        d = substr(rest, RSTART, RLENGTH)
        q = before
        gsub(/\047[^\047]*\047|\042[^\042]*\042/, "", q)
        if (q !~ /[\047\042]/) {
          dash = (d ~ /^<<-/)
          sub(/^<<-?/, "", d)
          gsub(/[\047\042]/, "", d)
          delim = d
          break
        }
        pre = before d
        rest = substr(rest, RSTART + RLENGTH)
      }
      print
    }'
}

# Bỏ phần TRONG DẤU NHÁY — hai bước, mỗi bước MỘT lượt trái→phải (một regex xen kẽ `'…'|"…"`):
#   1. chuỗi nháy là MỘT TỪ (`'main'`, `"x"`, `-m 'x'`) → bỏ dấu nháy, giữ từ: đó là đối số (tên nhánh, cờ), không
#      phải dữ liệu — đo 2026-10-10: `git push origin 'main'` lọt vì bản cũ bỏ cả từ cùng nháy;
#   2. chuỗi nháy còn lại (có khoảng trắng) → bỏ cả chuỗi: `git commit -m 'nói về git reset --hard'`.
# Vì sao một lượt chứ không phải hai lượt sed nối tiếp (`s/'…'//; s/"…"//`): bản cũ bỏ nháy đơn TRƯỚC nên
# `"don't break" && git push --force origin main && echo "it's done"` ghép `'t break" … "it'` thành một chuỗi và
# nuốt cả lệnh push ở giữa (đo được, lọt).
bo_trong_nhay() {
  sed -E "s/'([^'[:space:]]*)'|\"([^\"[:space:]]*)\"/\1\2/g; s/'[^']*'|\"[^\"]*\"//g"
}

# Chỉ bỏ KÝ TỰ nháy, giữ nội dung: dùng khi phần trong nháy chính LÀ lệnh (`bash -c 'git reset --hard'`).
bo_dau_nhay() { tr -d "'\""; }

# Vỏ bọc chạy CHUỖI như lệnh: `bash -c '…'`, `sh -c "…"`, `zsh -lc '…'`, `eval "…"`. Chỉ nhận khi chuỗi đứng ngay
# sau (qua cờ `-c`/`-lc`); `cmd=…; eval "$cmd"` hay script ghi ra file rồi chạy thì hook KHÔNG thấy lệnh thật —
# hook là lưới đỡ cho lỗi vô ý, không phải hàng rào chống người cố né (ruleset trên GitHub mới là hàng rào cứng).
VO_BOC_RE="(^|[[:space:]])(bash|sh|zsh|eval)[[:space:]]+(-[A-Za-z]+[[:space:]]+)*[\"']"

# Văn bản để so khớp từ lệnh gốc ($1): bỏ thân heredoc → bỏ phần trong nháy (có vỏ bọc chạy chuỗi thì phần trong
# nháy là lệnh nên chỉ bỏ ký tự nháy; chặn oan `echo "bash -c '…'"` là đánh đổi cố ý, chiều an toàn) → `$(…)`,
# `(…)`, backtick thành khoảng trắng: `x=$(git push origin main)` là push thật nhưng `main)` không khớp khuôn tên
# nhánh (đo 2026-10-10, lọt).
van_ban_soi() {
  local than
  than="$(printf '%s' "$1" | bo_than_heredoc)"
  if printf '%s' "$than" | grep -Eq "$VO_BOC_RE"; then
    printf '%s' "$than" | bo_dau_nhay | tr '()`' '   '
  else
    printf '%s' "$than" | bo_trong_nhay | tr '()`' '   '
  fi
}

# Chuỗi giống khoá/token THẬT — AWS / PEM private key / GitHub / GitLab / Google / OpenAI / Slack (lấy từ
# projects-template `scripts/_commit-guard.sh`), cộng dạng `sk-live-<hex>` của sự cố 2026-09-09 repo này
# (`docs/sessions/2026-09-09.md`: ca eval dùng `sk-live-<16 hex>` bịa, gitleaks quét cả lịch sử nên phải dựng lại
# nhánh). Placeholder entropy 0 (`sk-live-XXXXXXXXXXXXXXXX`, `<dien-khoa>`) cố ý KHÔNG khớp: hook này chặn thứ
# gitleaks sẽ chặn, không chặt hơn — chặn oan dạy người gõ --no-verify thành phản xạ.
KHOA_GIONG_THAT_RE='(AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,}|glpat-[A-Za-z0-9_-]{20}|AIza[0-9A-Za-z_-]{35}|sk-[A-Za-z0-9]{32,}|sk-(live|test)-[0-9a-f]{16,}|xox[baprs]-[A-Za-z0-9-]{10,})'
