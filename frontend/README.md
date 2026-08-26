# LokiLinux Frontend

Nuxt 4 single-page control surface for the LokiLinux platform: fleet dashboard, server management, jobs, CVEs, compliance, workflow builder (visual), Ansible automation, observability suite (events → signals → incidents → correlation → runbooks → topology), plugin marketplace and user admin. Also hosts **Better Auth** — the platform's identity provider.

Companion docs: [root README](../README.md) · [backend README](../backend/README.md) · [architecture overview](../docs/ARCHITECTURE.md).

## Stack

| Layer | Tech | Notes |
|---|---|---|
| Framework | Nuxt 4.5.2 + Vue 3.5 | SSR enabled (`ssr: true`, `compatibilityVersion: 4`) |
| Language | TypeScript (strict) | `vue-tsc` for type checking |
| State | Pinia 3 (`@pinia/nuxt`) | One store per API domain |
| Styling | Tailwind CSS 4 + `tailwindcss-animate` | Via `@tailwindcss/vite` plugin |
| UI primitives | radix-vue, lucide-vue-next, vue-sonner | shadcn-style `components/ui` |
| Graphs | @unovis/ts + @unovis/vue | Dashboard/compliance charts |
| Flow canvas | Vue Flow (+ background/minimap) | Visual workflow builder at `/workflows/[id]` |
| YAML editor | CodeMirror 6 + `@codemirror/lang-yaml` | Workflow/playbook editors |
| Auth | better-auth 1.6 + @better-auth/kysely-adapter | Sessions backed by Postgres via Kysely |
| DB access (auth only) | kysely + pg | Server-side session store, connects through pgBouncer |
| Fonts | @nuxt/fonts (Inter, Iceberg) | Self-hosted via Google provider |
| Tests | Vitest 4 + happy-dom + @vue/test-utils | `npm test` / coverage with `npm run test:coverage` |
| Runtime image | node:22.23.1-alpine | Non-root user `nuxt` (uid 10001) |

## Architecture

```text
Browser ──► Nuxt (Nitro, :3000)
              │
              ├─ pages/           file-based routes (SSR except /workflows/**)
              │     │  composable/store fetch ──┐
              │                                 ▼
              ├─ routeRules '/api/v1/**' ─ proxy ─► lokilinux-api :8000 (web-net)
              │        (same-origin proxy, Cache-Control: no-store)
              │
              ├─ server/api/auth/**  Better Auth handlers
              ├─ server/middleware/  auth guard — every route requires a session
              ├─ server/utils/       auth instance + Platform Settings from Postgres
              │                        (kysely → pgbouncer:5432)
              ▼
         node:22 alpine container (non-root, read-only rootfs)
```

Key wiring in `nuxt.config.ts`:

- **Same-origin API proxy** — clients call `NUXT_PUBLIC_API_BASE` (default `/api/v1`, relative). The Nitro route rule `'/api/v1/**': { proxy: API_INTERNAL_URL + '/api/v1/**' }` forwards to the FastAPI container. Result: one public origin, no CORS.
- **SSR base** — server-side code reaches the API directly via `API_INTERNAL_URL` (default `http://lokilinux-api:8000`).
- **Cache rules** — default `Cache-Control: no-store` on everything (authenticated session data must never be cached); exception `/_nuxt/**` which is content-hashed and immutable. The proxied `/api/v1/**` also forces `no-store`.
- **Auth everywhere** — `server/middleware/auth.ts` guards every route; there is no public content. Meta robots set to `noindex, nofollow`.
- **Anti-FOUC** — inline script seeds the dark color mode before hydration; theme toggle stored under the `lokilinux-color-mode` key.
- **`/workflows/**` renders CSR-only** (`ssr: false`) — Vue Flow measures DOM transforms at mount; this also keeps the ~45KB gz canvas bundle out of other routes.
- **Vite `allowedHosts: ['lokilinux-frontend']`** — required so the backend's Better Auth session validation can reach the container by its Docker hostname during dev.

## Directory Map

