# Audit Nuxt 4 — LokiLinux Frontend · Plan detaliat de optimizare & securitate

> Scope aprobat: **P0 + P1 + P2** · CSP moderată + header-e stricte · HSTS da (TLS termination) · SSR țintit 4 pagini · token eliminat din payload SSR.
>
> Toate căile sunt relative la `/opt/lokilinux/frontend`. Ordinea = ordinea de execuție.
> Context audit: Nuxt `^4.5.2`, Node v22.23.2, ~17.750 LOC, 39 pagini, Better Auth + Kysely/Postgres pe Nitro, proxy `/api/v1/**` → FastAPI.

---

## Faza 0 — Baseline (măsurători înainte de orice modificare)

1. `npx nuxi build` pe starea actuală → salvez dimensiunile (raw + gzip) pentru chunk-urile cheie din `.output/public/_nuxt/`:
   - entry JS
   - chunk @unovis (~52 KB gz)
   - chunk vue-flow (~117 KB gz)
   - chunk codemirror (~136 KB gz)
2. `npm run test` → confirm baseline verde (suitele existente trec).
3. Preview local + `curl -sI http://localhost:3000/auth/login` → baseline headere HTTP (acum doar Cache-Control; fără security headers).

---

## Faza 1 — Security (P0)

### 1.1 Rate limiting Better Auth — `server/utils/auth.ts`

**Problema:** limiterul Better Auth este dezactivat implicit în producție → login/signup fără protecție brute-force. Infrastructura anti-spoof XFF există deja în `server/api/auth/[...all].ts:11-18`.

**Modificare:** în obiectul `betterAuth({...})` (linia 58):

```ts
rateLimit: {
  enabled: true,
  window: 60,
  max: 100,
  specialRules: {
    '/sign-in/email': { window: 60, max: 5 },
    '/sign-up/email': { window: 60, max: 3 },
  },
},
```

**Risc:** mic — limite generoase general, stricte doar pe sign-in/up (protecție NAT-friendly).

### 1.2 Security headers — `nuxt.config.ts`

**Problema:** zero security headers în tot proiectul (fără CSP, HSTS, nosniff, frame-ancestors etc.).

**Modificare:** extind `routeRules['/**'].headers` cu:

```
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
Strict-Transport-Security: max-age=15552000
Content-Security-Policy:
  default-src 'self';
  script-src 'self';
  style-src 'self' 'unsafe-inline';   /* justificat: vue-flow/unovis injectează stiluri runtime */
  img-src 'self' data: blob:;
  connect-src 'self';
  font-src 'self';
  frame-ancestors 'none';
  base-uri 'self';
  form-action 'self'
```

**Atenție — script anti-FOUC inline** (`app.head.script`, liniile 27–33): va fi blocat de `script-src 'self'`.
- **Plan A (preferat):** mut snippet-ul static într-un fișier `/public/theme-init.js` servit same-origin + `<script src>` în head.
- **Plan B (fallback):** adaug hash-ul SHA-256 al snippet-ului în CSP (`script-src 'self' '<hash>'`).

**Verificare obligatorie la Faza 4:** preview + click-through `/workflows/[id]`, login, toasts — fără violări CSP în consolă.

### 1.3 Token afară din payload SSR — `utils/api.ts` + `composables/useAuth.ts`

**Problema:** `useState('auth:token')` serializază session token-ul în HTML-ul SSR pe fiecare randare → blast radius XSS mărit.

**Constrângere descoperită:** FastAPI validează sesiuni prin Better Auth (bearer plugin activ); neconfirmat dacă acceptă cookie direct → nu pot baza clientul exclusiv pe cookie fără risc de rupere totală.

**Soluția (același efect de securitate, zero risc comportamental):**

1. În `utils/api.ts:19`: înlocuiesc `useState<string | null>('auth:token')` cu variabilă de modul ne-reactivă:

```ts
let bearerToken: string | null = null
export function setBearerToken(t: string | null) {
  bearerToken = t
}
```

2. `onRequest` citește `bearerToken`; ramura SSR (liniile 31–38, dynamic import session) rămâne neschimbată.
3. `composables/useAuth.ts:14-21` (`refreshAuthToken`): apelează `setBearerToken(token)` în loc de `useState`.
4. Verific/ajustez mock-ul din `pages/auth/login.test.ts:26` dacă e necesar (semnătura publică neschimbată).

**Rezultat:** token-ul nu mai ajunge niciodată serializat în HTML; clientul trimite Bearer exact ca înainte.

### 1.4 2FA gate server-side — `server/utils/auth.ts` + `server/middleware/auth.ts`

**Problema:** 2FA enforcement există doar client-side (`middleware/auth.global.ts:15-21`, recunoscut în comentariul din cod ca fiind ocolibil).

**Modificări:**

1. `loadSecuritySettings()` (`server/utils/auth.ts:33-54`): adaug `"security.require_2fa"` la query-ul `ANY($1)` + câmp în rezultat și în `SECURITY_DEFAULTS` (`require2FA: false`). Export setting-urile pentru reutilizare.
2. `server/middleware/auth.ts`, după blocul `if (!session)`:

