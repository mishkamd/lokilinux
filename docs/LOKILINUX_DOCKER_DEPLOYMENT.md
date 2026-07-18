# LokiLinux — Docker Deployment & Plugin System Guide

---

## I. DOCKER ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────────────────┐
│         Docker Compose Stack (LokiLinux)               │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐ │
│  │   postgres   │  │    nats      │  │    redis      │ │
│  │  (database)  │  │  (messaging) │  │   (cache)     │ │
│  └──────────────┘  └──────────────┘  └───────────────┘ │
│         │                  │                  │         │
│  ┌──────┴──────────────────┴──────────────────┴──────┐  │
│  │                                                    │  │
│  │  ┌────────────────────────────────────────────┐   │  │
│  │  │  API Container (lokilinux-api)            │   │  │
│  │  │  - FastAPI (port 8000)                     │   │  │
│  │  │  - gRPC (port 50051)                       │   │  │
│  │  │  - Core services built-in                  │   │  │
│  │  └────────────────────────────────────────────┘   │  │
│  │                        │                           │  │
│  │  ┌────────────────────┴─────────────────────┐    │  │
│  │  │  Plugin Sandbox Dir                      │    │  │
│  │  │  /opt/plugins/                           │    │  │
│  │  │  ├── zabbix-connector/                  │    │  │
│  │  │  ├── nessus-connector/                  │    │  │
│  │  │  ├── jira-connector/                    │    │  │
│  │  │  └── [other plugins]                    │    │  │
│  │  │                                          │    │  │
│  │  │  (mounts into API container runtime)    │    │  │
│  │  └──────────────────────────────────────────┘    │  │
│  │                                                    │  │
│  └────────────────────────────────────────────────────┘  │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐ │
│  │   Frontend   │  │  Reverse     │  │  File         │ │
│  │  (Nuxt 4)    │  │  Proxy       │  │  Storage      │ │
│  │ (port 3000)  │  │  (NGINX)     │  │  (backups)    │ │
│  │              │  │ (port 443)   │  │               │ │
│  └──────────────┘  └──────────────┘  └───────────────┘ │
│                                                         │
└─────────────────────────────────────────────────────────┘
         │
         │ Network: lokilinux-net
         │
         ├─ Agents connect via gRPC (port 50051)
         └─ UI accessible via HTTPS (port 443)
```

---

## II. ENV CONFIGURATION

### 2.1 Root `.env` File (docker-compose level)

**File:** `.env` (root directory)

```bash
# ============================================================================
# LokiLinux Docker Deployment Configuration
# ============================================================================

# Deployment Environment
ENVIRONMENT=production                          # development | staging | production
DEPLOY_REGION=eu-central-1                      # For multi-region setup

# ============================================================================
# CORE PLATFORM IDENTITY
# ============================================================================

PLATFORM_NAME=LokiLinux Production
PLATFORM_HOSTNAME=lokilinux.example.com         # FQDN used in certificates
PLATFORM_VERSION=1.0.0

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
API_GRPC_PORT=50051
API_WORKERS=4                                   # Number of gunicorn workers

# Frontend Configuration
FRONTEND_HOST=0.0.0.0
FRONTEND_PORT=3000
FRONTEND_URL=https://lokilinux.example.com     # Public URL (used in redirects)

# Reverse Proxy (NGINX)
NGINX_PORT=443
NGINX_HTTP_PORT=80
NGINX_SSL_CERT=/etc/nginx/certs/lokilinux.crt  # Path inside container
NGINX_SSL_KEY=/etc/nginx/certs/lokilinux.key

# ============================================================================
# DATABASE
# ============================================================================

POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=lokilinux
POSTGRES_USER=lokilinux
POSTGRES_PASSWORD=your_secure_postgres_password_here  # Change this!
POSTGRES_POOL_SIZE=20
POSTGRES_POOL_RECYCLE=3600

# TimescaleDB (metrics)
TIMESCALEDB_HOST=postgres
TIMESCALEDB_PORT=5432
TIMESCALEDB_DB=lokilinux_metrics
TIMESCALEDB_USER=metrics_user
TIMESCALEDB_PASSWORD=your_secure_metrics_password  # Change this!

# Database Backup
POSTGRES_BACKUP_RETENTION_DAYS=30
POSTGRES_BACKUP_PATH=/var/backups/postgres

# ============================================================================
# MESSAGE QUEUE (NATS)
# ============================================================================

NATS_HOST=nats
NATS_PORT=4222
NATS_CLUSTER_PORT=6222
NATS_MONITOR_PORT=8222
NATS_JETSTREAM_ENABLED=true
NATS_JETSTREAM_STORE=/data/jetstream           # Persistence dir inside container

# ============================================================================
# CACHE (REDIS)
# ============================================================================

REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=your_secure_redis_password      # Change this!
REDIS_MAXMEMORY=2gb
REDIS_EVICTION_POLICY=allkeys-lru

# ============================================================================
# AUTHENTICATION & SECURITY
# ============================================================================

# JWT Secret (for API tokens)
JWT_SECRET_KEY=your_super_secret_jwt_key_change_this_to_random_string_64_chars_minimum
JWT_ALGORITHM=HS256
JWT_EXPIRATION_MINUTES=15
JWT_REFRESH_EXPIRATION_DAYS=7

# mTLS Certificates (Agent Communication)
CA_CERT_PATH=/etc/lokilinux/certs/ca.crt
CA_KEY_PATH=/etc/lokilinux/certs/ca.key
CERT_VALIDITY_DAYS=365
CERT_RENEWAL_DAYS=30

# API Key Salt
API_KEY_SALT=your_api_key_salt_change_this
ENCRYPTION_KEY=your_encryption_key_32_chars_minimum_for_aes256

# OAuth2 (optional)
OAUTH2_ENABLED=false
OAUTH2_PROVIDER=keycloak                       # keycloak | azure_ad | google
OAUTH2_CLIENT_ID=your_oauth_client_id
OAUTH2_CLIENT_SECRET=your_oauth_client_secret
OAUTH2_AUTHORIZATION_URL=https://auth.example.com/authorize
OAUTH2_TOKEN_URL=https://auth.example.com/token
OAUTH2_USER_INFO_URL=https://auth.example.com/userinfo

# LDAP (optional)
LDAP_ENABLED=false
LDAP_SERVER=ldap.example.com
LDAP_PORT=389
LDAP_BASE_DN=dc=example,dc=com
LDAP_BIND_DN=cn=admin,dc=example,dc=com
LDAP_BIND_PASSWORD=ldap_password

# ============================================================================
# AGENT CONFIGURATION
# ============================================================================

# Agent heartbeat settings
AGENT_HEARTBEAT_INTERVAL=60                    # seconds
AGENT_HEARTBEAT_TIMEOUT=30
AGENT_MAX_OFFLINE_DAYS=30

# Agent registration
AGENT_REGISTRATION_TOKEN_TTL=3600              # seconds (1 hour)
AGENT_CERT_RENEWAL_THRESHOLD=30                # days before expiry

# ============================================================================
# CVE & VULNERABILITY MANAGEMENT
# ============================================================================

# CVE Database Sources
CVE_FEED_UPDATE_INTERVAL=86400                 # 24 hours (seconds)
CVE_FEED_SOURCES=ubuntu,debian,rhel,nvd       # Enabled sources
CVE_RETENTION_DAYS=730                         # 2 years

# NVD API (optional, for enhanced data)
NVD_API_KEY=your_nvd_api_key_optional
NVD_API_RATE_LIMIT=120                         # requests per hour

# Ubuntu Security Notices API
UBUNTU_SECURITY_API_ENABLED=true

# Debian Security Tracker
DEBIAN_SECURITY_API_ENABLED=true

# RedHat/CentOS Errata
REDHAT_SECURITY_API_ENABLED=true

