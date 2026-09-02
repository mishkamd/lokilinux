# 06 — Infrastructură și deployment

> Documentație generată din cod la commit `77c4220`, august 2026. Sursă: `docker-compose.yml`, `docker-compose.dev.yml`, `Makefile`, `scripts/`.

## Rol

Tot ce rulează platforma stă în **9 servicii Docker** pe **cinci rețele segmentate** (`data-net`, `app-net`, `web-net` — interne; `gateway-net` pentru publicarea porturilor pe host; `egress-net` — doar api, pentru acces outbound), cu 5 volume named pentru persistență. Un singur `make init` duce de la zero la stack funcțional.

Doar frontend-ul (3000), api-ul (8000 REST + 9090 metrics) și grpc (50051) au porturi publicate pe host; postgres, pgBouncer (6432), redis (6379) și nats (4222/8222) sunt **internal-only**. Imaginile sunt tag-uite `${LOKILINUX_VERSION}` (0.3.0) — niciodată `latest`.

## Harta serviciilor

```
                        ┌────────────────────────────┐
   :3000 ──────────────►│  lokilinux-frontend (Nuxt) │◄── utilizator browser
                        │  + Better Auth             │
                        └─────────────┬──────────────┘
                                      │ proxy /api/v1 (same-origin)
                        ┌─────────────▼──────────────┐
   :8000/:9090 ────────►│  lokilinux-api (FastAPI)   │
                        └───────┬───────────┬────────┘
                                │           │ passthrough NATS
                 ┌──────────────▼──┐   ┌────▼──────────────┐
   :50051 mTLS ─►│ lokilinux-grpc  │   │ lokilinux-        │
   agenți Go     │ (grpcio)        │   │ compliance (Go)   │
                 └───────┬─────────┘   └────┬──────────────┘
                         │                  │
              ┌──────────▼──────────────────▼──────┐
              │ pgbouncer :6432 → postgres :5432    │  TimescaleDB PG17
              └──────────┬──────────────────────────┘
                         │
      ┌──────────────────┼──────────────────┐
      ▼                  ▼                  ▼
  nats :4222/:8222   redis :6379     lokilinux-migrate (alembic, un-shot)
```

## Tabel servicii

| Serviciu | Imagine | Porturi | Healthcheck | Limite resurse |
|---|---|---|---|---|
| `postgres` | timescale/timescaledb:2.28.1-pg17 | 5432 intern | pg_isready | 2 CPU / 4G |
| `pgbouncer` | edoburu/pgbouncer:v1.25.2-p0 | 6432→5432 | pg_isready | 0.5 CPU / 256M |
| `nats` | nats:2.10.29-alpine (--js) | 4222, 8222 monitor | wget healthz | 1 CPU / 1G |
| `redis` | redis:7.4.9-alpine | 6379 | redis-cli ping | 1 CPU / 2G |
| `lokilinux-migrate` | build backend | — | rulează și iese (restart: no) | — |
| `lokilinux-api` | lokilinux/api | 8000 REST, 9090 metrics | probe python stdlib `/health` | 2 CPU / 2G |
| `lokilinux-grpc` | lokilinux/api (alt command) | 50051 mTLS | socket probe python | 2 CPU / 2G |
| `lokilinux-compliance` | lokilinux/compliance | 8080 healthz, 9091 metrics | self-probe `-healthcheck` | 2 CPU / 2G |
| `lokilinux-frontend` | lokilinux/frontend | 3000 | wget /health | 0.5 CPU / 512M |

Lanț de dependențe: `postgres` → healthy → `pgbouncer` → healthy → `lokilinux-migrate` completed → {`api`, `grpc`, `compliance`} → `frontend`. `nats` și `redis` sunt independente de DB.

## Volum persistente

| Volum | Mount | Cine folosește |
|---|---|---|
| `lokilinux-postgres-data` | `/var/lib/postgresql/data/pgdata` | postgres |
| `lokilinux-nats-data` | `/data/jetstream` | nats (JetStream) |
| `lokilinux-redis-data` | `/data` | redis (AOF) |
| `lokilinux-plugins` | `/opt/lokilinux/plugins` | api + grpc (plugin-uri agent-side) |
| `lokilinux-certs` | `/etc/lokilinux/certs` (ro) | api, grpc, compliance |

## Certificate mTLS

- `make certs` → script `scripts/init-certificates.sh`: generează CA + server cert pentru hostname-ul din `PLATFORM_HOSTNAME`.
- gRPC :50051 cere mTLS: agentul prezintă cert client semnat de CA; serverul verifică.
- Certificatul CA e montat read-only în api/grpc/compliance.