```ts
if (
  settings.require2FA &&
  !(session.user as { twoFactorEnabled?: boolean }).twoFactorEnabled &&
  path !== '/account/security'
) {
  await sendRedirect(event, '/account/security', 302)
}
```

3. `middleware/auth.global.ts`: păstrez doar guard-ul client-side de existență sesiune (UX instant); șterg blocul „soft 2FA enforcement" (liniile 15–22) + comentariul asociat — devin redundanți față de gate-ul server-side.

**Risc:** mediu-mic — redirect server-side trebuie să permită `/account/security` și asset-urile (deja allowlist la liniile 6–12).
**Test flux complet:** user nou + require_2fa ON → enroll → acces normal; curl cu cookie de sesiune ocolește UI-ul dar primește redirect server-side.

---

## Faza 2 — Performance (P1)

### 2.1 Tabs lazy — `components/ui/AppTabs.vue`

**Problema:** panourile inactive se montează imediat (`v-show`, linia 46) → pe `/workflows/[id]` se încarcă ȘI CodeMirror (136 KB gz) ȘI Vue Flow (117 KB gz), indiferent de tab-ul activ.

**Modificare:** `v-show="active === i"` → `v-if="active === i"` pe panou (păstrez `role="tabpanel"` + aria).

**Impact:** −~250 KB JS executat la intrarea pe `/workflows/[id]`; TBT ↓ semnificativ.

**Verific compatibilitate:** caut consumatori care depind de montajul tuturor panourilor (`workflows/[id].vue`, playbook/roles editors) — polling-uri de fundal inactive ar fi afectate (nu am găsit astfel de cazuri în explorare).

### 2.2 Eliminare duble request-uri

**a) `/plugins` fetch-uit până la 3×/vizită:**
- `layouts/default.vue` (~linia 342, gate-ul `ansibleEnabled`): fetch doar dacă `pluginsStore.plugins.length === 0`.
- `pages/plugins/index.vue:6`: elimin `await store.fetchPlugins()` top-level (SSR-discard — Pinia nu serializează starea); pagina primește datele de la layout.
- Poll-ul de instalare rămâne neschimbat.

**b) Cursa `/dashboard/summary`:**
- `stores/dashboard.ts` `ensureSummary()` (~linia 270) — guard cu promisiune în zbor:

```ts
let inflight: Promise<void> | null = null
async function ensureSummary() {
  if (summary.value) return
  inflight ??= loadSummary().finally(() => {
    inflight = null
  })
  return inflight
}
```

### 2.3 Conversie SSR țintită (4 pagini)

**Constrângere de design (critică):** Pinia NU serializează starea în payload → mutarea mecanică a store-action-urilor în `useAsyncData` ar reproduce dublul-request. Pattern-ul aplicat:

> `useAsyncData(key)` deține datele paginii; handler-ul apelează API-ul (prin `useApi()`) și populează store-ul pentru mutații; pagina citește din `data` returnat, nu direct din store. La hidratare Nuxt sare peste handler (payload existent) → zero re-fetch.

| Pagină | Cheie | Conținut |
|---|---|---|
| `pages/index.vue` | `dashboard-overview` | agregat summary+trends+widgets (înlocuiește fan-out-ul din `onMounted`, linia 24); layout-ul primește summary prin același store sincronizat |
| `pages/servers/index.vue` | `servers-list` | liste + categorii; formatarea `toLocaleString` rămâne client-only (`<ClientOnly>` local pe celule sau format la mounted — comentariul liniilor 10–15 rămâne relevant) |
| `pages/jobs/index.vue` | `jobs-list` | lista jobs + opțiuni agenți; polling-ul de 5s rămâne neschimbat |
| `pages/vulnerabilities/index.vue` | `vulns-overview` | cele 5 fetch-uri din `onMounted` (liniile 9–15) → un singur `useAsyncData` paralel |

Restul (~20 pagini) rămân client-first intenționat, documentat printr-un comentariu scurt pe fiecare dintre cele 4 convertite.

**Risc:** cel mai mare al planului — mitigat prin conversie pagină-cu-pagină cu verificare manuală după fiecare.

### 2.4 Limite explicite pe liste fără bound

Adaug parametri `limit` expliciti (implicit 200 pentru liste admin) — nu schimb contractul backend-ului, doar query params acceptați deja:

- `stores/playbooks.ts:28`
- `stores/playbook_templates.ts:24`
- `stores/ansible_roles.ts:22`
- `stores/ansible_projects.ts:20`
- `stores/plugins.ts:41`
- `stores/policies.ts:70`
- `stores/jobs.ts:90` (job results)
- `stores/vulnerabilities.ts:152` (CVE resources)

---

## Faza 3 — Curățenie (P2)

### 3.1 Dead code (ștergeri pure)

