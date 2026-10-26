# Security Audit — Docker / Runtime (LokiLinux)

Scop: audit securitate Dockerfile-uri, compose, entrypoint, runtime. Fază: read-only.

## Constatări confirmate (bun)

- App tier (api, grpc, frontend, compliance, ca-signer, migrate): `read_only: true`, `tmpfs /tmp`,
  `cap_drop: ALL`, `no-new-privileges: true`, USER non-root (appuser 10001 / nuxt 1001 / distroless 65532).
- Secrets: env-driven (`.env`: POSTGRES/NATS/REDIS/BETTER_AUTH/S3); chei CA/policy în volume dedicate
  (`lokilinux-ca-key`, policy key separat) — fără hardcodare.
- NATS: auth mandatory (`--user/--pass`), porturi interne doar.
- Rețele: segmented (data/app/web internal, gateway, egress=api only); doar fe/api/grpc publicate.
- Healthchecks: toți prezente (api=python stdlib, fe=wget, compliance=distroless self-check,
  ca-signer=UDS socket check, migrate=condition-based).

## Findings

- HIGH — imaginea `lokilinux/api`: 44 HIGH (util-linux CVE-2026-78408/9/10 afectate,
  ncurses CVE-2025-69720, perl-base CVE-2026-9538 `fix_deferred`). Total: **44 HIGH**.
- HIGH — imaginea `lokilinux/frontend`: 3 HIGH; 2 deja acoperite de `.trivyignore`.

## Severitate

- CRITICAL: 0.
- HIGH: 44 (api) + 3 (fe, parțial acceptat).
- MEDIUM/LOW: în curs de audit.

## Recomandări

- Bump base image backend (python:3.11.15-slim → nouă 3.11.x) — să lichidisești cele 44 HIGH.
- Re-evalua `.trivyignore` după bump.

---

Nu a fost modificată nicio configurație pentru vârful acestui audit.