```text
frontend/
├── app.vue                  # Root component wrapper
├── error.vue                # Branded error page
├── nuxt.config.ts           # Proxy, cache rules, fonts, modules, runtimeConfig
├── assets/css/global.css    # Tailwind entry + theme tokens
├── components/
│   ├── ui/                  # shadcn-style primitives (radix-vue based)
│   ├── dashboard/           # Dashboard widgets / charts
│   ├── workflow/            # Visual builder: nodes, edges, inspector panels
│   ├── server/              # Server detail components
│   └── *.vue                # Feature pieces (JobDetail, PolicyWizard, PlaybookEditor, UserSettingsModal…)
├── composables/             # useAuth, useBranding, useJobs, useServers, useSeverity, useToast
├── layouts/                 # default (app shell), auth (login screen)
├── middleware/
│   └── auth.global.ts       # Client-side auth redirect guard (+ tests)
├── pages/                   # File-based routing:
│   ├── index.vue            # Dashboard
│   ├── account/ admin/ agents/ alerts/
│   ├── automation/ansible/  # projects · roles · playbooks · templates
│   ├── compliance/          # baselines · drift · exceptions · file-integrity · policies · remediation · reports · rules
│   ├── correlation/ events/ incidents/ signals/ runbooks/ topology/   # observability suite
│   ├── jobs/ policies/ plugins/ servers/ vulnerabilities/ workflows/
│   └── security/            # audit log
├── plugins/auth.client.ts   # Better Auth client init
├── server/
│   ├── api/auth/[...all].ts # Better Auth catch-all handler
│   ├── middleware/auth.ts   # Server-side session guard (every route)
│   ├── routes/health.get.ts # Container healthcheck endpoint (:3000/health)
│   └── utils/               # auth instance, kysely db, session helpers, migrate runner
├── stores/                  # 18 Pinia stores — one per domain incl. compliance (32K),
│   │                        #   workflow builder state (24K), vulnerabilities, incidents…
│   └── *.test.ts            # Store unit tests (compliance, servers)
├── types/ utils/            # Shared TS types & helpers
├── public/                  # Static assets (logo.svg, brand images)
├── scripts/                 # Build/dev helper scripts
├── vitest.config.ts         # happy-dom environment
├── Dockerfile               # Multi-stage: npm ci → nuxi build → non-root node runtime
└── package.json             # v0.4.0
```

## Pages ↔ API

All data access flows through the same-origin proxy into FastAPI `/api/v1` (see backend README for endpoint inventory). Store-per-domain mapping:

| UI area | Route(s) | Store |
|---|---|---|
| Dashboard | `/` | `dashboard.ts` |
| Fleet | `/servers`, `/agents` | `servers.ts` |
| Jobs | `/jobs` | `jobs.ts` |
| Vulnerabilities | `/vulnerabilities` | `vulnerabilities.ts` |
| Compliance (8 sub-apps) | `/compliance/**` | `compliance.ts` |
| Workflows + visual builder | `/workflows` | `workflow.ts` (builder), `workflows.ts` (list) |
| Ansible automation | `/automation/ansible/**` | `ansible_projects.ts`, `ansible_roles.ts`, `playbooks.ts`, `playbook_templates.ts` |
| Policies / Plugins | `/policies`, `/plugins` | `policies.ts`, `plugins.ts` |
| Observability | `/events`, `/signals`, `/incidents`, `/correlation`, `/runbooks`, `/topology` | matching stores per domain |
| Admin / Account | `/admin/**`, `/account` | auth + settings composables |

## Authentication

Better Auth runs **inside this container**:

- **Handlers**: `server/api/auth/[...all].ts` mounts the full Better Auth surface under `/api/auth/**`; client initialized in `plugins/auth.client.ts` and shared via `useAuth()`.
- **Session storage**: Postgres through the Kysely adapter (`server/utils/auth.ts` → `pg` → pgBouncer). This is why the frontend is attached to `data-net` in docker-compose.
- **Backend validation**: FastAPI validates every Bearer token against `{BETTER_AUTH_URL}/api/auth/get-session` — the frontend is the single source of identity; it owns no tokens itself.
- **Guards**: server middleware (`server/middleware/auth.ts`) protects every SSR route; global client middleware (`middleware/auth.global.ts`) redirects unauthenticated navigations to `/auth/login`.

## Environment

| Variable | Scope | Purpose |
|---|---|---|
| `NUXT_PUBLIC_API_BASE` | runtime (build arg in compose) | Client API base — keep relative (`/api/v1`) for the same-origin proxy |
| `API_INTERNAL_URL` | runtime | SSR/Nitro proxy target (default `http://lokilinux-api:8000`) |
| `BETTER_AUTH_URL` | runtime | Public origin used by Better Auth (default `http://localhost:3000`) |
| `BETTER_AUTH_SECRET` | runtime | Session signing secret (shared conceptually with backend config) |
| `POSTGRES_HOST/PORT/USER/PASSWORD/DB` | runtime | Kysely session-store connection (through pgBouncer) |

## Development

```bash
# From repo root — recommended (full stack wired):
make dev           # hot-reload stack via docker-compose.dev.yml

# Or isolated frontend dev (expects API on localhost:8000):
cd frontend
npm ci --legacy-peer-deps
npm run dev        # nuxi dev --host 0.0.0.0

# Type check / tests
npx vue-tsc
npm test                # vitest run
npm run test:coverage
```

Notes:

- Dev sessions validate against `Host: lokilinux-frontend` — already allowlisted in `nuxt.config.ts` vite server options.
- Production build: `npm run build` → `.output/` served by `node server/index.mjs` (Node 22 target).
- UI polish/design-system decisions live in [`DESIGN.md`](../DESIGN.md).

## Health & Deployment

- Healthcheck: `GET :3000/health` (Nitro route, used by both the Docker HEALTHCHECK and compose).
- Compose service `lokilinux-frontend`: depends on `lokilinux-api` being healthy; ports `3000:3000`; networks `web-net`, `data-net` (auth DB), `gateway-net` (port publishing).
