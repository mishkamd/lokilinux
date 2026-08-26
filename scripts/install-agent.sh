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

# ── Platform job-signing public key (public by design) ────────────────────────
# NOTE: this offline installer's agent.yaml schema has drifted from
# backend/lokilinux/install_agent.sh.tmpl (the served one matches
# config.go). The security block below matches config.SecurityConfig.
echo "[*] Fetching platform job-signing public key..."
if curl -fsSL "$PLATFORM_URL/api/v1/agent/signing-key" -o /etc/lokilinux/signing_pub.b64 \
   && [ -s /etc/lokilinux/signing_pub.b64 ]; then
  chmod 644 /etc/lokilinux/signing_pub.b64
else
  echo "[!] WARNING: could not fetch signing key — signed-job enforcement will stay disabled"
  rm -f /etc/lokilinux/signing_pub.b64
fi

# ── Install binary ────────────────────────────────────────────────────────────
echo "[*] Installing agent binary..."
install -m 755 "$AGENT_TMP" /usr/local/bin/lokilinux-agent
rm -f "$AGENT_TMP"

# ── Dedicated service user (pre-provisioning for Faza 2 broker) ───────────────
if ! id -u loki-agent >/dev/null 2>&1; then
  echo "[*] Creating system user loki-agent..."
  useradd --system --home-dir /var/lib/lokilinux --no-create-home \
          --shell /usr/sbin/nologin loki-agent 2>/dev/null || true
fi
chown -R loki-agent:loki-agent /var/lib/lokilinux /var/log/lokilinux 2>/dev/null || true

# ── Create systemd unit ───────────────────────────────────────────────────────
# NOTE: keep the [Service] section identical to backend/lokilinux/install_agent.sh.tmpl
# (the template actually served by /api/v1/agent/install.sh — this file is a
# secondary/offline install path). A prior divergence between the two shipped
# a widened ReadWritePaths here that the served template never got, and was
# insufficient anyway: ProtectSystem=strict still blocks writing into /usr,
# where package installs actually land. Host-mutating jobs (package updates,
# ansible, arbitrary shell) escape this sandbox per-job via systemd-run
# instead (see agent/internal/modules/systemd_run.go) — ReadWritePaths does
# not need widening for that.
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
UMask=0027

# Harden service
ProtectSystem=strict
# /etc/lokilinux/certs is writable too — PKI Faza 4: the agent renews its own
# mTLS cert+key here in place (atomic tmp+rename, cert_renewal.go) before the
# current one expires.
ReadWritePaths=/var/lib/lokilinux /var/log/lokilinux /etc/lokilinux/certs
ProtectHome=true
PrivateTmp=true
NoNewPrivileges=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictNamespaces=true
SystemCallArchitectures=native

[Install]
WantedBy=multi-user.target
EOF

# ── Enable and start ──────────────────────────────────────────────────────────
echo "[*] Enabling and starting lokilinux-agent..."
# Non-root flip (opt-in, same contract as the served template)
if [ "${INSTALL_EXEC_BROKER:-1}" = "1" ]; then
  install -m 644 /dev/null /etc/systemd/system/loki-agent-exec.service
  cat > /etc/systemd/system/loki-agent-exec.service <<'BROKEREOF'
[Unit]
Description=LokiLinux Agent Execution Broker
PartOf=lokilinux-agent.service
After=lokilinux-agent.service

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/loki-agent-exec --socket /run/lokilinux/exec.sock --agent-user loki-agent
Restart=always
RestartSec=5
RestrictAddressFamilies=AF_UNIX
IPAddressDeny=any
ProtectSystem=strict
ReadWritePaths=/run/lokilinux /var/lib/lokilinux
ProtectHome=true
PrivateTmp=true
UMask=0027
TasksMax=64

[Install]
WantedBy=multi-user.target
BROKEREOF
  mkdir -p /run/lokilinux && chmod 750 /run/lokilinux
  chown root:loki-agent /run/lokilinux 2>/dev/null || true
fi

if [ -f /etc/systemd/system/loki-agent-exec.service ] && [ "${AGENT_NON_ROOT:-0}" = "1" ]; then
  sed -i 's/^User=root$/User=loki-agent/' /etc/systemd/system/lokilinux-agent.service
  chown -R loki-agent:loki-agent /var/lib/lokilinux /var/log/lokilinux
  chown root:loki-agent /etc/lokilinux/certs/agent.key 2>/dev/null || true
  chmod 640 /etc/lokilinux/certs/agent.key 2>/dev/null || true
  # Renewal (PKI Faza 4) atomic-renames a new agent.key.tmp into place — that
  # needs write on the DIRECTORY itself, not just the file.
  chown root:loki-agent /etc/lokilinux/certs
  chmod 770 /etc/lokilinux/certs
fi

# ── Exec broker + non-root flip (opt-in, same contract as served template) ────
if [ "${INSTALL_EXEC_BROKER:-1}" = "1" ]; then
  cat > /etc/systemd/system/loki-agent-exec.service <<'BROKEREOF'
[Unit]
Description=LokiLinux Agent Execution Broker
PartOf=lokilinux-agent.service
After=lokilinux-agent.service

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/loki-agent-exec --socket /run/lokilinux/exec.sock --agent-user loki-agent
Restart=always
RestartSec=5
RestrictAddressFamilies=AF_UNIX
IPAddressDeny=any
ProtectSystem=strict
ReadWritePaths=/run/lokilinux /var/lib/lokilinux
ProtectHome=true
PrivateTmp=true
UMask=0027
TasksMax=64

[Install]
WantedBy=multi-user.target
BROKEREOF
  mkdir -p /run/lokilinux && chmod 750 /run/lokilinux
  chown root:loki-agent /run/lokilinux 2>/dev/null || true
fi

if [ -f /etc/systemd/system/loki-agent-exec.service ] && [ "${AGENT_NON_ROOT:-0}" = "1" ]; then
  sed -i 's/^User=root$/User=loki-agent/' /etc/systemd/system/lokilinux-agent.service
  chown -R loki-agent:loki-agent /var/lib/lokilinux /var/log/lokilinux
  chown root:loki-agent /etc/lokilinux/certs/agent.key 2>/dev/null || true
  chmod 640 /etc/lokilinux/certs/agent.key 2>/dev/null || true
  # Renewal (PKI Faza 4) atomic-renames a new agent.key.tmp into place — that
  # needs write on the DIRECTORY itself, not just the file.
  chown root:loki-agent /etc/lokilinux/certs
  chmod 770 /etc/lokilinux/certs
fi

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
