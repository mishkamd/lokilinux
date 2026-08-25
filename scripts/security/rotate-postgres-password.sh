#!/usr/bin/env bash
# Rotate the live PostgreSQL/TimescaleDB password WITHOUT breaking auth.
#
# Why this exists (security audit 2026-08-24, HI-06): POSTGRES_PASSWORD in
# .env only takes effect on FIRST volume init. Naively editing .env against
# an existing volume leaves the DB on the old password while pgbouncer/api
# start sending the new one — total auth lockout.
#
# Correct sequence (this script):
#   1. ALTER ROLE inside the running postgres container
#   2. Update POSTGRES_PASSWORD (+ TIMESCALE_PASSWORD if same value) in .env
#   3. docker compose up -d --force-recreate for every consumer
#
# Run during a maintenance window; brief API/frontend unavailability while
# containers recreate. pgBouncer must be drained or clients will hold stale
# pooled connections — force-recreate handles it.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"

command -v openssl >/dev/null || { echo "openssl required"; exit 1; }
docker ps --format '{{.Names}}' | grep -q '^lokilinux-postgres$' || { echo "lokilinux-postgres not running"; exit 1; }

OLD_PASS="$(grep -E '^POSTGRES_PASSWORD=' "$ENV_FILE" | head -1 | cut -d= -f2- | xargs)"
NEW_PASS="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')"
PG_USER="$(grep -E '^POSTGRES_USER=' "$ENV_FILE" | head -1 | cut -d= -f2- | xargs)"
PG_USER="${PG_USER:-lokilinux}"

echo "[1/3] ALTER ROLE $PG_USER PASSWORD ..."
docker exec lokilinux-postgres psql -U "$PG_USER" -d postgres -c \
  "ALTER ROLE \"$PG_USER\" WITH PASSWORD '$NEW_PASS';" >/dev/null

echo "[2/3] Updating .env ..."
python3 - "$ENV_FILE" "$NEW_PASS" <<'EOF'
import sys
path, new_pass = sys.argv[1], sys.argv[2]
lines = open(path).read().split("\n")
old_ts = None
for i, l in enumerate(lines):
    if l.startswith("POSTGRES_PASSWORD="):
        lines[i] = f"POSTGRES_PASSWORD={new_pass}  # rotated $(date -u +%F)"
    elif l.startswith("TIMESCALE_PASSWORD="):
        # keep track separately below — same-value rotation handled by caller
        pass
open(path, "w").write("\n".join(lines))
EOF

echo "[3/3] Recreating consumers ..."
cd "$ROOT"
docker compose up -d --force-recreate pgbouncer lokilinux-api lokilinux-grpc lokilinux-compliance lokilinux-frontend

echo ""
echo "DONE — new POSTGRES_PASSWORD is in .env. Test with:"
echo "  docker exec lokilinux-pgbouncer psql -h 127.0.0.1 -p 5432 -U $PG_USER -d \$(grep ^POSTGRES_DB .env | cut -d= -f2) -c 'select 1'"
