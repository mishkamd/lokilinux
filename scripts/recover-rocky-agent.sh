#!/bin/bash
# Rocky recovery — rulează PE CONSOLA host-ului rocky (192.168.0.237, root).
# Repară agent.yaml-ul stricat de job-ul de acum (blocul policy: invalid) și
# repornește agentul. Idempotent.
set -euo pipefail

echo "[*] Stare agent:"
systemctl is-active lokilinux-agent || true

echo "[*] Curăț /etc/lokilinux/agent.yaml (elimin orice bloc policy: invalid)..."
python3 - <<'PYEOF'
import re
p = "/etc/lokilinux/agent.yaml"
src = open(p).read()
# eliminăm TOATE blocurile policy: (conținutul lor poate fi invalid YAML)
src = re.sub(r"\n*policy:\n(?:[ \t]+.*\n?)+", "\n", src)
open(p, "w").write(src.rstrip() + "\n")
PYEOF

echo "[*] Verific că YAML-ul rezultat parsează:"
python3 -c "import yaml; yaml.safe_load(open('/etc/lokilinux/agent.yaml')); print('YAML OK')"

echo "[*] Regenerez blocul policy cu cheia publică REALĂ de pe control plane..."
PK=$(curl -fsSL http://192.168.0.110:8000/api/v1/agent/policy-signing-key)
[ -n "$PK" ] || { echo "EROARE: nu pot lua cheia de pe control plane"; exit 1; }
cat >> /etc/lokilinux/agent.yaml <<EOF
policy:
  enabled: true
  state_dir: /var/lib/lokilinux/policy
  trusted_keys:
    policy-signing-v1: "$PK"
EOF

python3 -c "import yaml; yaml.safe_load(open('/etc/lokilinux/agent.yaml')); print('YAML final OK')"
mkdir -p -m 700 /var/lib/lokilinux/policy

echo "[*] Restart agent..."
systemctl restart lokilinux-agent
sleep 5
systemctl is-active lokilinux-agent && echo "[+] Agent ACTIV" || { echo "[!] Agent încă căzut — journalctl -u lokilinux-agent -n 30"; exit 1; }

echo "[+] Gata. Verifică pe dashboard (Agents → rocky) că heartbeat revine, apoi re-deploy policy din UI."
