#!/bin/bash
# LokiLinux — First-Run Initialisation Script
# Run once after `cp .env.example .env` and editing .env
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$ROOT_DIR"

echo "[*] LokiLinux — Docker initialisation"

# 1. Require .env ---------------------------------------------------------
if [ ! -f .env ]; then
  echo "[!] .env not found. Creating from .env.example..."
  cp .env.example .env
  echo "[!] Edit .env with your configuration, then re-run this script."
  exit 1
fi

# shellcheck disable=SC1091
source .env

# 2. Certificates ---------------------------------------------------------
if [ ! -f ".certs/ca.crt" ]; then
  echo "[*] Certificates not found — generating..."
  bash scripts/init-certificates.sh .certs "${PLATFORM_HOSTNAME:-lokilinux.example.com}" "${CERT_VALIDITY_DAYS:-365}"
fi

# 3. Required directories -------------------------------------------------
echo "[*] Creating runtime directories..."
mkdir -p logs/{api,frontend} backups

# 4. Docker volumes -------------------------------------------------------
echo "[*] Creating named volumes..."
docker volume create lokilinux-postgres-data  2>/dev/null || true
docker volume create lokilinux-nats-data      2>/dev/null || true
docker volume create lokilinux-redis-data     2>/dev/null || true
docker volume create lokilinux-plugins        2>/dev/null || true
docker volume create lokilinux-certs          2>/dev/null || true

# 5. Copy certificates into Docker volume ---------------------------------
echo "[*] Copying certificates into lokilinux-certs volume..."
docker run --rm \
  -v lokilinux-certs:/certs \
  -v "$(pwd)/.certs":/source:ro \
  alpine:latest \
  sh -c "cp -r /source/* /certs/ && chmod 600 /certs/*.key && chmod 644 /certs/*.crt"

# 6. Build images ---------------------------------------------------------
echo "[*] Building Docker images..."
docker compose build

# 7. Start infrastructure services first ----------------------------------
echo "[*] Starting infrastructure (postgres, pgbouncer, nats, redis)..."
docker compose up -d postgres nats redis
sleep 5
docker compose up -d pgbouncer

# 8. Wait for postgres ready ----------------------------------------------
echo "[*] Waiting for PostgreSQL..."
for i in $(seq 1 30); do
  if docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-lokilinux}" >/dev/null 2>&1; then
    echo "[+] PostgreSQL ready"
    break
  fi
  echo "    ... ($i/30)"
  sleep 3
done

# 9. Start application services -------------------------------------------
echo "[*] Starting application services..."
docker compose up -d lokilinux-api lokilinux-grpc lokilinux-frontend

# 10. Wait for API ready --------------------------------------------------
echo "[*] Waiting for API..."
for i in $(seq 1 20); do
  if docker compose exec -T lokilinux-api curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    echo "[+] API ready"
    break
  fi
  echo "    ... ($i/20)"
  sleep 3
done

# 11. Run Alembic migrations ----------------------------------------------
echo "[*] Running database migrations..."
docker compose exec -T lokilinux-api alembic upgrade head

# 11b. Run Better Auth migrations (creates user/session/account/... tables) --
echo "[*] Running Better Auth migrations..."
( cd frontend && npx --yes tsx scripts/migrate-db.ts )

# 12. Create default admin via Better Auth admin API ----------------------
echo "[*] Creating default admin user..."
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@lokilinux.local}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-$(openssl rand -base64 16)}"

# Bootstrap: admin plugin's /admin/create-user needs an existing admin session,
# so the first admin is created via the public sign-up endpoint, then promoted
# to role=admin directly in the DB (chicken-and-egg bootstrap).
docker compose exec -T lokilinux-frontend node - <<NODEEOF
// Post to localhost inside the container; set Origin to the trusted baseURL
// so Better Auth's origin check passes.
const origin = process.env.BETTER_AUTH_URL || "http://localhost:3000";
const res = await fetch("http://localhost:3000/api/auth/sign-up/email", {
  method: "POST",
  headers: { "Content-Type": "application/json", "Origin": origin },
  body: JSON.stringify({
    email: "$ADMIN_EMAIL",
    password: "$ADMIN_PASSWORD",
    name: "Admin",
    username: "admin",
  }),
});
if (res.ok) console.log("[+] Admin user created");
else {
  const t = await res.text();
  if (t.includes("already exists") || res.status === 422) console.log("[+] Admin user already exists");
  else console.log("[!] Admin sign-up returned " + res.status + ": " + t);
}
NODEEOF

# Promote to admin role
docker compose exec -T postgres psql -U "\${POSTGRES_USER:-lokilinux}" -d "\${POSTGRES_DB:-lokilinux}" \
  -c "UPDATE \"user\" SET role='admin' WHERE email='$ADMIN_EMAIL';"

# 13. Status --------------------------------------------------------------
echo ""
docker compose ps
echo ""
echo "[+] LokiLinux initialised successfully!"
echo ""
echo "Access:"
echo "  Web UI : https://${PLATFORM_HOSTNAME:-localhost}"
echo "  API    : http://localhost:8000/docs"
echo "  gRPC   : localhost:50051 (mTLS)"
echo ""
echo "Admin credentials:"
echo "  Email   : $ADMIN_EMAIL"
echo "  Password: $ADMIN_PASSWORD"
echo ""
echo "Next: change the admin password, generate an agent enrollment token, install agents."
