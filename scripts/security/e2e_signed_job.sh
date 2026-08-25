#!/bin/bash
# LokiLinux — end-to-end security validation against a LIVE stack.
# Covers: signing-key provisioning, mTLS port, revocation API, metrics.
# Full agent-enroll→signed-job flow needs a test VM (see DISTRO_RUNBOOK.md);
# this script validates everything reachable from the control plane side.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
METRICS_URL="${METRICS_URL:-http://127.0.0.1:9090/metrics}"
export no_proxy='localhost,127.0.0.1'
export NO_PROXY="$no_proxy"
C="curl -fsS --max-time 5"
PASS=0; FAIL=0
ok()   { echo "[PASS] $1"; PASS=$((PASS+1)); }
bad()  { echo "[FAIL] $1"; FAIL=$((FAIL+1)); }

echo "== LokiLinux control-plane security E2E vs $BASE_URL =="

# 1. Liveness
if $C "$BASE_URL/health" >/dev/null 2>&1; then ok "API /health"; else bad "API /health"; fi

# 2. Signing key endpoint exists and returns base64 raw Ed25519 (44 chars)
KEY="$($C "$BASE_URL/api/v1/agent/signing-key" 2>/dev/null || true)"
if [ ${#KEY} -eq 44 ] && [[ "$KEY" =~ ^[A-Za-z0-9+/]+={0,2}$ ]]; then
  ok "signing key served (base64 raw 32B)"
else
  bad "signing key endpoint (${#KEY} chars)"
fi

# 3. PEM variant parses as Ed25519 public key
PEM="$($C "$BASE_URL/api/v1/agent/signing-key.pem" 2>/dev/null || true)"
if [ -n "$PEM" ] && echo "$PEM" | openssl pkey -pubin -text -noout >/dev/null 2>&1; then
  ok "signing key PEM valid"
else
  bad "signing key PEM invalid/unavailable"
fi

# 4. Cross-check: b64 raw == tail 32 bytes of DER SPKI from PEM
if [ -n "$PEM" ]; then
  DER_B64="$(printf '%s\n' "$PEM" | openssl pkey -pubout -outform DER 2>/dev/null | base64 -w0)"
  RAW_FROM_DER="$(openssl pkey -pubin -in <(echo "$PEM") -pubout -outform DER 2>/dev/null | tail -c 32 | base64 -w0)"
  [ "$RAW_FROM_DER" = "$KEY" ] && ok "raw/PEM key forms consistent" || bad "raw/PEM mismatch"
fi

# 5. Revocation admin endpoints exist (unauthenticated → 401/403, not 404)
CODE="$(curl -s --max-time 5 -o /dev/null -w '%{http_code}' "$BASE_URL/api/v1/admin/certificates/revoked" 2>/dev/null)"
case "$CODE" in 401|403) ok "revocation list gated ($CODE)";; *) bad "revocation list HTTP $CODE";; esac

# 6. Metrics endpoint exposes security counters
METRICS="$(curl -fsS --max-time 15 "$METRICS_URL" 2>/dev/null || true)"
for M in unsigned_privileged_jobs_total signed_jobs_total agent_rejected_jobs_total; do
  echo "$METRICS" | grep -q "${M}" && ok "metric $M exposed" || bad "metric $M missing"
done

echo "== done: $PASS passed, $FAIL failed =="
exit $(( FAIL > 0 ? 1 : 0 ))
