#!/bin/bash
# LokiLinux — Certificate Generation Script
# Generates: CA, server certificate (for gRPC), and a client template (for agent enrollment)
# Usage: bash scripts/init-certificates.sh [certs-dir] [hostname] [validity-days]
set -euo pipefail

CERTS_DIR="${1:-/etc/lokilinux/certs}"
PLATFORM_HOSTNAME="${2:-lokilinux.example.com}"
VALIDITY_DAYS="${3:-365}"

mkdir -p "$CERTS_DIR"

# Idempotent: regenerating the CA would break trust for every already-enrolled
# agent. Skip if certs exist; pass FORCE=1 to deliberately regenerate.
if [ -f "$CERTS_DIR/ca.crt" ] && [ "${FORCE:-0}" != "1" ]; then
  echo "[=] Certificates already exist in $CERTS_DIR — skipping (set FORCE=1 to regenerate)."
  exit 0
fi

echo "[*] Generating CA key and self-signed certificate..."
openssl genrsa -out "$CERTS_DIR/ca.key" 4096
openssl req -new -x509 \
  -days "$VALIDITY_DAYS" \
  -key "$CERTS_DIR/ca.key" \
  -out "$CERTS_DIR/ca.crt" \
  -subj "/CN=LokiLinux-CA/O=LokiLinux/C=US"

# Build SAN list. Each host is classified DNS: vs IP: automatically — agents that
# connect to an IP (grpc_endpoint 192.168.x.x:50051) need an IP SAN, not DNS.
# Extra names can be added via EXTRA_SANS="host1,host2" (comma-separated).
san_entry() {
  case "$1" in
    *[!0-9.]*) echo "DNS:$1" ;;   # contains a non-(digit/dot) char → hostname
    *)         echo "IP:$1"  ;;   # pure digits+dots → IPv4 literal
  esac
}
SAN_LIST="$(san_entry "$PLATFORM_HOSTNAME"),DNS:lokilinux-grpc,DNS:localhost,IP:127.0.0.1"
if [ -n "${EXTRA_SANS:-}" ]; then
  IFS=',' read -ra _extra <<< "$EXTRA_SANS"
  for h in "${_extra[@]}"; do
    [ -n "$h" ] && SAN_LIST="$SAN_LIST,$(san_entry "$h")"
  done
fi

echo "[*] Generating server key and certificate (SANs: $SAN_LIST)..."
openssl genrsa -out "$CERTS_DIR/server.key" 4096
openssl req -new \
  -key "$CERTS_DIR/server.key" \
  -out "$CERTS_DIR/server.csr" \
  -subj "/CN=$PLATFORM_HOSTNAME/O=LokiLinux/C=US"

# SAN extension — required for modern gRPC clients
cat > "$CERTS_DIR/server_ext.cnf" <<EOF
[req]
req_extensions = v3_req
[v3_req]
subjectAltName = $SAN_LIST
EOF

openssl x509 -req \
  -days "$VALIDITY_DAYS" \
  -in "$CERTS_DIR/server.csr" \
  -CA "$CERTS_DIR/ca.crt" \
  -CAkey "$CERTS_DIR/ca.key" \
  -CAcreateserial \
  -extfile "$CERTS_DIR/server_ext.cnf" \
  -extensions v3_req \
  -out "$CERTS_DIR/server.crt"

echo "[*] Generating agent client certificate template..."
openssl genrsa -out "$CERTS_DIR/agent-template.key" 4096
openssl req -new \
  -key "$CERTS_DIR/agent-template.key" \
  -out "$CERTS_DIR/agent-template.csr" \
  -subj "/CN=agent-template/O=LokiLinux-Agents/C=US"
openssl x509 -req \
  -days "$VALIDITY_DAYS" \
  -in "$CERTS_DIR/agent-template.csr" \
  -CA "$CERTS_DIR/ca.crt" \
  -CAkey "$CERTS_DIR/ca.key" \
  -CAcreateserial \
  -out "$CERTS_DIR/agent-template.crt"

# Secure private keys; CAs and certs stay readable
chmod 600 "$CERTS_DIR"/*.key
chmod 644 "$CERTS_DIR"/*.crt "$CERTS_DIR"/*.csr 2>/dev/null || true
rm -f "$CERTS_DIR/server_ext.cnf"

echo "[+] Certificates written to $CERTS_DIR"
ls -lh "$CERTS_DIR"
echo ""
echo "Files:"
echo "  CA:             $CERTS_DIR/ca.crt  (distribute to all agents)"
echo "  Server cert:    $CERTS_DIR/server.crt + server.key"
echo "  Agent template: $CERTS_DIR/agent-template.crt (sign per-agent certs from CA)"
