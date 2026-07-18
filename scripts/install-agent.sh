#!/bin/bash
# LokiLinux Agent — Installation & Enrollment Script
# curl-installable: curl -fsSL https://lokilinux.example.com/install | bash -s -- --token=TOKEN
set -euo pipefail

PLATFORM_URL="${PLATFORM_URL:-https://lokilinux.example.com}"
ENROLLMENT_TOKEN=""
AGENT_NAME=""

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --token=*) ENROLLMENT_TOKEN="${1#*=}"; shift ;;
    --token)   ENROLLMENT_TOKEN="$2";      shift 2 ;;
    --name=*)  AGENT_NAME="${1#*=}";       shift ;;
    --name)    AGENT_NAME="$2";            shift 2 ;;
    --url=*)   PLATFORM_URL="${1#*=}";     shift ;;
    --url)     PLATFORM_URL="$2";          shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

if [ -z "$ENROLLMENT_TOKEN" ]; then
  echo "Error: --token=ENROLLMENT_TOKEN required"
  echo "Usage: bash install-agent.sh --token=<token> [--url=<platform-url>] [--name=<agent-name>]"
  exit 1
fi

# ── OS detection ──────────────────────────────────────────────────────────────
if [ ! -f /etc/os-release ]; then
  echo "Error: /etc/os-release not found — cannot detect OS"
  exit 1
fi
# shellcheck disable=SC1091
. /etc/os-release
OS="$ID"
OS_VERSION="$VERSION_ID"
ARCH="$(uname -m)"
[ "$ARCH" = "aarch64" ] && ARCH="arm64"
[ "$ARCH" = "x86_64" ]  && ARCH="amd64"

echo "[*] LokiLinux Agent Installation"
echo "    Platform : $PLATFORM_URL"
echo "    OS       : $OS $OS_VERSION ($ARCH)"
echo "    Token    : ${ENROLLMENT_TOKEN:0:12}..."

# ── Download binary ───────────────────────────────────────────────────────────
echo "[*] Downloading agent binary..."
AGENT_TMP="$(mktemp)"
curl -fsSL \
  -H "Authorization: Bearer $ENROLLMENT_TOKEN" \
  -H "X-OS: $OS" \
  -H "X-Arch: $ARCH" \
  "$PLATFORM_URL/api/v1/agent/download" \
  -o "$AGENT_TMP"
chmod +x "$AGENT_TMP"
echo "[+] Binary downloaded"

# ── Register with control plane ───────────────────────────────────────────────
echo "[*] Registering agent with control plane..."
REG_RESPONSE=$(curl -fsSL -X POST \
  "$PLATFORM_URL/api/v1/agents/register" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ENROLLMENT_TOKEN" \
  -d "{
    \"hostname\":       \"$(hostname -f)\",
    \"os_distro\":      \"$OS\",
    \"os_version\":     \"$OS_VERSION\",
    \"arch\":           \"$ARCH\",
    \"kernel_version\": \"$(uname -r)\"
  }")

AGENT_ID="$(echo "$REG_RESPONSE"   | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["agent_id"])')"
AGENT_CERT="$(echo "$REG_RESPONSE" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["agent_cert"])')"
AGENT_KEY="$(echo "$REG_RESPONSE"  | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("agent_key",""))')"
CA_CERT="$(echo "$REG_RESPONSE"    | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["ca_cert"])')"

if [ -z "$AGENT_ID" ] || [ "$AGENT_ID" = "null" ]; then
  echo "Error: Agent registration failed"
  echo "$REG_RESPONSE"
  exit 1
fi
echo "[+] Registered — Agent ID: $AGENT_ID"

# ── Create directories ────────────────────────────────────────────────────────
echo "[*] Creating directories..."
install -d -m 750 /etc/lokilinux/certs
install -d -m 755 /var/lib/lokilinux
install -d -m 755 /var/log/lokilinux
install -d -m 755 /opt/lokilinux/plugins

# ── Install certificates ──────────────────────────────────────────────────────
echo "[*] Installing certificates..."
printf '%s\n' "$AGENT_CERT" > /etc/lokilinux/certs/agent.crt
printf '%s\n' "$CA_CERT"    > /etc/lokilinux/certs/ca.crt
if [ -n "$AGENT_KEY" ] && [ "$AGENT_KEY" != "null" ]; then
  printf '%s\n' "$AGENT_KEY" > /etc/lokilinux/certs/agent.key
  chmod 600 /etc/lokilinux/certs/agent.key
fi
chmod 644 /etc/lokilinux/certs/agent.crt /etc/lokilinux/certs/ca.crt

# ── Write agent configuration ─────────────────────────────────────────────────
echo "[*] Writing /etc/lokilinux/agent.yaml..."
GRPC_HOST="$(echo "$PLATFORM_URL" | sed 's|https://||; s|http://||')"

cat > /etc/lokilinux/agent.yaml <<EOF
platform_url: $PLATFORM_URL
grpc:
  host: $GRPC_HOST
  port: 50051
  cert_path: /etc/lokilinux/certs/agent.crt
  key_path: /etc/lokilinux/certs/agent.key
  ca_path: /etc/lokilinux/certs/ca.crt

agent:
  id: $AGENT_ID
  hostname: $(hostname -f)

heartbeat:
  interval_seconds: 60
  timeout_seconds: 30

cache:
  path: /var/lib/lokilinux

plugins:
  enabled: true
  dir: /opt/lokilinux/plugins

logging:
  level: info
  path: /var/log/lokilinux/agent.log
EOF
chmod 640 /etc/lokilinux/agent.yaml

# ── Install binary ────────────────────────────────────────────────────────────
echo "[*] Installing agent binary..."
install -m 755 "$AGENT_TMP" /usr/local/bin/lokilinux-agent
rm -f "$AGENT_TMP"

# ── Create systemd unit ───────────────────────────────────────────────────────
echo "[*] Creating systemd service..."
cat > /etc/systemd/system/lokilinux-agent.service <<'EOF'
[Unit]
Description=LokiLinux Agent
Documentation=https://docs.lokilinux.io/agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/lokilinux-agent --config /etc/lokilinux/agent.yaml
Restart=always
RestartSec=10
TimeoutStopSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lokilinux-agent

# Harden service
ProtectSystem=strict
ReadWritePaths=/var/lib/lokilinux /var/log/lokilinux
ProtectHome=true
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

# ── Enable and start ──────────────────────────────────────────────────────────
echo "[*] Enabling and starting lokilinux-agent..."
systemctl daemon-reload
systemctl enable lokilinux-agent
systemctl start  lokilinux-agent

sleep 2
if systemctl is-active --quiet lokilinux-agent; then
  echo "[+] lokilinux-agent is running"
else
  echo "[-] Service failed to start. Logs:"
  journalctl -u lokilinux-agent -n 30 --no-pager
  exit 1
fi

echo ""
echo "[+] LokiLinux Agent installed successfully!"
echo ""
echo "  Agent ID : $AGENT_ID"
echo "  Status   : $(systemctl is-active lokilinux-agent)"
echo "  Logs     : journalctl -u lokilinux-agent -f"
echo "  Config   : /etc/lokilinux/agent.yaml"