| Locație | Simbol | Motiv |
|---|---|---|
| `stores/compliance.ts:423-439` | `fetchInventorySnapshot` + `inventorySnapshot/Error/Loading` | 0 referințe (confirmat prin grep) |
| `stores/compliance.ts:441-446` | `fetchInventoryHistory` + `inventoryHistory` | 0 referințe |
| `stores/compliance.ts:987-992` | `fetchAssessment` | 0 referințe |
| `nuxt.config.ts:115` | `runtimeConfig.betterAuthSecret` | declarat, niciodată folosit (`auth.ts:60` citește `process.env` direct) |
| `components/server/MetricsCards.vue:13` | `formatBytes()` local duplicat | util-ul auto-importat există (`utils/formatBytes.ts`) |
| `stores/workflows.ts` / `policies.ts` | `total` neafișat | verific template-urile o ultimă dată înainte de ștergere |

### 3.2 Deduplicare

**a) Factory CRUD** — `stores/crud.ts` nou (~40 linii): `createCrudStore<T>(resource, opts)` generând `items/loading/error/fetch/create/update/delete`. Migrez:
- `stores/playbooks.ts` (61 linii)
- `stores/playbook_templates.ts` (60)
- `stores/ansible_roles.ts` (51)
- `stores/ansible_projects.ts` (45)

≈217 linii → ≈60. Semnăturile publice rămân identice → zero schimbări în consumatori.

**b) Helper cursor-paginare** — intern în `stores/compliance.ts`: `fetchCursorPage<T>(path, params, targets)` colaps al celor 8 blocuri identice (liniile 346, 467, 501, 570, 640, 717, 843, 890) → ~200 linii salvate.

**c) Constant maps consolidate** — `utils/severityColors.ts` nou: `SEVERITY_COLORS`, `JOB_STATUS_COLOR`, `SERVER_STATUS_COLOR`. Actualizez cele ~8 pagini care le copiază (inclusiv `pages/index.vue:47-52`, `vulnerabilities/index.vue:17-19`, `vulnerabilities/list.vue:36-38`).

**d) Comentariu corectat** — `nuxt.config.ts:98-102`: „dynamic-imported, ~45KB gz" → realitatea: import static izolat pe rută, ~117 KB gz, montaj amânat prin tab lazy (2.1).

**Nu consolidez în această fază (decizie conștientă):**
- `workflow.ts` vs `workflows.ts` — responsabilități diferite (editor vs listă);
- split-ul god-store-ului `compliance.ts` pe domenii — prea invaziv pentru această sesiune;
- composables triviale (`useJobs`, `useServers`, `useSeverity`) — P3, exclus din scope.

---

## Faza 4 — Verificare

```bash
npm run test                 # toate suitele trec
npx vue-tsc --noEmit         # typecheck (nu există script dedicat în package.json)
npx nuxi build               # build reușit
```

**Comparativ bundle:** raport before/after pe entry + chunk-urile cheie din Faza 0.

**Manual (preview local):**
1. `curl -sI http://localhost:3000/auth/login` → toate headerele noi prezente; CSP fără violări în consola browser.
2. Login funcțional **fără token în sursa paginii** (`grep 'auth:token'` pe HTML → 0 rezultate).
3. User fără 2FA + `require_2fa=true` → redirect `/account/security` și server-side (curl cu cookie de sesiune).
4. Rate limit: >5 POST `/api/auth/sign-in/email` într-un minut → 429.
5. Navigare: `/`, `/servers`, `/jobs`, `/vulnerabilities` — date la primul paint (SSR), zero duble request-uri în Network tab; `/workflows/[id]` — CodeMirror/Vue Flow se încarcă doar la activarea tab-ului; toasts funcționale; login/logout/2FA end-to-end.

---

## Risc & Impact — sumar

| Modificare | Risc | Impact așteptat |
|---|---|---|
| Rate limiting (1.1) | mic | brute-force blocat pe login/signup |
| Headers + CSP (1.2) | mic-mediu (testare) | OWASP baseline complet |
| Token out of payload (1.3) | mic | XSS blast radius redus |
| 2FA server-side (1.4) | mediu-mic | gap P0 real, recunoscut în cod, închis |
| Tab lazy (2.1) | mic | −250 KB JS executat pe workflows |
| Duble fetch (2.2) | mic | −1..2 request-uri/vizită |
| SSR 4 pagini (2.3) | mediu | LCP ↓ vizibil pe dashboard/liste |
| Limite explicite (2.4) | minim | protecție împotriva răspunsurilor uriaeșe |
| Dedup stores (3.x) | mic (tipizare strictă) | ~400 linii eliminate |

## Explicit în afara scope-ului (recomandări viitoare)

1. Split-ul `stores/compliance.ts` (1027 linii) pe domenii.
2. Simplificarea composables triviale (`useJobs`, `useServers`, `useSeverity`).
3. Optimizarea `public/logo.svg` (29.7 KB raw → sub 2 KB posibil).
4. Mutarea PNG-urilor de screenshot (~700 KB) din rădăcina `frontend/`.
5. HSTS preload + revizuire `trustedOrigins` localhost în producție.
6. Migrarea rate limiting la Redis/shared storage pentru deployment distribuit.
7. Conversia SSR a celorlalte ~20 pagini client-first (doar unde justifică traficul).
8. Curățarea dynamic import-urilor modulelor server din cod universal (`useAuth.ts:41`, `api.ts:34`) — fragil la refactor.
