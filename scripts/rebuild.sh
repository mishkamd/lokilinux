#!/bin/bash
# LokiLinux — Docker rebuild & start
# Usage: bash scripts/rebuild.sh [--clean]
#   --clean  also wipes volumes (fresh DB, fresh certs)
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[1/6] Stopping stack..."
docker compose down 2>/dev/null || true

echo "[2/6] Cleaning frontend build artifacts..."
rm -rf frontend/.nuxt frontend/.output

echo "[3/6] Cleaning Docker cache..."
docker builder prune -a -f 2>/dev/null || true
docker system prune -f 2>/dev/null || true

if [[ "${1:-}" == "--clean" ]]; then
  echo "[3b/6] Removing volumes..."
  docker compose down -v 2>/dev/null || true
  docker volume ls -q | grep lokilinux | xargs -r docker volume rm 2>/dev/null || true
fi

echo "[4/6] Building images..."
docker compose build

echo "[5/6] Generating certificates..."
docker run --rm -v lokilinux-certs:/certs alpine:latest sh -c "
  apk add --no-cache openssl >/dev/null 2>&1 &&
  cd /certs &&
  openssl genrsa -out ca.key 4096 &&
  openssl req -new -x509 -days 365 -key ca.key -out ca.crt -subj '/CN=LokiLinux-CA/O=LokiLinux/C=US' &&
  openssl genrsa -out server.key 4096 &&
  openssl req -new -key server.key -out server.csr -subj '/CN=lokilinux.example.com/O=LokiLinux/C=US' &&
  printf '[req]\nreq_extensions = v3_req\n[v3_req]\nsubjectAltName = DNS:lokilinux.example.com,DNS:lokilinux-grpc,DNS:localhost,IP:127.0.0.1\n' > ext.cnf &&
  openssl x509 -req -days 365 -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -extfile ext.cnf -extensions v3_req -out server.crt &&
  chmod 600 *.key && chmod 644 *.crt &&
  rm -f ext.cnf server.csr
"

echo "[6/6] Starting stack..."
docker compose up -d

echo ""
echo "Waiting for services..."
sleep 8

echo ""
docker compose ps

echo ""
echo "Testing endpoints..."
curl -s -o /dev/null -w "  frontend : %{http_code}\n" http://127.0.0.1:3000/ 2>/dev/null || echo "  frontend : unreachable"
curl -s -o /dev/null -w "  API      : %{http_code}\n" http://127.0.0.1:8000/health 2>/dev/null || echo "  API      : unreachable"

echo ""
echo "[done] LokiLinux stack ready"