## Redis & Postgres

- Redis: `--requirepass`, maxmemory 2gb default, policy **allkeys-lru**, AOF on — cache pierdabil prin design.
- TimescaleDB: chunk interval 1 zi (init SQL); pgBouncer **transaction mode**, MAX_CLIENT_CONN 200, pool 20, auth scram-sha-256. Consecință: conexiunile async SQLAlchemy nu pot ține sesiuni stateful între tranzacții.
- Compliance service folosește DSN keyword=value (nu URI) tocmai ca parolele generate cu caractere speciale să nu necesite percent-encoding — comentariu în compose documentează un incident real de hang la forma URI.

## Dev vs Production

`docker-compose.dev.yml` (folosit de `make dev`):
- expune local porturile infra: 5432, 6432, 4222 (+8222), 6379;
- Dockerfile-uri dev cu `uvicorn --reload` și `npm run dev`;
- bind-mount surse (fără `.venv`/`node_modules`);
- limite relaxate (4G/serviciu), query logging verbose Postgres.

## Securitate runtime

- Serviciile de aplicație rulează non-root (imaginea backend are user dedicat `appuser`, uid 10001; imaginea compliance distroless rulează `USER nonroot:nonroot`) cu rootfs **read-only** + tmpfs `/tmp`, `cap_drop: ALL`, `no-new-privileges` și limite pids/memory/cpu. Infrastructura e hardenită cu `no-new-privileges` + limite.
- `.env` nu ajunge niciodată în imagini (`backend/.dockerignore` îl blochează).
- `scripts/docker-init.sh` dă chown 10001:10001 pe cheile de certificate, ca serviciile non-root să le poată citi; wait-for-API folosește un one-liner Python `urllib` (imaginea runtime nu are curl).

## Scanare imagini & supply chain

```bash
make scan-image                       # Trivy peste toate imaginile lokilinux/* — pică pe HIGH/CRITICAL
make sbom IMAGE=lokilinux/api:0.3.0   # SBOM CycloneDX în sbom/
```

Excepțiile acceptate explicit sunt în `.trivyignore`. Pipeline-ul CI (`.github/workflows/security-pipeline.yml`) aplică același gate: build → teste → Trivy → SBOM → push GHCR → semnare cosign.

## Makefile — comenzi esențiale

```bash
make init            # certs → build → up → migrate → admin user (parola printată)
make certs           # CA + certificate mTLS
make build && make up && make down
make dev             # hot-reload dev override
make logs / make ps

make agent-build            # binar static linux/amd64
make agent-build-arm64      # linux/arm64
make agent-package          # .tar.gz + .deb + .rpm ambele arhitecturi
make agent-test             # go test -race
make proto                  # regenerează Go + Python din proto/*.proto
make scan-image             # gate Trivy (HIGH/CRITICAL = fail)
make sbom IMAGE=...         # SBOM CycloneDX
```

## Scripturi utile (`scripts/`)

`docker-init.sh`, `init-certificates.sh`, `install-agent.sh` (curl-bash pe hosturi gestionate), `loki-cli.sh`.

## Variabile de mediu esențiale (`.env`)

| Variabilă | Rol |
|---|---|
| `POSTGRES_USER/PASSWORD/DB` | DB principal |
| `REDIS_PASSWORD` | Cache |
| `BETTER_AUTH_SECRET` | Semnare sesiuni (comun frontend ↔ backend) |
| `ADMIN_EMAIL/PASSWORD` | Utilizator admin inițial |
| `PLATFORM_HOSTNAME` | Hostname pentru certificate |
| `PUBLIC_URL` | Origine publică unică (URL-uri install agent + CORS) |
| `AGENT_VERSION` | Binar agent servit la download (0.35.3) |
| `DATABASE_URL/NATS_URL/REDIS_URL` | Conexiuni interne |
| `ENVIRONMENT`, `LOG_LEVEL` | development/production, info/debug |

## Decizii de design

1. **Migrări ca serviciu un-shot** — orice deploy rulează `alembic upgrade head` înainte de api; ordonanța e garantată de `condition: service_completed_successfully`.
2. **Un singur entry-point public** — totul se derivează din `PUBLIC_URL` (install agent, CORS, branding).
3. **Distroless pentru Go** — suprafață de atac minimă; healthcheck prin self-probe.
4. **JetStream persistent pe volum** — evenimentele supraviețuiesc restart-urilor; reconcilierea la startup rămâne plasă de siguranță.
