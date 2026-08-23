# 08 — API deschis & MCP (design viitor)

> Document de design, august 2026. Starea actuală e documentată contra cod la commit `77c4220`; secțiunile „API deschis" și „MCP" sunt **plan de implementare**, nu cod existent.

## Rol

Documentul explică cum funcționează API-ul LokiLinux astăzi și stabilește calea spre două obiective viitoare: (1) deschiderea REST API către consumatori externi (integrări, scripting) prin **Personal Access Tokens** și (2) un **server MCP** care expune operațiunile platformei clienților AI.

## Cum funcționează API-ul astăzi

### Două API-uri separate

| API | Port | Clienți | Securitate |
|---|---|---|---|
| REST `/api/v1` | 8000 | Frontend Nuxt (+ viitor: integrări externe) | Bearer token sesiune Better Auth |
| gRPC `AgentService` | 50051 | Doar agenți Go | mTLS cu certificate CA intern |

gRPC-ul nu intră în discuția „API deschis" — e canal privat agent-server, definit în `proto/lokilinux.proto`, transport JSON sub codec `"proto"`.

### Lanțul de autentificare REST (real, `backend/lokilinux/auth/`)

```
Client ── Authorization: Bearer <opaque-token> ──► FastAPI dependency chain
                                                      │
                     ┌────────────────────────────────┤
                     ▼                                ▼
          get_current_user()                  require_role(*roles)
          (auth/jwks_validator.py)            (auth/dependencies.py:34)
                     │                                │
   GET {BETTER_AUTH_URL}/api/auth/get-session     citește rolul user-ului
   cu același header Bearer                       din răspunsul de sesiune
   → cache Redis per-token, TTL 60s
   → 401 dacă invalid/expirat/fără sesiune activă
```

Observații importante din cod:

1. **Token-ele sunt opaque session tokens** (`jwks_validator.py:2-5`): „Better Auth emite opaque session tokens (nu JWT RS256)". Validarea e **prin delegare** — backendul nu interpretează token-ul, întreabă frontend-ul (unde trăiește Better Auth).
2. **Cache Redis** `ba:session:{token}`, TTL 60s + cheie de circuit-breaker `ba:down:{token}` când frontend-ul e indisponibil.
3. **RBAC** = factory de dependencies: fiecare rută își declară rolurile acceptate; cinci roluri (`ADMIN`/`MANAGER`/`OPERATOR`/`VIEWER`/`AUDITOR`).
4. **Contract public gratuit**: FastAPI generează OpenAPI automat — `/docs` (Swagger UI) + `/openapi.json`.
5. **Model async**: operațiile lungi returnează `202`/`job_id`; progresul se citește prin polling REST. Același model rămâne valabil pentru consumatori externi.

### De ce sesiunile de browser nu sufică pentru API deschis

Token-ele actuale sunt legate de sesiuni interactive: expiră odată cu ele, nu au scopes, nu pot fi rotate/revocate independent, iar auditul le atribuie unui om, nu unei integrări.

## API deschis — Personal Access Tokens (PAT)

### Principiu

Better Auth rămâne furnizorul de identitate pentru **oameni**; integrările mașină-mașină primesc **PAT-uri proprii**, validate local de backend fără delegare. Un singur branch în dependency-ul existent, zero refactor pe routere.

### Schema `api_tokens` (propus)

| Câmp | Tip | Rol |
|---|---|---|
| `id` | UUID PK | Identificator audit |
| `name` | text | Etichetă umană („CI pipeline", „MCP read-only") |
| `owner_user_id` | UUID | User Better Auth proprietar — token-ul moștenește plafonul rolului lui |
| `token_hash` | SHA-256 hex, unique | Niciodată plaintext; hash-ul se calculează la fiecare validare (ieftin) |
| `scopes` | JSONB list | Ex. `["servers:read", "jobs:write"]` |
| `expires_at` | timestamptz nullable | Null = fără expirare (nerecomandat) |
| `last_used_at` | timestamptz | Actualizat la validare (batched prin cache) |
| `revoked_at` | timestamptz nullable | Revocare soft, instant |

### Generare securizată

```
POST /api/v1/admin/api-tokens          (rol ADMIN sau self-service pt. propriile token-uri)
  body: {name, scopes[], expires_at?}
  ─► secret = "llk_" + base64url(32 bytes din secrets.token_bytes())
  ─► DB: doar SHA-256(secret); plaintext returnat O SINGURĂ DATĂ în răspuns
  ─► audit log: "token created" (fără secret)
```

Format prefixat `llk_` permite identificarea tipului de token dintr-o privire și evită coliziunea cu sesiunile opaque Better Auth.

### Validare (branch în `get_current_user`)

```
Bearer începe cu "llk_"?
  ├─ DA → SHA-256(token) → lookup api_tokens (+ cache Redis TTL ~30s,
  │        invalidat la revocare) → verifică revoked_at/expires_at
  │        → principal = {user_id, scopes, token_id}
  └─ NU → fluxul actual get-session Better Auth
```

