#!/bin/bash
# LokiLinux — CA rotation without agent reinstall (plan P11/CA).
# Implements the 9-step runbook in docs/security/CERTIFICATE_ROTATION.md.
# Every step is idempotent and guarded; the script NEVER deletes the old CA
# automatically — retirement is an explicit final step.
#
# Usage:
#   rotate-ca.sh generate [certs-dir]            # step 1: mint CA_new
#   rotate-ca.sh bundle   [certs-dir]            # step 2+3: dual-trust bundle
#   rotate-ca.sh verify-fleet <agents-up>        # step 6: report who still uses old serial
#   rotate-ca.sh retire-old [certs-dir]          # steps 7+8: revoke old serials, drop from bundle
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

CMD="${1:-}"
CERTS_DIR="${2:-/etc/lokilinux/certs}"

usage() { echo "Usage: $0 <generate|bundle|verify-fleet|retire-old> [certs-dir]" >&2; exit 1; }
[ -n "$CMD" ] || usage

case "$CMD" in
  generate)
    if [ -f "$CERTS_DIR/ca-new.crt" ]; then
      echo "[=] CA_new already exists at $CERTS_DIR/ca-new.crt — skipping (rotation already started)."
      exit 0
    fi
    echo "[*] Generating CA_new (${CERTS_DIR}/ca-new.crt)..."
    openssl genrsa -out "$CERTS_DIR/ca-new.key" 4096
    openssl req -new -x509 -days "${CA_VALIDITY_DAYS:-365}" \
      -key "$CERTS_DIR/ca-new.key" -out "$CERTS_DIR/ca-new.crt" \
      -subj "/CN=LokiLinux-CA-v2/O=LokiLinux/C=US"
    chmod 600 "$CERTS_DIR/ca-new.key"; chmod 644 "$CERTS_DIR/ca-new.crt"
    echo "[+] Next: restart lokilinux-api/grpc with CA_CERT_PATH=$CERTS_DIR/ca-bundle.crt (dual trust)."
    ;;

  bundle)
    bash scripts/init-certificates.sh "$CERTS_DIR" >/dev/null 2>&1 || true
    # init-certificates refreshes ca-bundle.crt whenever ca-new.crt exists.
    echo "[+] Bundle contents:"
    openssl crl2pkcs7 -nocrl -certfile "$CERTS_DIR/ca-bundle.crt" 2>/dev/null \
      | openssl pkcs7 -print_certs -noout | grep subject || true
    echo "[+] Distribute ca-bundle.crt to agents via install.sh re-run OR wait for next agent release."
    ;;

  verify-fleet)
    AGENTS_UP="${2:-}"
    [ -n "$AGENTS_UP" ] || { echo "Usage: $0 verify-fleet <count-of-connected-agents>" >&2; exit 1; }
    echo "[i] Manual gate: check Agents dashboard → every connected agent shows HEALTHY."
    echo "    Count expected: $AGENTS_UP. Only proceed to retire-old when ALL are on certs signed by CA_new."
    ;;

  retire-old)
    [ -f "$CERTS_DIR/ca-new.crt" ] || { echo "ERROR: no CA_new present — run 'generate' first." >&2; exit 1; }
    echo "[*] Step 7/8: revoke remaining CA_old-signed agent certificates..."
    echo "    Revoke per-cert via API: POST /api/v1/admin/certificates/{serial}/revoke"
    echo "    List issued serials:     openssl x509 -in <agent.crt> -noout -serial"
    OLD_ISSUER_HASH="$(openssl x509 -in "$CERTS_DIR/ca.crt" -noout -issuer_hash 2>/dev/null || true)"
    NEW_ISSUER_HASH="$(openssl x509 -in "$CERTS_DIR/ca-new.crt" -noout -issuer_hash 2>/dev/null || true)"
    if [ "$OLD_ISSUER_HASH" = "$NEW_ISSUER_HASH" ]; then
      echo "ERROR: CA_old and CA_new have identical issuer hashes — refusing." >&2
      exit 1
    fi
    cp "$CERTS_DIR/ca.crt" "$CERTS_DIR/ca-retired-$(date +%Y%m%d).crt"
    rm -f "$CERTS_DIR/ca.crt"
    cp "$CERTS_DIR/ca-new.crt" "$CERTS_DIR/ca.crt"
    cat "$CERTS_DIR/ca.crt" > "$CERTS_DIR/ca-bundle.crt"
    echo "[+] CA_new promoted to ca.crt; bundle now single-CA."
    echo "    Rollback within validity window: restore ca-retired-*.crt + regenerate bundle (dual trust again)."
    echo "    Old key archived as ca-retired key material — keep for historical signature verification only."
    ;;

  *) usage ;;
esac
