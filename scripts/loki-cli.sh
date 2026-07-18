#!/bin/bash
# LokiLinux Agent — local management CLI. Installed as /usr/local/bin/loki
# by install_agent.sh.tmpl (bundled in the tar.gz alongside the agent binary).
set -euo pipefail

CONFIG=/etc/lokilinux/agent.yaml
BIN=/usr/local/bin/lokilinux-agent
SERVICE=lokilinux-agent

usage() {
  cat <<'EOF'
Usage: loki <command>

Commands:
  status    Show whether the agent is running, its ID and version
  start     Start the agent service
  stop      Stop the agent service
  restart   Restart the agent service
  update    Download and install the latest agent version, then restart
  logs      Tail the agent's systemd journal
EOF
}

require_root() {
  [ "$(id -u)" -eq 0 ] || { echo "Error: run as root (sudo)"; exit 1; }
}

# yaml_field <top-level-key> <nested-key> — reads the flat 2-space-indent YAML
# install_agent.sh.tmpl writes. Not a general YAML parser — the format is ours.
yaml_field() {
  awk -v top="$1:" -v key="  $2:" '
    $0 == top { f=1; next }
    f && index($0, key) == 1 { $1=""; sub(/^ /,""); print; exit }
    f && $0 !~ /^  / { exit }
  ' "$CONFIG"
}

cmd_status() {
  local active
  active="$(systemctl is-active "$SERVICE" 2>/dev/null || true)"
  echo "Service    : $SERVICE ($active)"
  if [ -f "$CONFIG" ]; then
    echo "Agent ID   : $(yaml_field identity agent_id)"
    echo "Platform   : $(yaml_field platform url)"
  fi
  [ -x "$BIN" ] && echo "Version    : $("$BIN" --version)"
}

cmd_update() {
  require_root
  [ -f "$CONFIG" ] || { echo "Error: $CONFIG not found — is the agent installed?"; exit 1; }

  local platform_url old_version new_version arch tmpdir bin_path
  platform_url="$(yaml_field platform url)"
  [ -n "$platform_url" ] || { echo "Error: platform.url not found in $CONFIG"; exit 1; }

  arch="$(uname -m)"
  [ "$arch" = "aarch64" ] && arch="arm64"
  [ "$arch" = "x86_64" ] && arch="amd64"

  old_version="$([ -x "$BIN" ] && "$BIN" --version || echo unknown)"

  tmpdir="$(mktemp -d)"
  trap 'rm -rf "$tmpdir"' EXIT
  echo "[*] Downloading latest agent (tar.gz/$arch)..."
  curl -fsSL "$platform_url/api/v1/agent/download-latest?os=tar.gz&arch=$arch" -o "$tmpdir/agent.tar.gz"
  tar -xzf "$tmpdir/agent.tar.gz" -C "$tmpdir"

  bin_path="$(find "$tmpdir" -type f -name 'lokilinux-agent*' ! -name '*.tar.gz' | head -1)"
  [ -n "$bin_path" ] || { echo "Error: binary not found in downloaded package"; exit 1; }
  chmod +x "$bin_path"

  install -m 755 "$bin_path" "$BIN"

  loki_path="$(find "$tmpdir" -type f -name 'loki' | head -1)"
  if [ -n "$loki_path" ]; then
    install -m 755 "$loki_path" /usr/local/bin/loki
    ln -sf /usr/local/bin/loki /usr/bin/loki
  fi

  systemctl restart "$SERVICE"
  sleep 2
  new_version="$("$BIN" --version)"

  if systemctl is-active --quiet "$SERVICE"; then
    echo "[+] Updated: $old_version -> $new_version — $SERVICE running"
  else
    echo "[-] Service failed to start after update:"
    journalctl -u "$SERVICE" -n 20 --no-pager
    exit 1
  fi
}

case "${1:-}" in
  status)  cmd_status ;;
  start)   require_root; systemctl start "$SERVICE" ;;
  stop)    require_root; systemctl stop "$SERVICE" ;;
  restart) require_root; systemctl restart "$SERVICE" ;;
  update)  cmd_update ;;
  logs)    journalctl -u "$SERVICE" -f ;;
  -h|--help|help|"") usage ;;
  *) echo "Unknown command: $1"; usage; exit 1 ;;
esac