# ============================================================================
# PLUGIN SYSTEM
# ============================================================================

# Plugin Configuration
PLUGINS_ENABLED=true
PLUGINS_DIR=/opt/plugins                       # Where plugins are extracted/stored
PLUGINS_SANDBOX_MODE=true                      # Run plugins in sandbox (isolate)
PLUGINS_MAX_MEMORY_MB=256                      # Per-plugin memory limit
PLUGINS_MAX_CPU_CORES=1                        # Per-plugin CPU limit
PLUGINS_ISOLATION_TYPE=namespace                # namespace | cgroup | docker

# Plugin Marketplace
PLUGIN_MARKETPLACE_URL=https://plugins.lokilinux.io/api/v1
PLUGIN_MARKETPLACE_API_KEY=your_marketplace_api_key
PLUGIN_AUTO_UPDATE_ENABLED=false               # Don't auto-update plugins
PLUGIN_SECURITY_SCAN_ENABLED=true              # Scan plugins on install

# Built-in Plugins (can be pre-installed)
PLUGINS_BUILTIN=                               # Empty = none (just core)
# PLUGINS_BUILTIN=zabbix-connector,nessus-connector,jira-connector

# ============================================================================
# LOGGING & OBSERVABILITY
# ============================================================================

# Logging
LOG_LEVEL=info                                 # debug | info | warning | error
LOG_FORMAT=json                                # json | text
LOG_OUTPUT=stdout                              # stdout | file
LOG_FILE_PATH=/var/log/lokilinux/app.log

# Audit Logging
AUDIT_LOG_ENABLED=true
AUDIT_LOG_RETENTION_DAYS=730                   # 2 years
AUDIT_LOG_COMPRESSION=true                     # Compress old logs

# Metrics & Observability
METRICS_ENABLED=true
METRICS_PORT=9090
PROMETHEUS_SCRAPE_INTERVAL=15                  # seconds

# Tracing (OpenTelemetry)
TRACING_ENABLED=false
TRACING_JAEGER_ENDPOINT=http://jaeger:14268/api/traces
TRACING_SAMPLE_RATE=0.1                        # 10% sampling

# ============================================================================
# NOTIFICATIONS & ALERTING
# ============================================================================

# Email (SMTP)
SMTP_ENABLED=false
SMTP_HOST=mail.example.com
SMTP_PORT=587
SMTP_USERNAME=noreply@example.com
SMTP_PASSWORD=your_smtp_password
SMTP_FROM_ADDRESS=noreply@example.com
SMTP_TLS_ENABLED=true

# Slack Notifications (optional)
SLACK_ENABLED=false
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL

# PagerDuty (optional)
PAGERDUTY_ENABLED=false
PAGERDUTY_INTEGRATION_KEY=your_pagerduty_key

# ============================================================================
# BACKUP & STORAGE
# ============================================================================

# Local Storage
BACKUP_DIR=/var/backups/lokilinux
BACKUP_RETENTION_DAYS=30
BACKUP_COMPRESSION=gzip

# S3 Backup (optional)
S3_BACKUP_ENABLED=false
S3_BUCKET=lokilinux-backups
S3_REGION=eu-central-1
S3_ACCESS_KEY=your_aws_access_key
S3_SECRET_KEY=your_aws_secret_key
S3_ENDPOINT=https://s3.amazonaws.com            # or MinIO endpoint

# ============================================================================
# DOCKER IMAGE VERSIONS
# ============================================================================

POSTGRES_IMAGE_VERSION=15-alpine
NATS_IMAGE_VERSION=2.10-alpine
REDIS_IMAGE_VERSION=7-alpine
NGINX_IMAGE_VERSION=1.25-alpine
LOKILINUX_API_IMAGE_VERSION=latest              # or specific version tag
LOKILINUX_FRONTEND_IMAGE_VERSION=latest

# ============================================================================
# DEVELOPMENT / DEBUG
# ============================================================================

DEBUG=false
RELOAD_ON_CHANGE=false                         # Auto-reload API on code change (dev only)
MOCK_AGENTS=false                              # Generate fake agents for testing
DEMO_MODE=false                                # Limited features for demo

# ============================================================================
# RESOURCE LIMITS
# ============================================================================

# CPU & Memory limits (for compose, overridden by kubernetes limits)
API_MEMORY_LIMIT=2g
API_CPU_LIMIT=2000m
FRONTEND_MEMORY_LIMIT=512m
FRONTEND_CPU_LIMIT=500m

# ============================================================================
# NETWORKING
# ============================================================================

DOCKER_NETWORK_NAME=lokilinux-net
DOCKER_NETWORK_DRIVER=bridge

# For multi-host setup (Swarm/K8s)
SERVICE_DISCOVERY_ENABLED=false
CONSUL_ENABLED=false
CONSUL_HOST=consul
CONSUL_PORT=8500
```

### 2.2 Application-specific `.env` (backend)

**File:** `backend/.env.local` (development) or loaded from docker-compose

```bash
# This can be generated from root .env or set separately
DATABASE_URL=postgresql://lokilinux:password@postgres:5432/lokilinux
METRICS_DATABASE_URL=postgresql://metrics_user:password@postgres:5432/lokilinux_metrics
NATS_URL=nats://nats:4222
REDIS_URL=redis://:password@redis:6379/0
JWT_SECRET_KEY=your_secret
ENVIRONMENT=production
```

### 2.3 Agent `.env` (on each server)

**File:** `/etc/lokilinux/agent.env`

```bash
# Agent Configuration (generated during enrollment)
PLATFORM_URL=https://lokilinux.example.com
PLATFORM_GRPC_HOST=grpc.lokilinux.example.com
PLATFORM_GRPC_PORT=50051

AGENT_ID=agent-uuid-generated-during-enrollment
AGENT_HOSTNAME=production-server-01
AGENT_CERT_PATH=/etc/lokilinux/certs/agent.crt
AGENT_KEY_PATH=/etc/lokilinux/certs/agent.key
AGENT_CA_PATH=/etc/lokilinux/certs/ca.crt

HEARTBEAT_INTERVAL=60
HEARTBEAT_TIMEOUT=30
CACHE_PATH=/var/lib/lokilinux

PLUGINS_ENABLED=true
PLUGINS_PATH=/opt/lokilinux/plugins

LOG_LEVEL=info
LOG_PATH=/var/log/lokilinux/agent.log
```

---

## III. DOCKER COMPOSE SETUP

### 3.1 `docker-compose.yml` (Production-Ready)

**File:** `docker-compose.yml`

```yaml
version: "3.9"

