#!/bin/bash
# LokiLinux — job-signing key rotation without breaking in-flight fleet trust.
# Implements the stage → distribute → activate → verify → retire sequence
# from docs/security/JOB_SIGNING_ROTATION.md. Mirrors rotate-ca.sh: every
# step is explicit and guarded, and retirement is NEVER automatic — the old
# version must stay VERIFY_ONLY until the whole fleet has the new one.
#
# Requires LOKILINUX_KEYS_DIR configured on the API (versioned key layout —
# same guard the admin endpoints themselves enforce, 409 otherwise) and an
# ADMIN-role bearer token (ADMIN_TOKEN env var; obtain one by logging in via
# the frontend and copying the session JWT, or see JOB_SIGNING_ROTATION.md).
#
# Usage:
#   ADMIN_TOKEN=<jwt> rotate-job-signing-key.sh stage    [key-id]
#   ADMIN_TOKEN=<jwt> rotate-job-signing-key.sh status   [key-id]
#   ADMIN_TOKEN=<jwt> rotate-job-signing-key.sh activate --confirm [key-id]
#   ADMIN_TOKEN=<jwt> rotate-job-signing-key.sh retire <version> --confirm [key-id]
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
KEY_ID_DEFAULT="job-signing"

C() {
  curl -fsS --max-time 10 \
    -H "Authorization: Bearer ${ADMIN_TOKEN:?ADMIN_TOKEN env var required — see docs/security/JOB_SIGNING_ROTATION.md}" \
    "$@"
}

usage() {
  cat >&2 <<'USAGE'
Usage: rotate-job-signing-key.sh <stage|status|activate|retire> [args]
  stage    [key-id]                    — generate + register a new VERIFY_ONLY version
  status   [key-id]                    — list version:state map
  activate --confirm [key-id]          — promote the newest VERIFY_ONLY version to ACTIVE
  retire   <version> --confirm [key-id] — retire a version (refuses the ACTIVE one)
key-id defaults to "job-signing". --confirm is required for state-changing steps.
USAGE
  exit 1
}

CMD="${1:-}"
[ -n "$CMD" ] || usage
shift || true

case "$CMD" in
  stage)
    KEY_ID="${1:-$KEY_ID_DEFAULT}"
    echo "[*] Staging new version for '$KEY_ID'..."
    RESP="$(C -X POST "$BASE_URL/api/v1/admin/kms/keys/$KEY_ID/versions")"
    echo "$RESP"
    VERSION="$(echo "$RESP" | grep -oE '"version":[0-9]+' | grep -oE '[0-9]+')"
    echo "[+] Staged v${VERSION:-?} as VERIFY_ONLY — signing still uses the prior ACTIVE version."
    echo "    Next: distribute the new public key to the fleet BEFORE activating."
    echo "    GET $BASE_URL/api/v1/agent/signing-keys now includes it; re-run install.sh"
    echo "    on live agents (no runtime push exists — see JOB_SIGNING_ROTATION.md)."
    ;;

  status)
    KEY_ID="${1:-$KEY_ID_DEFAULT}"
    C "$BASE_URL/api/v1/admin/kms/keys/$KEY_ID"
    echo
    ;;

  activate)
    CONFIRM=""
    KEY_ID="$KEY_ID_DEFAULT"
    for a in "$@"; do
      case "$a" in
        --confirm) CONFIRM=1 ;;
        *) KEY_ID="$a" ;;
      esac
    done
    if [ -z "$CONFIRM" ]; then
      echo "ERROR: activate signs ALL new jobs with the new version immediately —" \
           "refusing without --confirm." >&2
      echo "       Verify the fleet has the new key first (status / GET .../agent/signing-keys)." >&2
      exit 1
    fi
    STATUS_JSON="$(C "$BASE_URL/api/v1/admin/kms/keys/$KEY_ID")"
    VERSION="$(echo "$STATUS_JSON" \
      | grep -oE '"[0-9]+": *"VERIFY_ONLY"' | grep -oE '^"[0-9]+"' | tr -d '"' \
      | sort -n | tail -1)"
    if [ -z "$VERSION" ]; then
      echo "ERROR: no VERIFY_ONLY version found to activate — run 'stage' first." >&2
      exit 1
    fi
    echo "[*] Activating v$VERSION for '$KEY_ID'..."
    C -X PATCH -H "Content-Type: application/json" -d '{"state":"ACTIVE"}' \
      "$BASE_URL/api/v1/admin/kms/keys/$KEY_ID/versions/$VERSION"
    echo
    echo "[+] v$VERSION is now ACTIVE. Run a signed-job smoke test now:"
    echo "    scripts/security/e2e_signed_job.sh (or dispatch a real job to a live agent)."
    echo "    Only retire the OLD version once every connected agent accepts v$VERSION."
    ;;

  retire)
    VERSION="${1:-}"; shift || true
    CONFIRM=""
    KEY_ID="$KEY_ID_DEFAULT"
    for a in "$@"; do
      case "$a" in
        --confirm) CONFIRM=1 ;;
        *) KEY_ID="$a" ;;
      esac
    done
    if ! [[ "$VERSION" =~ ^[0-9]+$ ]]; then
      echo "Usage: rotate-job-signing-key.sh retire <version> --confirm [key-id]" >&2
      exit 1
    fi
    if [ -z "$CONFIRM" ]; then
      echo "ERROR: retiring a version any agent still holds locks it out of every signed" \
           "job — refusing without --confirm." >&2
      echo "       Confirm the whole fleet moved off v$VERSION first." >&2
      exit 1
    fi
    echo "[*] Retiring v$VERSION for '$KEY_ID'..."
    C -X PATCH -H "Content-Type: application/json" -d '{"state":"RETIRED"}' \
      "$BASE_URL/api/v1/admin/kms/keys/$KEY_ID/versions/$VERSION"
    echo
    echo "[+] v$VERSION retired — signatures from it are refused from now on."
    ;;

  *) usage ;;
esac
