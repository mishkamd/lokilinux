#!/bin/sh
# Post-install for the .deb/.rpm agent package. The package only ships the
# binary — enrollment (certs + /etc/lokilinux/agent.yaml + systemd unit) is done
# separately via the control-plane installer:
#   curl -fsSL <platform>/api/v1/agent/install.sh | bash -s -- --token=<token>
set -e

if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload >/dev/null 2>&1 || true
fi

echo "[+] lokilinux-agent binary installed to /usr/local/bin/lokilinux-agent"
echo "    This is the binary only — not yet enrolled or running."
echo "    Get your enrollment command from the LokiLinux dashboard: Agents -> Add Agent"
echo "    (it will look like: curl -fsSL https://YOUR-PLATFORM/api/v1/agent/install.sh | bash -s -- --token=YOUR-TOKEN)"
