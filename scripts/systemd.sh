#!/usr/bin/env bash
# Cài/gỡ systemd user unit cho hub X-Agents trên Linux (ADR gốc 0032). Hướng dẫn: docs/TRIEN-KHAI-SYSTEMD.md
#
#   scripts/systemd.sh install            sinh unit vào ~/.config/systemd/user, chép hub.env lần đầu, daemon-reload
#   scripts/systemd.sh uninstall          dừng + tắt + xoá unit (GIỮ hub.env và dữ liệu)
#   scripts/systemd.sh status             trạng thái mọi dịch vụ xagents-*
#   scripts/systemd.sh logs [dịch vụ]     theo dõi log (mặc định orchestrator), vd: logs console
#   scripts/systemd.sh render <thư mục>   chỉ sinh unit vào thư mục, không đụng systemd (test dùng)
#
# Biến: XDG_CONFIG_HOME (mặc định ~/.config), SYSTEMCTL (mặc định systemctl — test đặt `true`).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAU="$ROOT/deploy/systemd"
CFG="${XDG_CONFIG_HOME:-$HOME/.config}"
UNIT_DIR="$CFG/systemd/user"
ENV_FILE="$CFG/x-agents/hub.env"
SYSTEMCTL="${SYSTEMCTL:-systemctl}"
DICH_VU=(xagents-gateway xagents-orchestrator xagents-console xagents-keeper)
MAC_DINH=(xagents-gateway xagents-orchestrator xagents-console)

uv_path() {
  command -v uv || { echo "[systemd] không thấy uv trên PATH — cài uv trước (docs/TRIEN-KHAI-SYSTEMD.md §1)" >&2; exit 1; }
}

render() {
  local dich="$1" uv
  uv="$(uv_path)"
  mkdir -p "$dich"
  for s in "${DICH_VU[@]}"; do
    sed -e "s|@REPO_ROOT@|$ROOT|g" -e "s|@UV@|$uv|g" "$MAU/$s.service" > "$dich/$s.service"
  done
}

install() {
  render "$UNIT_DIR"
  if [ ! -e "$ENV_FILE" ]; then
    mkdir -p "$(dirname "$ENV_FILE")"
    (umask 077 && sed -e "s|@PATH@|$PATH|g" "$MAU/hub.env.example" > "$ENV_FILE")
    echo "[systemd] đã tạo $ENV_FILE — điền ORCHESTRATOR_ARGS (--repo <repo khách>) trước khi bật"
  else
    echo "[systemd] giữ nguyên $ENV_FILE (đã có)"
  fi
  chmod 600 "$ENV_FILE"
  "$SYSTEMCTL" --user daemon-reload
  echo "[systemd] đã cài ${#DICH_VU[@]} unit vào $UNIT_DIR. Bước tiếp:"
  echo "  systemctl --user enable --now ${MAC_DINH[*]}"
  echo "  loginctl enable-linger \"\$USER\"   # chạy cả khi không ai đăng nhập, bật lại sau reboot"
}

uninstall() {
  for s in "${DICH_VU[@]}"; do
    "$SYSTEMCTL" --user disable --now "$s.service" 2>/dev/null || true
    rm -f "$UNIT_DIR/$s.service"
  done
  "$SYSTEMCTL" --user daemon-reload
  echo "[systemd] đã gỡ unit; giữ $ENV_FILE và mọi file *.sqlite"
}

case "${1:-}" in
  render) [ -n "${2:-}" ] || { echo "dùng: $0 render <thư mục>" >&2; exit 2; }; render "$2" ;;
  install) install ;;
  uninstall) uninstall ;;
  status) "$SYSTEMCTL" --user status --no-pager 'xagents-*' || true ;;
  logs) exec journalctl --user -u "xagents-${2:-orchestrator}" -f ;;
  *) sed -n '2,10p' "$0" >&2; exit 2 ;;
esac