### Scopes

Granularitate resursă+acțiune, mapate peste RBAC-ul existent:

| Scope | Acoperă |
|---|---|
| `servers:read` | GET `/servers`, `/dashboard`, inventar |
| `servers:write` | mentenanță, assignment |
| `jobs:read` / `jobs:write` | job-uri + aprobări |
| `vulnerabilities:read` / `vulnerabilities:write` | CVE remediate/accept-risk/rescan |
| `workflows:read` / `workflows:write` | CRUD + run/cancel/approve |
| `compliance:read` | drift, baselines, rapoarte |
| `admin:write` | DOAR dacă owner e ADMIN — tokens, settings |

Enforcement: o dependință `require_scope("jobs:write")` alături de `require_role`; pentru PAT se aplică scope-ul, pentru sesiuni se aplică rolul (sau ambele, cel mai restrictiv).

### Rate limiting & audit

- Counter Redis per token (`rate:{token_id}`, fereastră fixă) — prag configurabil global, ex. 600 req/min.
- Audit existent primește actor `token:<id>` — fiecare acțiune de scriere rămâne trasabilă.
- Revocare: `PATCH .../revoked` → șterge cheia Redis → următorul request primește 401.

## Server MCP (Model Context Protocol)

### Ce este

Protocol standard prin care un server expune *tools* apelabile de clienți AI (Claude Code, IDE-uri agenți). Pentru LokiLinux: ops-urile devin invocabile conversațional — „arată serverele cu CVE critice nepatchuite și deschide un job de update".

### Arhitectura recomandată

```
Client AI (Claude Code etc.)
   │ MCP: stdio (local) sau HTTP streamable + TLS (shared/team)
   ▼
lokilinux-mcp   ← proces separat, repo nou; Python fastmcp sau TS SDK
   │ HTTP → Authorization: Bearer llk_<PAT cu scopes minime>
   ▼
REST /api/v1 existent        ← ZERO acces direct la DB / NATS / gRPC
```

Reguli de aur:

1. **Wrapper subțire peste REST** — moștenește gratis auth, RBAC/scopes, rate limit, audit. Fără a doua cale spre date.
2. **Un PAT per utilizator/client AI** — scopes minime necesare; read-only implicit.
3. Secretul trăiește doar în config-ul clientului AI al utilizatorului; serverul MCP îl forward-ează, nu-l loghează niciodată.

### Tools propuse (prima generație)

| Tool | REST subiacent | Scope |
|---|---|---|
| `list_servers(status?)` | GET `/servers` | `servers:read` |
| `get_server(agent_id)` | GET `/servers/{id}` + packages | `servers:read` |
| `list_cves(severity?, patchable?)` | GET `/vulnerabilities` | `vulnerabilities:read` |
| `create_package_update_job(agent_ids, packages?)` | POST `/jobs` | `jobs:write` |
| `get_job(job_id)` | GET `/jobs/{id}` + results | `jobs:read` |
| `run_workflow(workflow_id, agents)` | POST `/workflows/{id}/run` | `workflows:write` |
| `compliance_overview()` | GET `/compliance/overview` | `compliance:read` |

Tools de scriere pornesc read-only în prima iterieție (flag de config al serverului MCP), apoi se deblochează cu PAT-uri scoped corespunzător.

## Roadmap de implementare

| Pas | Livrabil | Efort orientativ |
|---|---|---|
| 1 | Tabel `api_tokens` (migrare Alembic) + CRUD admin + branch `llk_` în `get_current_user` | mic |
| 2 | `require_scope()` + enforcement pe rutere + audit actor `token:<id>` | mic-mediu |
| 3 | Rate limit Redis per token + endpoint revocare | mic |
| 4 | Curățare OpenAPI (tags, descrieri, examples) pt. consum extern | mediu |
| 5 | `lokilinux-mcp`: fastmcp + cele 7 tools, transport stdio, PAT din env/config | mediu |
| 6 | Transport HTTP streamable remote (TLS) + tooling de onboard | mediu |

## Decizii de design

1. **PAT propriu, nu OAuth2** — single-tenant self-hosted; client credentials aduc redirect flows și lifecycle inutil aici.
2. **Hash-only la rest** — leak-ul DB-ului nu compromite token-uri active; rotirea = creare + revocare.
3. **Prefix `llk_` ca discriminator** — un singur punct de bifurcație în auth, fără cost pe sesiunile existente.
4. **Scopes ≤ rolul owner** — un token nu poate depăși ce poate omul care l-a creat.
5. **MCP peste REST, nu peste DB** — contractul public rămâne unul singur; MCP-ul e client, nu strat de acces.
6. **Latency acceptată explicit** — dispatch job prin heartbeat (~60s): UI-ul și MCP tools comunică onest starea „waiting for agent", conform principiilor PRODUCT.md.