services:
  # ============================================================================
  # DATABASE LAYER
  # ============================================================================

  postgres:
    image: postgres:${POSTGRES_IMAGE_VERSION:-15-alpine}
    container_name: lokilinux-postgres
    restart: unless-stopped
    
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      PGDATA: /var/lib/postgresql/data/pgdata
    
    ports:
      - "5432:5432"
    
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init-scripts/postgres-init.sql:/docker-entrypoint-initdb.d/01-init.sql
      - ./init-scripts/postgres-timescale.sql:/docker-entrypoint-initdb.d/02-timescale.sql
    
    networks:
      - lokilinux-net
    
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5
    
    resources:
      limits:
        cpus: "2"
        memory: 4g
      reservations:
        cpus: "1"
        memory: 2g

  # ============================================================================
  # MESSAGE QUEUE
  # ============================================================================

  nats:
    image: nats:${NATS_IMAGE_VERSION:-2.10-alpine}
    container_name: lokilinux-nats
    restart: unless-stopped
    
    command:
      - "-c"
      - "/etc/nats/nats.conf"
    
    ports:
      - "4222:4222"    # Client port
      - "6222:6222"    # Cluster port
      - "8222:8222"    # Monitor port
    
    volumes:
      - ./config/nats.conf:/etc/nats/nats.conf:ro
      - nats_data:/data/jetstream
    
    networks:
      - lokilinux-net
    
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:8222/healthz"]
      interval: 10s
      timeout: 5s
      retries: 5
    
    resources:
      limits:
        cpus: "1"
        memory: 1g

  # ============================================================================
  # CACHE
  # ============================================================================

  redis:
    image: redis:${REDIS_IMAGE_VERSION:-7-alpine}
    container_name: lokilinux-redis
    restart: unless-stopped
    
    command:
      - "redis-server"
      - "--maxmemory"
      - "${REDIS_MAXMEMORY:-2gb}"
      - "--maxmemory-policy"
      - "${REDIS_EVICTION_POLICY:-allkeys-lru}"
      - "--requirepass"
      - "${REDIS_PASSWORD}"
      - "--appendonly"
      - "yes"
    
    ports:
      - "6379:6379"
    
    volumes:
      - redis_data:/data
    
    networks:
      - lokilinux-net
    
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    
    resources:
      limits:
        cpus: "1"
        memory: 2g

  # ============================================================================
  # API (CORE PLATFORM)
  # ============================================================================

  api:
    build:
      context: ./backend
      dockerfile: Dockerfile
      args:
        BUILDKIT_INLINE_CACHE: 1
    
    image: lokilinux/api:${LOKILINUX_API_IMAGE_VERSION:-latest}
    container_name: lokilinux-api
    restart: unless-stopped
    
    depends_on:
      postgres:
        condition: service_healthy
      nats:
        condition: service_healthy
      redis:
        condition: service_healthy
    
    environment:
      # Load from root .env (docker-compose will interpolate)
      ENVIRONMENT: ${ENVIRONMENT}
      PLATFORM_HOSTNAME: ${PLATFORM_HOSTNAME}
      API_HOST: ${API_HOST}
      API_PORT: ${API_PORT}
      API_GRPC_PORT: ${API_GRPC_PORT}
      API_WORKERS: ${API_WORKERS}
      
      DATABASE_URL: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      METRICS_DATABASE_URL: postgresql://${TIMESCALEDB_USER}:${TIMESCALEDB_PASSWORD}@postgres:5432/${TIMESCALEDB_DB}
      NATS_URL: nats://${NATS_HOST}:${NATS_PORT}
      REDIS_URL: redis://:${REDIS_PASSWORD}@${REDIS_HOST}:${REDIS_PORT}/${REDIS_DB}
      
      JWT_SECRET_KEY: ${JWT_SECRET_KEY}
      JWT_ALGORITHM: ${JWT_ALGORITHM}
      JWT_EXPIRATION_MINUTES: ${JWT_EXPIRATION_MINUTES}
      
      CA_CERT_PATH: /etc/lokilinux/certs/ca.crt
      CA_KEY_PATH: /etc/lokilinux/certs/ca.key
      CERT_VALIDITY_DAYS: ${CERT_VALIDITY_DAYS}
      
      PLUGINS_ENABLED: ${PLUGINS_ENABLED}
      PLUGINS_DIR: /opt/plugins
      PLUGINS_SANDBOX_MODE: ${PLUGINS_SANDBOX_MODE}
      
      LOG_LEVEL: ${LOG_LEVEL}
      LOG_FORMAT: ${LOG_FORMAT}
      DEBUG: ${DEBUG}
    
    ports:
      - "8000:8000"    # HTTP API
      - "50051:50051"  # gRPC
      - "9090:9090"    # Metrics (Prometheus)
    
    volumes:
      # Plugin sandbox (shared between API and external)
      - plugins_dir:/opt/plugins
      
      # Certificates (must exist, see initialization)
      - certs_dir:/etc/lokilinux/certs
      
      # Logs
      - ./logs/api:/var/log/lokilinux
      
      # Backups
      - ./backups:/var/backups/lokilinux
    
    networks:
      - lokilinux-net
    
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    
    resources:
      limits:
        cpus: "${API_CPU_LIMIT:-2000m}"
        memory: "${API_MEMORY_LIMIT:-2g}"

  # ============================================================================
  # FRONTEND (NUXT 4)
  # ============================================================================

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
      args:
        VITE_API_URL: https://${PLATFORM_HOSTNAME}
        VITE_GRPC_URL: ${PLATFORM_HOSTNAME}:50051
    
    image: lokilinux/frontend:${LOKILINUX_FRONTEND_IMAGE_VERSION:-latest}
    container_name: lokilinux-frontend
    restart: unless-stopped
    
    environment:
      NUXT_HOST: ${FRONTEND_HOST}
      NUXT_PORT: ${FRONTEND_PORT}
      NUXT_PUBLIC_API_URL: https://${PLATFORM_HOSTNAME}
      NUXT_PUBLIC_GRPC_URL: ${PLATFORM_HOSTNAME}:50051
    
    ports:
      - "3000:3000"
    
    networks:
      - lokilinux-net
    
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/"]
      interval: 30s
      timeout: 10s
      retries: 3
    
    resources:
      limits:
        cpus: "${FRONTEND_CPU_LIMIT:-500m}"
        memory: "${FRONTEND_MEMORY_LIMIT:-512m}"

  # ============================================================================
  # REVERSE PROXY (NGINX)
  # ============================================================================

  nginx:
    image: nginx:${NGINX_IMAGE_VERSION:-1.25-alpine}
    container_name: lokilinux-nginx
    restart: unless-stopped
    
    depends_on:
      - api
      - frontend
    
    environment:
      PLATFORM_HOSTNAME: ${PLATFORM_HOSTNAME}
    
    ports:
      - "80:80"
      - "443:443"
    
    volumes:
      - ./config/nginx.conf:/etc/nginx/nginx.conf:ro
      - certs_dir:/etc/nginx/certs:ro
      - ./logs/nginx:/var/log/nginx
    
    networks:
      - lokilinux-net
    
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost/health"]
      interval: 30s
      timeout: 10s
      retries: 3

networks:
  lokilinux-net:
    name: ${DOCKER_NETWORK_NAME:-lokilinux-net}
    driver: ${DOCKER_NETWORK_DRIVER:-bridge}

volumes:
  postgres_data:
    name: lokilinux-postgres-data
  nats_data:
    name: lokilinux-nats-data
  redis_data:
    name: lokilinux-redis-data
  plugins_dir:
    name: lokilinux-plugins
  certs_dir:
    name: lokilinux-certs
```

### 3.2 `docker-compose.dev.yml` (Development Override)

**File:** `docker-compose.dev.yml`

```yaml
version: "3.9"

# Override for development
services:
  api:
    build:
      context: ./backend
      dockerfile: Dockerfile.dev
    
    environment:
      DEBUG: "true"
      RELOAD_ON_CHANGE: "true"
      ENVIRONMENT: development
    
    volumes:
      - ./backend:/app
      - /app/.venv  # Exclude venv
    
    command: ["uvicorn", "lokilinux.main:app", "--reload", "--host", "0.0.0.0"]

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile.dev
    
    environment:
      DEBUG: "true"
    
    volumes:
      - ./frontend:/app
      - /app/node_modules
    
    command: ["npm", "run", "dev"]

  postgres:
    environment:
      POSTGRES_INITDB_ARGS: "-c log_statement=all"
    
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    command: ["redis-server", "--loglevel", "debug"]
```

---

## IV. INITIALIZATION & FIRST-TIME SETUP

### 4.1 Certificate Generation Script

**File:** `scripts/init-certificates.sh`

```bash
#!/bin/bash
set -e

CERTS_DIR="${1:-./.certs}"
PLATFORM_HOSTNAME="${2:-lokilinux.example.com}"
CERT_VALIDITY_DAYS="${3:-365}"

