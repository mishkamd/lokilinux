# 01 — Frontend (Nuxt 4 + Vue 3)

> Documentație generată din cod la commit `77c4220` (v0.3.0), august 2026.

## Rol

Aplicația web single-page (cu SSR) a platformei: dashboard, management flota, vulnerabilități, compliance, workflow-uri builder, automatizare Ansible, plugin marketplace și administrare utilizatori. Găzduiește și **Better Auth** — furnizorul de identitate pentru întreaga platformă (backendul validează token-urile prin delegare).

## Tehnologii

| Componentă | Versiune | Rol |
|---|---|---|
| Nuxt | 4.5.2 | Framework full-stack Vue |
| Vue | 3.5.39 | UI reactiv |
| TypeScript | 6.x | Tipizare |
| Pinia | 3.x | State management |
| Better Auth | — | Sesiuni/JWKS, stocate în Postgres |
| Node | 22 | Runtime container |

## Compoziție

```
frontend/
├── pages/                 # File-based routing
│   ├── index.vue          # Dashboard
│   ├── servers/           # index.vue, [id].vue
│   ├── jobs/, alerts/, agents/, plugins/, policies/ ([id].vue)
│   ├── vulnerabilities/   # index.vue, list.vue, [cve].vue
│   ├── compliance/        # index.vue + baselines/, policies/, drift/, file-integrity/ (fiecare cu index + [id])
│   ├── workflows/         # index.vue, [id].vue (builder + runs)
│   ├── automation/ansible/# projects, roles, playbooks, templates (index + [id])
│   ├── admin/             # audit.vue, settings.vue, users/ (utilizatori, roluri)
│   ├── account/security.vue, auth/login.vue
├── stores/                # Pinia — sursa de adevăr client
│   ├── servers.ts (+test), jobs.ts, vulnerabilities.ts, dashboard.ts
│   ├── policies.ts, plugins.ts
│   ├── playbooks.ts, playbook_templates.ts, ansible_projects.ts, ansible_roles.ts
│   ├── compliance.ts (35K, +test 8.5K)   # reguli, baselines, drift, exceptions
│   ├── workflow.ts (23K)                  # builder state, validare, run-uri
│   └── workflows.ts                       # listare
├── composables/           # useAuth, useServers, useJobs, useSeverity, useBranding, useToast
├── components/            # Componente reutilizabile
├── middleware/auth.global.ts    # Guard rute protejate
├── plugins/auth.client.ts       # Client Better Auth hidratat
├── server/                # Partea server Nuxt:
│   ├── api/auth/[...all].ts     # Mount Better Auth (/api/auth/*)
│   ├── utils/auth.ts            # Instanța Better Auth (adapter Postgres)
│   ├── utils/session.ts         # Utilitare sesiune
│   ├── middleware/auth.ts       # Protecție API auth
│   └── routes/health.get.ts     # /health pentru healthcheck Docker
└── nuxt.config.ts         # apiBase relativ (/api/v1) → proxy same-origin
```

## Cum funcționează

### Autentificare (Better Auth)

1. Login la `/auth/login` → POST `/api/auth/sign-in/email` (handler Nuxt server).
2. Better Auth creează sesia în **Postgres** (același DB, schema proprie) și emite cookie + JWT semnat cu `BETTER_AUTH_SECRET`.
3. Frontendul apelează REST backend cu `Authorization: Bearer <jwt>`.
4. Backendul FastAPI validează token-ul **prin delegare**: interoghează endpoint-ul de sesiune al frontendului (`BETTER_AUTH_INTERNAL_URL`), inclusiv JWKS.
5. Roluri: `ADMIN`, `MANAGER`, `OPERATOR`, `VIEWER`, `AUDITOR` — gestionate din `/admin`.

### Acces la API

- Browser: `NUXT_PUBLIC_API_BASE=/api/v1` **relativ** — cererile pleacă pe același origin (:3000), proxy-uite de Nuxt spre `lokilinux-api:8000` (`API_INTERNAL_URL`) → zero probleme CORS.
- SSR folosește direct `http://lokilinux-api:8000`.

### Store-uri Pinia

Fiecare domeniu are un store care încapsulează fetch/CRUD/caching local:

| Store | Acoperire |
|---|---|
| `servers` | Listă agenți, detalii, pachete, mentenanță |
| `jobs` | Job-uri + rezultate live |
| `vulnerabilities` | CVE-uri, trend-uri, remediere/accept-risk |
| `compliance` | Cel mai mare (35K): rules, policy sets, assignments, baselines + versionare, drift events, exceptions, inventory, file integrity |
| `workflow` | Builder: noduri/muchii, YAML compile/validate, versiuni, publish, run-uri, approve/reject pași |
| `dashboard` | Summary + trends |

### Pagini principale

| Rută | Ce face |
|---|---|
| `/` | Dashboard: agenți sănătoși, CVE-uri critice, job-uri active, trend-uri |
| `/servers`, `/servers/[id]` | Flota + inventar per host |
| `/jobs` | Istoric job-uri, aprobări, rezultate |
| `/vulnerabilities` | CVE-uri: filtrare, patchable, remediere ghidată |
| `/policies`, `/policies/[id]` | Politici de patch management |
| `/compliance` | Dashboard compliance + subsecțiuni: `/compliance/policies`, `/compliance/baselines`, `/compliance/drift`, `/compliance/file-integrity` |
| `/workflows`, `/workflows/[id]` | Workflow Builder: editor grafic, versiuni, dry-run, execuții |
| `/automation/*` | AWX-like: proiecte, roles, playbooks, job templates |
| `/plugins` | Marketplace plugin-uri (ciclu PENDING_INSTALL→ENABLED) |
| `/admin` | Utilizatori, roluri, setări agent-config, audit log |

## Dependențe

- `lokilinux-api` (REST `/api/v1`) — singura sursă de date business.
- Postgres — tabelele Better Auth (sesiuni/utilizatori).
- `BETTER_AUTH_SECRET` comun cu backendul.

Dependenți: backendul FastAPI (delegare validare token), utilizatorii browser.

## Decizii de design

1. **Auth în frontend** — Better Auth embedded: un singur loc definește sesiunile; API-ul rămâne stateless.
2. **Proxy same-origin** — apiBase relativ elimină CORS și simplifică deploy-ul în spatele unui singur hostname.
3. **Store-uri per domeniu** — fiecare pagină citește din store-ul ei; store-urile mari (compliance, workflow) testeate unitar (`*.test.ts`).
4. **Builder grafic pentru workflow** — validarea se face tot pe server (`POST /workflows/validate`), clientul doar pre-validază UX.