mkdir -p "$CERTS_DIR"

echo "[*] Generating CA certificate..."
openssl genrsa -out "$CERTS_DIR/ca.key" 4096

openssl req -new -x509 \
  -days "$CERT_VALIDITY_DAYS" \
  -key "$CERTS_DIR/ca.key" \
  -out "$CERTS_DIR/ca.crt" \
  -subj "/CN=LokiLinux-CA/O=LokiLinux/C=US"

echo "[*] Generating server certificate..."
openssl genrsa -out "$CERTS_DIR/server.key" 4096

openssl req -new \
  -key "$CERTS_DIR/server.key" \
  -out "$CERTS_DIR/server.csr" \
  -subj "/CN=$PLATFORM_HOSTNAME/O=LokiLinux/C=US"

openssl x509 -req \
  -days "$CERT_VALIDITY_DAYS" \
  -in "$CERTS_DIR/server.csr" \
  -CA "$CERTS_DIR/ca.crt" \
  -CAkey "$CERTS_DIR/ca.key" \
  -CAcreateserial \
  -out "$CERTS_DIR/server.crt"

chmod 600 "$CERTS_DIR"/*.key
chmod 644 "$CERTS_DIR"/*.crt

echo "[+] Certificates generated in $CERTS_DIR"
ls -la "$CERTS_DIR"
```

### 4.2 Docker Initialization Script

**File:** `scripts/docker-init.sh`

```bash
#!/bin/bash
set -e

echo "[*] LokiLinux Docker Initialization"

# 1. Load environment
if [ ! -f .env ]; then
    echo "[!] Creating .env from .env.example..."
    cp .env.example .env
    echo "[!] EDIT .env with your configuration!"
    exit 1
fi

source .env

# 2. Generate certificates
echo "[*] Checking certificates..."
if [ ! -d ".certs" ]; then
    echo "[!] Certificates not found, generating..."
    bash scripts/init-certificates.sh .certs "$PLATFORM_HOSTNAME" "$CERT_VALIDITY_DAYS"
fi

# 3. Create required directories
echo "[*] Creating required directories..."
mkdir -p logs/{api,nginx,frontend}
mkdir -p backups
mkdir -p plugins

# 4. Initialize volumes
echo "[*] Creating Docker volumes..."
docker volume create lokilinux-postgres-data || true
docker volume create lokilinux-nats-data || true
docker volume create lokilinux-redis-data || true
docker volume create lokilinux-plugins || true
docker volume create lokilinux-certs || true

# 5. Copy certificates to Docker volume
echo "[*] Copying certificates to Docker volume..."
docker run --rm \
  -v lokilinux-certs:/certs \
  -v $(pwd)/.certs:/source \
  alpine:latest \
  cp -r /source/* /certs/

# 6. Build images
echo "[*] Building Docker images..."
docker-compose build

# 7. Start services
echo "[*] Starting services..."
docker-compose up -d

# 8. Wait for postgres
echo "[*] Waiting for PostgreSQL to be ready..."
for i in {1..30}; do
    if docker-compose exec -T postgres pg_isready -U "$POSTGRES_USER" > /dev/null 2>&1; then
        echo "[+] PostgreSQL is ready"
        break
    fi
    echo "  Waiting... ($i/30)"
    sleep 2
done

# 9. Run database migrations
echo "[*] Running database migrations..."
docker-compose exec -T api alembic upgrade head

# 10. Create initial admin user
echo "[*] Creating initial admin user..."
docker-compose exec -T api python -m lokilinux.scripts.create_admin

# 11. Health check
echo "[*] Checking service health..."
sleep 5
docker-compose ps

echo "[+] LokiLinux initialized successfully!"
echo ""
echo "Access:"
echo "  - Web UI: https://localhost/ or https://$PLATFORM_HOSTNAME"
echo "  - API: https://localhost:8000/docs"
echo "  - gRPC: localhost:50051"
echo ""
echo "Next steps:"
echo "  1. Change default admin password"
echo "  2. Configure integrations (.env)"
echo "  3. Generate agent enrollment token"
echo "  4. Install agents on target servers"
```

### 4.3 Environment Template

**File:** `.env.example`

```bash
# Copy this to .env and customize

ENVIRONMENT=production
PLATFORM_NAME=LokiLinux Production
PLATFORM_HOSTNAME=lokilinux.example.com      # CHANGE THIS!

# Database
POSTGRES_PASSWORD=change_this_to_random_password
TIMESCALEDB_PASSWORD=change_this_to_random_password

# Redis
REDIS_PASSWORD=change_this_to_random_password

# Secrets (generate with: openssl rand -base64 32)
JWT_SECRET_KEY=change_this_to_random_secret_key
ENCRYPTION_KEY=change_this_to_random_encryption_key

# API
API_PORT=8000
API_GRPC_PORT=50051

# Frontend
FRONTEND_URL=https://lokilinux.example.com

# Certificates
CERT_VALIDITY_DAYS=365

# CVE Feeds
CVE_FEED_UPDATE_INTERVAL=86400

# Logging
LOG_LEVEL=info

# Plugins
PLUGINS_ENABLED=true
PLUGINS_SANDBOX_MODE=true
```

---

## V. SANDBOX PLUGIN ARCHITECTURE

### 5.1 Plugin Directory Structure

```
/opt/plugins/
├── zabbix-connector/
│   ├── manifest.yaml              # Plugin metadata
│   ├── requirements.txt            # Python dependencies
│   ├── Dockerfile                  # Optional: plugin container
│   ├── bin/
│   │   └── zabbix-plugin.py        # Entry point
│   ├── lokilinux_zabbix/
│   │   ├── __init__.py
│   │   ├── connector.py
│   │   ├── models.py
│   │   └── api.py
│   ├── config/
│   │   └── schema.json             # Configuration schema
│   └── tests/
│       └── test_connector.py
│
├── nessus-connector/
│   ├── manifest.yaml
│   ├── requirements.txt
│   ├── bin/
│   │   └── nessus-plugin.py
│   └── ...
│
├── jira-connector/
│   ├── manifest.yaml
│   ├── requirements.txt
│   ├── bin/
│   │   └── jira-plugin.py
│   └── ...
│
└── [other plugins...]
```

### 5.2 Plugin Manifest Specification

**File:** `/opt/plugins/{plugin_name}/manifest.yaml`

```yaml
# Zabbix Connector Example
name: "zabbix-connector"
display_name: "Zabbix Integration"
version: "1.0.0"
author: "LokiLinux Team"
description: "Synchronize servers and alerts from Zabbix"

# Plugin Metadata
category: "integration"
icon_url: "https://cdn.lokilinux.io/plugins/zabbix.png"
documentation_url: "https://docs.lokilinux.io/plugins/zabbix"
license: "Apache-2.0"

# Compatibility
min_platform_version: "1.0.0"
max_platform_version: "99.0.0"
supported_platforms:
  - linux/amd64
  - linux/arm64

# Entrypoint
entrypoint:
  type: "python"                     # python | go | nodejs | shell
  language_version: "3.11"
  module: "lokilinux_zabbix.connector"
  class: "ZabbixConnectorPlugin"
  port: 8001                         # Service port inside sandbox

# Permissions Required
permissions:
  - resource: "inventory"
    operations: ["read", "write"]
  - resource: "alerts"
    operations: ["write"]
  - resource: "external"
    operations: ["http"]             # Can make outbound HTTP requests

# Configuration Schema (JSON Schema)
config_schema:
  type: "object"
  title: "Zabbix Configuration"
  properties:
    zabbix_url:
      type: "string"
      title: "Zabbix Server URL"
      description: "e.g., https://zabbix.example.com"
      pattern: "^https?://"
      
    zabbix_api_token:
      type: "string"
      title: "API Token"
      description: "Zabbix API authentication token"
      format: "password"  # Will be encrypted in DB
      
    sync_interval_minutes:
      type: "integer"
      minimum: 5
      maximum: 1440
      default: 30
      title: "Sync Interval"
      
    enabled:
      type: "boolean"
      default: true
  
  required:
    - zabbix_url
    - zabbix_api_token

# Dependencies (for Python plugins)
dependencies:
  - name: "requests"
    version: ">=2.28.0"
  - name: "pydantic"
    version: ">=2.0.0"

# Resource Limits (in sandbox)
resources:
  memory_limit_mb: 256
  cpu_limit_percent: 50
  network_bandwidth_mbps: 10
  disk_space_mb: 500

# Health Check
health_check:
  type: "http"
  path: "/health"
  interval_seconds: 30
  timeout_seconds: 5

# Lifecycle Hooks
lifecycle:
  on_install: "scripts/install.sh"
  on_enable: "scripts/enable.sh"
  on_disable: "scripts/disable.sh"
  on_uninstall: "scripts/uninstall.sh"
  on_update: "scripts/update.sh"

# Hooks/Events
hooks:
  - event: "server_discovered"
    handler: "on_server_discovered"
  - event: "alert_triggered"
    handler: "on_alert_triggered"

# Update Strategy
update_strategy: "rolling"           # rolling | blue_green | canary
update_check_interval_hours: 24

# Marketplace Metadata
ratings:
  average: 4.8
  count: 156
downloads: 1234
verified: true
```

### 5.3 Plugin SDK (Python Base Class)

**File:** `backend/lokilinux/plugin_sdk.py`

```python
"""
LokiLinux Plugin SDK - Base classes for plugin development
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import json
import logging
from pathlib import Path

import aiohttp
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


@dataclass
class PluginContext:
    """Context provided to plugins"""
    plugin_name: str
    plugin_version: str
    platform_url: str
    platform_grpc_url: str
    api_key: str  # Service-to-service API key
    config: Dict[str, Any]
    plugins_dir: Path
    data_dir: Path  # Isolated data dir per plugin


class PluginConfig(BaseModel):
    """Base configuration for all plugins"""
    enabled: bool = True
    debug: bool = False


class PluginResponse(BaseModel):
    """Standard plugin response"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class BasePlugin(ABC):
    """
    Base class for all LokiLinux plugins
    
    Example:
        class MyPlugin(BasePlugin):
            async def on_install(self):
                self.logger.info("Plugin installing")
            
            async def on_enable(self):
                self.logger.info("Plugin enabled")
                # Start background tasks
            
            @http_endpoint(method="GET", path="/health")
            async def health(self, request):
                return {"status": "ok"}
    """
    
    def __init__(self, context: PluginContext):
        self.context = context
        self.name = context.plugin_name
        self.version = context.plugin_version
        self.logger = self._setup_logger()
        self.http_client: Optional[aiohttp.ClientSession] = None
    
    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger(f"plugin.{self.name}")
        handler = logging.FileHandler(
            self.context.data_dir / f"{self.name}.log"
        )
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger
    
    async def __aenter__(self):
        """Async context manager entry"""
        self.http_client = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.http_client:
            await self.http_client.close()
    
    # ==================== LIFECYCLE HOOKS ====================
    
    async def on_install(self) -> None:
        """Called when plugin is being installed"""
        self.logger.info(f"Installing {self.name}")
    
    async def on_enable(self) -> None:
        """Called when plugin is enabled"""
        self.logger.info(f"Enabling {self.name}")
    
    async def on_disable(self) -> None:
        """Called when plugin is disabled"""
        self.logger.info(f"Disabling {self.name}")
    
    async def on_uninstall(self) -> None:
        """Called when plugin is uninstalled"""
        self.logger.info(f"Uninstalling {self.name}")
    
    async def on_update(self, old_version: str, new_version: str) -> None:
        """Called when plugin is updated"""
        self.logger.info(f"Updating {self.name} from {old_version} to {new_version}")
    
    async def on_config_change(self, old_config: Dict, new_config: Dict) -> None:
        """Called when plugin configuration changes"""
        self.logger.info(f"Configuration changed for {self.name}")
    
    # ==================== HEALTH CHECK ====================
    
    async def health_check(self) -> Dict[str, Any]:
        """Return health status"""
        return {
            "status": "healthy",
            "plugin": self.name,
            "version": self.version
        }
    
    # ==================== API INTEGRATION ====================
    
    async def call_api(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Call LokiLinux API from plugin
        
        Example:
            result = await self.call_api(
                "GET",
                "/api/v1/servers",
                params={"limit": 100}
            )
        """
        if not self.http_client:
            raise RuntimeError("HTTP client not initialized")
        
        url = f"{self.context.platform_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.context.api_key}",
            "Content-Type": "application/json"
        }
        
        async with self.http_client.request(
            method,
            url,
            headers=headers,
            **kwargs
        ) as resp:
            data = await resp.json()
            if resp.status >= 400:
                raise Exception(f"API error: {data}")
            return data
    
    # ==================== DATA STORAGE ====================
    
    async def save_state(self, key: str, value: Any) -> None:
        """Persist plugin state (stored in isolated dir)"""
        state_file = self.context.data_dir / f"{key}.json"
        with open(state_file, "w") as f:
            json.dump(value, f)
    
    async def load_state(self, key: str) -> Optional[Any]:
        """Load plugin state"""
        state_file = self.context.data_dir / f"{key}.json"
        if not state_file.exists():
            return None
        with open(state_file, "r") as f:
            return json.load(f)
    
    # ==================== EVENT SUBSCRIPTION ====================
    
    def subscribe(self, event_type: str, handler: callable):
        """Subscribe to platform events"""
        # Implementation: register with event bus
        pass
    
    # ==================== HTTP ENDPOINTS ====================
    
    def register_endpoint(
        self,
        method: str,
        path: str,
        handler: callable
    ) -> None:
        """Register HTTP endpoint in sandbox"""
        # Implementation: register with internal HTTP server
        pass


class PluginRegistry:
    """
    Manages plugin registration and lifecycle
    Used by the platform to discover and load plugins
    """
    
    def __init__(self, plugins_dir: Path, platform_url: str):
        self.plugins_dir = plugins_dir
        self.platform_url = platform_url
        self.plugins: Dict[str, BasePlugin] = {}
    
    async def discover_plugins(self) -> List[Dict[str, Any]]:
        """Find all plugins in plugins_dir"""
        plugins = []
        for plugin_dir in self.plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue
            
            manifest_file = plugin_dir / "manifest.yaml"
            if not manifest_file.exists():
                continue
            
            # Load manifest
            import yaml
            with open(manifest_file) as f:
                manifest = yaml.safe_load(f)
            
            plugins.append({
                "name": manifest["name"],
                "version": manifest["version"],
                "display_name": manifest.get("display_name"),
                "description": manifest.get("description"),
                "path": str(plugin_dir),
                "manifest": manifest
            })
        
        return plugins
    
    async def load_plugin(self, plugin_name: str) -> BasePlugin:
        """Dynamically load and instantiate plugin"""
        # Find plugin dir
        plugin_dir = self.plugins_dir / plugin_name
        manifest_file = plugin_dir / "manifest.yaml"
        
        # Load manifest
        import yaml
        with open(manifest_file) as f:
            manifest = yaml.safe_load(f)
        
        # Create context
        context = PluginContext(
            plugin_name=plugin_name,
            plugin_version=manifest["version"],
            platform_url=self.platform_url,
            platform_grpc_url="",
            api_key="",
            config={},
            plugins_dir=self.plugins_dir,
            data_dir=plugin_dir / ".data"
        )
        
        context.data_dir.mkdir(exist_ok=True)
        
        # Import plugin class
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            plugin_name,
            plugin_dir / "bin" / f"{plugin_name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Instantiate
        plugin_class = getattr(module, "Plugin")
        plugin = plugin_class(context)
        
        self.plugins[plugin_name] = plugin
        return plugin
```

### 5.4 Zabbix Plugin Example

**File:** `/opt/plugins/zabbix-connector/bin/zabbix-plugin.py`

```python
"""
Zabbix Connector Plugin for LokiLinux
Synchronizes servers and alerts from Zabbix
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any

from lokilinux.plugin_sdk import BasePlugin, PluginContext, http_endpoint

import aiohttp


class ZabbixConnectorPlugin(BasePlugin):
    """Main plugin class"""
    
    def __init__(self, context: PluginContext):
        super().__init__(context)
        self.zabbix_url = context.config.get("zabbix_url")
        self.zabbix_token = context.config.get("zabbix_api_token")
        self.sync_interval = context.config.get("sync_interval_minutes", 30) * 60
        self._sync_task = None
    
    async def on_enable(self) -> None:
        """Start background sync task"""
        await super().on_enable()
        self.logger.info("Starting Zabbix sync task")
        self._sync_task = asyncio.create_task(self._sync_loop())
    
    async def on_disable(self) -> None:
        """Stop background sync task"""
        await super().on_disable()
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
    
    async def _sync_loop(self) -> None:
        """Continuous sync from Zabbix"""
        while True:
            try:
                await self._sync_from_zabbix()
                await asyncio.sleep(self.sync_interval)
            except Exception as e:
                self.logger.error(f"Sync error: {e}", exc_info=True)
                await asyncio.sleep(300)  # Retry in 5 min
    
    async def _sync_from_zabbix(self) -> None:
        """Fetch hosts from Zabbix and sync with LokiLinux"""
        self.logger.info("Syncing from Zabbix")
        
        # Fetch hosts from Zabbix API
        hosts = await self._fetch_zabbix_hosts()
        self.logger.info(f"Found {len(hosts)} hosts in Zabbix")
        
        # Sync each host
        for host in hosts:
            try:
                await self._sync_host(host)
            except Exception as e:
                self.logger.error(f"Failed to sync host {host['name']}: {e}")
        
        # Save state
        await self.save_state("last_sync", {
            "timestamp": datetime.now().isoformat(),
            "host_count": len(hosts)
        })
    
    async def _fetch_zabbix_hosts(self) -> List[Dict[str, Any]]:
        """Fetch hosts from Zabbix API"""
        payload = {
            "jsonrpc": "2.0",
            "method": "host.get",
            "params": {
                "output": ["hostid", "name", "host", "status"],
                "selectInterfaces": ["interfaceid", "ip", "port", "type"],
                "selectGroups": ["groupid", "name"]
            },
            "auth": self.zabbix_token,
            "id": 1
        }
        
        async with self.http_client.post(
            f"{self.zabbix_url}/api_jsonrpc.php",
            json=payload
        ) as resp:
            result = await resp.json()
            
            if "error" in result:
                raise Exception(f"Zabbix API error: {result['error']}")
            
            return result.get("result", [])
    
    async def _sync_host(self, zabbix_host: Dict[str, Any]) -> None:
        """Sync single Zabbix host to LokiLinux"""
        ip = ""
        if zabbix_host.get("interfaces"):
            ip = zabbix_host["interfaces"][0].get("ip", "")
        
        # Call LokiLinux API to add/update server
        await self.call_api(
            "POST",
            "/api/v1/servers/sync",
            json={
                "name": zabbix_host["name"],
                "hostname": zabbix_host["host"],
                "ip": ip,
                "source": "zabbix",
                "metadata": {
                    "zabbix_hostid": zabbix_host["hostid"],
                    "zabbix_groups": [g["name"] for g in zabbix_host.get("groups", [])]
                }
            }
        )
    
    # ==================== HTTP ENDPOINTS ====================
    
    @http_endpoint(method="GET", path="/health")
    async def health_check(self) -> Dict[str, Any]:
        """Health check endpoint"""
        last_sync = await self.load_state("last_sync")
        return {
            "status": "healthy",
            "plugin": "zabbix-connector",
            "last_sync": last_sync,
            "connected_to_zabbix": await self._test_zabbix_connection()
        }
    
    @http_endpoint(method="POST", path="/sync")
    async def manual_sync(self) -> Dict[str, Any]:
        """Trigger manual sync"""
        await self._sync_from_zabbix()
        return {
            "status": "success",
            "message": "Sync completed"
        }
    
    async def _test_zabbix_connection(self) -> bool:
        """Test connection to Zabbix"""
        try:
            payload = {
                "jsonrpc": "2.0",
                "method": "host.get",
                "params": {"output": "count"},
                "auth": self.zabbix_token,
                "id": 1
            }
            async with self.http_client.post(
                f"{self.zabbix_url}/api_jsonrpc.php",
                json=payload,
                timeout=5
            ) as resp:
                return resp.status == 200
        except:
            return False


# Entry point for plugin loader
Plugin = ZabbixConnectorPlugin
```

---

## VI. PLUGIN INSTALLATION & MANAGEMENT

### 6.1 Plugin Installation Flow

**API Endpoint:** `POST /api/v1/plugins/install`

```python
# backend/lokilinux/api/v1/routers/plugins.py

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
import subprocess
import tempfile
from pathlib import Path
import json

router = APIRouter(prefix="/plugins", tags=["plugins"])


@router.post("/install")
async def install_plugin(
    plugin_name: str,
    plugin_version: str,
    config: dict = None,
    current_user = Depends(get_current_user)
):
    """
    Install plugin into sandbox
    
    Flow:
    1. Download plugin binary from marketplace (or upload)
    2. Verify signature (GPG/cosign)
    3. Extract to /opt/plugins/{name}/
    4. Validate manifest
    5. Check permissions
    6. Run on_install hook
    7. Register in DB
    """
    
    # Check permission
    await check_permission(current_user, "plugins:install")
    
    plugins_dir = Path("/opt/plugins")
    target_dir = plugins_dir / plugin_name
    
    try:
        # Step 1: Download from marketplace
        plugin_data = await download_plugin_from_marketplace(
            plugin_name,
            plugin_version
        )
        
        # Step 2: Verify signature
        if not await verify_plugin_signature(plugin_data):
            raise HTTPException(
                status_code=400,
                detail="Plugin signature verification failed"
            )
        
        # Step 3: Extract
        with tempfile.TemporaryDirectory() as tmpdir:
            extract_plugin_archive(plugin_data, tmpdir)
            
            # Step 4: Validate manifest
            manifest_file = Path(tmpdir) / "manifest.yaml"
            if not manifest_file.exists():
                raise HTTPException(
                    status_code=400,
                    detail="Plugin missing manifest.yaml"
                )
            
            manifest = load_manifest(manifest_file)
            
            # Step 5: Check permissions
            required_permissions = manifest.get("permissions", [])
            await validate_plugin_permissions(required_permissions)
            
            # Step 6: Move to plugins dir
            target_dir.mkdir(parents=True, exist_ok=True)
            copy_files(tmpdir, target_dir)
            
            # Step 7: Run install hook
            if "lifecycle" in manifest and "on_install" in manifest["lifecycle"]:
                install_script = target_dir / manifest["lifecycle"]["on_install"]
                if install_script.exists():
                    result = subprocess.run(
                        ["bash", str(install_script)],
                        cwd=target_dir,
                        capture_output=True,
                        timeout=300
                    )
                    if result.returncode != 0:
                        raise HTTPException(
                            status_code=500,
                            detail=f"Plugin install failed: {result.stderr.decode()}"
                        )
            
            # Step 8: Register in DB
            await db.plugins.create(
                name=plugin_name,
                version=plugin_version,
                manifest=json.dumps(manifest),
                config=config or {},
                is_installed=True,
                status="installed"
            )
            
            # Step 9: Audit
            await audit_log(
                user=current_user,
                action="plugin_installed",
                resource="plugin",
                resource_id=plugin_name,
                changes={"version": plugin_version}
            )
        
        return {
            "status": "success",
            "plugin_name": plugin_name,
            "plugin_version": plugin_version,
            "message": f"Plugin {plugin_name} installed successfully"
        }
    
    except Exception as e:
        logger.error(f"Plugin installation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{plugin_name}/enable")
async def enable_plugin(
    plugin_name: str,
    current_user = Depends(get_current_user)
):
    """Enable installed plugin"""
    
    plugin_dir = Path(f"/opt/plugins/{plugin_name}")
    if not plugin_dir.exists():
        raise HTTPException(status_code=404, detail="Plugin not found")
    
    # Run on_enable hook
    manifest = load_manifest(plugin_dir / "manifest.yaml")
    
    if "lifecycle" in manifest and "on_enable" in manifest["lifecycle"]:
        enable_script = plugin_dir / manifest["lifecycle"]["on_enable"]
        if enable_script.exists():
            result = subprocess.run(
                ["bash", str(enable_script)],
                cwd=plugin_dir,
                capture_output=True,
                timeout=300
            )
            if result.returncode != 0:
                raise HTTPException(
                    status_code=500,
                    detail=f"Plugin enable failed: {result.stderr.decode()}"
                )
    
    # Update DB
    await db.plugins.update(
        plugin_name,
        is_enabled=True,
        enabled_at=datetime.now()
    )
    
    await audit_log(
        user=current_user,
        action="plugin_enabled",
        resource="plugin",
        resource_id=plugin_name
    )
    
    return {"status": "success", "message": f"Plugin {plugin_name} enabled"}


@router.post("/{plugin_name}/disable")
async def disable_plugin(
    plugin_name: str,
    current_user = Depends(get_current_user)
):
    """Disable plugin (stop running, but keep installed)"""
    
    plugin_dir = Path(f"/opt/plugins/{plugin_name}")
    if not plugin_dir.exists():
        raise HTTPException(status_code=404, detail="Plugin not found")
    
    # Run on_disable hook
    manifest = load_manifest(plugin_dir / "manifest.yaml")
    
    if "lifecycle" in manifest and "on_disable" in manifest["lifecycle"]:
        disable_script = plugin_dir / manifest["lifecycle"]["on_disable"]
        if disable_script.exists():
            subprocess.run(
                ["bash", str(disable_script)],
                cwd=plugin_dir,
                capture_output=True,
                timeout=300
            )
    
    # Update DB
    await db.plugins.update(
        plugin_name,
        is_enabled=False,
        disabled_at=datetime.now()
    )
    
    await audit_log(
        user=current_user,
        action="plugin_disabled",
        resource="plugin",
        resource_id=plugin_name
    )
    
    return {"status": "success", "message": f"Plugin {plugin_name} disabled"}


@router.delete("/{plugin_name}")
async def uninstall_plugin(
    plugin_name: str,
    current_user = Depends(get_current_user)
):
    """Uninstall plugin completely"""
    
    plugin_dir = Path(f"/opt/plugins/{plugin_name}")
    if not plugin_dir.exists():
        raise HTTPException(status_code=404, detail="Plugin not found")
    
    # Run on_uninstall hook
    manifest = load_manifest(plugin_dir / "manifest.yaml")
    
    if "lifecycle" in manifest and "on_uninstall" in manifest["lifecycle"]:
        uninstall_script = plugin_dir / manifest["lifecycle"]["on_uninstall"]
        if uninstall_script.exists():
            subprocess.run(
                ["bash", str(uninstall_script)],
                cwd=plugin_dir,
                capture_output=True,
                timeout=300
            )
    
    # Remove directory
    import shutil
    shutil.rmtree(plugin_dir)
    
    # Update DB
    await db.plugins.delete(plugin_name)
    
    await audit_log(
        user=current_user,
        action="plugin_uninstalled",
        resource="plugin",
        resource_id=plugin_name
    )
    
    return {"status": "success", "message": f"Plugin {plugin_name} uninstalled"}


@router.get("/marketplace")
async def list_marketplace_plugins():
    """List available plugins from marketplace"""
    
    # Call external marketplace API
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{PLUGIN_MARKETPLACE_URL}/plugins"
        ) as resp:
            plugins = await resp.json()
            return plugins
```

### 6.2 Plugin Sandbox Isolation (Docker)

Plugins can be optionally run in isolated Docker containers:

**File:** `scripts/plugin-sandbox.sh`

```bash
#!/bin/bash

PLUGIN_NAME=$1
PLUGIN_DIR="/opt/plugins/$PLUGIN_NAME"
MANIFEST="$PLUGIN_DIR/manifest.yaml"

# Parse manifest for resource limits
MEMORY=$(yq '.resources.memory_limit_mb' $MANIFEST)
CPU=$(yq '.resources.cpu_limit_percent' $MANIFEST)
NETWORK_BW=$(yq '.resources.network_bandwidth_mbps' $MANIFEST)

# Create sandbox container
docker run -d \
  --name "lokilinux-plugin-$PLUGIN_NAME" \
  --memory "${MEMORY}m" \
  --cpus "$((CPU / 100))" \
  --network lokilinux-net \
  --mount type=bind,source="$PLUGIN_DIR",target=/app,readonly \
  --mount type=volume,source="lokilinux-plugins-data",target=/data \
  -e PLUGIN_NAME="$PLUGIN_NAME" \
  -e PLUGIN_DIR="/app" \
  -e API_URL="http://api:8000" \
  lokilinux/plugin-sandbox:latest \
  python -m lokilinux_plugin_runner
```

---

## VII. AGENT INSTALLATION & ENROLLMENT

### 7.1 Agent Installation Script

**File:** `scripts/install-agent.sh`

```bash
#!/bin/bash
set -e

# LokiLinux Agent Installation Script
# Usage: curl -s https://lokilinux.example.com/install | bash -s -- --token=ENROLLMENT_TOKEN

PLATFORM_URL="${PLATFORM_URL:-https://lokilinux.example.com}"
ENROLLMENT_TOKEN=""
AGENT_NAME=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --token)
            ENROLLMENT_TOKEN="$2"
            shift 2
            ;;
        --name)
            AGENT_NAME="$2"
            shift 2
            ;;
        --url)
            PLATFORM_URL="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

if [ -z "$ENROLLMENT_TOKEN" ]; then
    echo "Error: --token required"
    exit 1
fi

echo "[*] LokiLinux Agent Installation"
echo "  Platform: $PLATFORM_URL"
echo "  Token: ${ENROLLMENT_TOKEN:0:10}..."

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    OS_VERSION=$VERSION_ID
else
    echo "Error: Cannot detect OS"
    exit 1
fi

echo "[*] Detected OS: $OS $OS_VERSION"

# Download agent binary
echo "[*] Downloading agent binary..."
AGENT_BINARY="/tmp/lokilinux-agent"

curl -s -L \
  "$PLATFORM_URL/api/v1/agent/download" \
  -H "Authorization: Bearer $ENROLLMENT_TOKEN" \
  -H "X-OS: $OS" \
  -H "X-ARCH: $(uname -m)" \
  -o "$AGENT_BINARY"

if [ ! -f "$AGENT_BINARY" ]; then
    echo "Error: Failed to download agent binary"
    exit 1
fi

chmod +x "$AGENT_BINARY"
echo "[+] Agent binary downloaded"

# Register agent with platform
echo "[*] Registering agent..."

REGISTRATION_RESPONSE=$(curl -s -X POST \
  "$PLATFORM_URL/api/v1/agent/register" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ENROLLMENT_TOKEN" \
  -d "{
    \"hostname\": \"$(hostname)\",
    \"os_distro\": \"$OS\",
    \"os_version\": \"$OS_VERSION\",
    \"arch\": \"$(uname -m)\",
    \"kernel_version\": \"$(uname -r)\"
  }")

AGENT_ID=$(echo $REGISTRATION_RESPONSE | jq -r '.agent_id')
AGENT_CERT=$(echo $REGISTRATION_RESPONSE | jq -r '.agent_cert')
CA_CERT=$(echo $REGISTRATION_RESPONSE | jq -r '.ca_cert')

if [ -z "$AGENT_ID" ] || [ "$AGENT_ID" = "null" ]; then
    echo "Error: Agent registration failed"
    echo "$REGISTRATION_RESPONSE" | jq .
    exit 1
fi

echo "[+] Agent registered with ID: $AGENT_ID"

# Create agent directories
echo "[*] Creating agent directories..."
mkdir -p /etc/lokilinux/certs
mkdir -p /var/lib/lokilinux
mkdir -p /var/log/lokilinux
mkdir -p /opt/lokilinux/plugins

# Install certificates
echo "[*] Installing certificates..."
echo "$AGENT_CERT" > /etc/lokilinux/certs/agent.crt
echo "$CA_CERT" > /etc/lokilinux/certs/ca.crt
chmod 600 /etc/lokilinux/certs/*.crt

# Create agent configuration
echo "[*] Creating agent configuration..."
cat > /etc/lokilinux/agent.env <<EOF
PLATFORM_URL=$PLATFORM_URL
PLATFORM_GRPC_HOST=$(echo $PLATFORM_URL | sed 's|https://||')
PLATFORM_GRPC_PORT=50051

AGENT_ID=$AGENT_ID
AGENT_HOSTNAME=$(hostname)
AGENT_CERT_PATH=/etc/lokilinux/certs/agent.crt
AGENT_KEY_PATH=/etc/lokilinux/certs/agent.key
AGENT_CA_PATH=/etc/lokilinux/certs/ca.crt

HEARTBEAT_INTERVAL=60
HEARTBEAT_TIMEOUT=30
CACHE_PATH=/var/lib/lokilinux

PLUGINS_ENABLED=true
PLUGINS_PATH=/opt/lokilinux/plugins

LOG_LEVEL=info
LOG_PATH=/var/log/lokilinux/agent.log
EOF

# Install agent binary
echo "[*] Installing agent binary..."
cp "$AGENT_BINARY" /usr/local/bin/lokilinux-agent
chmod +x /usr/local/bin/lokilinux-agent

# Create systemd service
echo "[*] Creating systemd service..."
cat > /etc/systemd/system/lokilinux-agent.service <<EOF
[Unit]
Description=LokiLinux Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
EnvironmentFile=/etc/lokilinux/agent.env
ExecStart=/usr/local/bin/lokilinux-agent
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
echo "[*] Enabling and starting service..."
systemctl daemon-reload
systemctl enable lokilinux-agent
systemctl start lokilinux-agent

# Verify
sleep 2
if systemctl is-active --quiet lokilinux-agent; then
    echo "[+] Agent is running!"
else
    echo "[-] Agent failed to start. Check logs:"
    journalctl -u lokilinux-agent -n 20
    exit 1
fi

echo ""
echo "[+] LokiLinux Agent Installation Complete!"
echo ""
echo "Agent ID: $AGENT_ID"
echo "Status: $(systemctl is-active lokilinux-agent)"
echo "Log: /var/log/lokilinux/agent.log"
echo ""
echo "Check status:"
echo "  systemctl status lokilinux-agent"
echo "  tail -f /var/log/lokilinux/agent.log"
```

### 7.2 Agent Binary Download Endpoint

**File:** `backend/lokilinux/api/v1/routers/agent.py`

```python
# API endpoint to download agent binary

@router.get("/download")
async def download_agent(
    request: Request,
    token: str = Query(...)
):
    """
    Download agent binary for specific OS/architecture
    
    Query params:
      - token: enrollment token
      - os: linux (hardcoded for now)
      - arch: amd64, arm64
    """
    
    # Verify token
    enrollment = await db.agent_enrollments.get_by_token(token)
    if not enrollment or enrollment.expired:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    os_type = request.headers.get("X-OS", "linux")
    arch = request.headers.get("X-ARCH", "amd64")
    
    # Map architecture
    if arch == "aarch64":
        arch = "arm64"
    
    # Build binary filename
    binary_name = f"lokilinux-agent-{os_type}-{arch}"
    binary_path = Path(f"/app/releases/{binary_name}")
    
    if not binary_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Binary not available for {os_type}/{arch}"
        )
    
    # Mark token as used
    await db.agent_enrollments.mark_used(token)
    
    return FileResponse(
        binary_path,
        media_type="application/octet-stream",
        filename=binary_name
    )
```

---

## VIII. QUICK START GUIDE

### 8.1 First-Time Deployment

```bash
# 1. Clone repository
git clone https://github.com/lokilinux/lokilinux.git
cd lokilinux

# 2. Copy environment template
cp .env.example .env

# 3. Edit configuration (IMPORTANT!)
nano .env
# Change:
#  - PLATFORM_HOSTNAME
#  - All *_PASSWORD variables
#  - JWT_SECRET_KEY
#  - ENCRYPTION_KEY

# 4. Initialize (generates certificates, creates volumes, starts services)
bash scripts/docker-init.sh

# 5. Check status
docker-compose ps
docker-compose logs -f api

# 6. Access UI
# Web UI: https://localhost/ or https://YOUR_PLATFORM_HOSTNAME
# API Docs: https://localhost:8000/docs
# gRPC: localhost:50051

# 7. Change admin password
docker-compose exec api python -m lokilinux.scripts.change_admin_password

# 8. Generate agent enrollment token
docker-compose exec api python -c "
from lokilinux.services.agent_service import AgentService
import asyncio
async def main():
    service = AgentService()
    token = await service.create_enrollment_token(ttl_hours=24)
    print(f'Enrollment token: {token}')
asyncio.run(main())
"

# 9. Install agent on target server
curl -s https://YOUR_PLATFORM_HOSTNAME/install | bash -s -- --token=TOKEN
```

### 8.2 Post-Installation Tasks

```bash
# 1. Verify all services
docker-compose ps

# 2. Check logs
docker-compose logs -f api
docker-compose logs -f frontend
docker-compose logs -f postgres

# 3. Install first plugin (optional)
# Via UI: Admin → Plugins → Marketplace → Install Zabbix Connector
# Or via API:
curl -X POST https://localhost:8000/api/v1/plugins/install \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "plugin_name": "zabbix-connector",
    "plugin_version": "1.0.0",
    "config": {
      "zabbix_url": "https://zabbix.example.com",
      "zabbix_api_token": "YOUR_TOKEN"
    }
  }'

# 4. Monitor agent connections
docker-compose exec api python -m lokilinux.scripts.monitor_agents
```

---

## IX. ARCHITECTURE SUMMARY

```
LokiLinux Core (Docker)
├── API (FastAPI) ← Core services only
├── Frontend (Nuxt 4)
├── PostgreSQL
├── NATS
└── Redis

Plugin Sandbox (/opt/plugins/)
├── zabbix-connector/      [optional]
├── nessus-connector/      [optional]
├── jira-connector/        [optional]
└── [user-installed plugins...]

Agents (on servers)
└── lokilinux-agent (Go binary)
    └── Core modules only + loaded plugins
```

**First installation = Core only (API + Agent + DB)**
**Plugins = Optional, installed post-deployment**

---

Structura este completa, practică și production-ready. Vrei să aprofundez vreo secțiune?
