# Plan de Implementare — LokiLinux Observability (Audit & Modernizare)

Decizii confirmate: **converge on incidents**, **demote topology**, **polling only**, **no Metrics page now**.

---

## A. Current State

**Pipeline (sound overall):**
```
agent gRPC heartbeat ──┐   POST /events ──┐   OTLP /otlp/v1/* ──┐   heartbeat_monitor ──┘
                       ▼                 ▼                     ▼
                    NATS lokilinux.events.raw.*  (JetStream provisioned, never replayed)
                       ▼
        EventProcessorWorker → Redis dedup → ClickHouse `events` (TTL 30d) → EVENT_NORMALIZED
                       ▼
        SignalProcessorWorker → detectors (per-event, sustain counters in Redis)
                       ▼ Postgres `signals` + ClickHouse `signal_occurrences` (90d)
        CorrelationWorker → rule cache (30s) → Redis ZSET windows → IncidentService
                       ▼ Postgres incidents/timeline + ClickHouse evidence (180d) + bridge Alert
        IncidentWorker → auto-resolve sweep (60s) + optional runbook autorun
```

**Legacy stack running in parallel:** HeartbeatMonitor → AlertProcessorWorker → `alerts` table → `/alerts` page. Plus dead `AlertRule` engine (API exists, zero evaluators read `conditions`, zero UI).

**Frontend IA today (6 top-level nav entries):**

| Page | Reality |
|---|---|
| `/alerts` | Flat 100-row table, manual refresh, no pagination (`next_cursor` always None) |
| `/incidents` | Real workflow: ack/resolve/detail/evidence/runbook execute |
| `/signals` | Dedup anomalies, resolve/suppress (suppress cosmetic only) |
| `/events` | Raw payload debugger, no time-range filter despite repo support |
| `/topology` | CRUD form, explicitly no graph, holds nav slot anyway |
| `/correlation` | Rule CRUD — admin config wearing an ops-page costume |

**Dashboard:** 11 endpoints per mount, zero auto-refresh anywhere in observability, new pipeline (signals/incidents) invisible on the homepage.

**Realtime:** none. No SSE/WebSocket. Server detail polls metrics 30s; observability pages: manual button only.

---

## B. Problems

### Critical
| # | Problem | Ref |
|---|---|---|
| C1 | `AgentMetrics` hypertable has no writer — metrics time-series store is dead; health goes to unretained `agent_health` + lossy JSON-in-events | models/agent.py:134 |
| C2 | No secret masking on event/log pipeline — passwords/tokens/Authorization headers stored raw in ClickHouse, served verbatim to any authenticated VIEWER | events.py:100, translate.py:92 |
| C3 | Redis fail-closed dedup: `set_nx` returns False on Redis error → EventProcessor silently discards events as "dupes" during outages | cache.py:157, event_processor.py:66 |

### High
| # | Problem | Ref |
|---|---|---|
| H1 | Two parallel alerting stacks; one host-down creates two alert rows from independent paths | incidents/service.py:158, heartbeat_monitor.py:75 |
| H2 | `POST /servers/{id}/maintenance` guarded by `get_current_user` only — VIEWER can flip fleet hosts into maintenance | servers.py:229 |
| H3 | Signal processor opens a PG session before detector filtering — most messages (heartbeats, INFO noise) need none | signal_processor.py:80 |
| H4 | Per-heartbeat fanout: 2 CH rows + 2 NATS msgs + session + 2-3 SELECTs per beat per agent | grpc/agent_service.py:285 |
| H5 | `agent_health`: one row per heartbeat, no retention/compression — unbounded growth | agent_service.py:327 |
| H6 | Homepage blind to new pipeline; obs pages never auto-refresh | dashboard.ts:236 |

### Medium
| # | Problem | Ref |
|---|---|---|
| M1 | Fingerprint mismatch: member-resolution computes fingerprint without `resource`, upsert stores with it → `compliance.violation` signals never auto-resolve | signals/service.py:52 vs incidents/service.py:59 |
| M2 | Suppression non-durable: next occurrence resets SUPPRESSED→OPEN, re-fires correlation | signals/service.py:74 |
| M3 | RetentionCleanup: single unbounded DELETE on audit_logs — lock/vacuum spikes | retention_cleanup.py:46 |
| M4 | IncidentWorker sweep N+1 over ALL open incidents, no LIMIT, every 60s | incident_worker.py:118 |
| M5 | Incident open race: lock result ignored, check-then-insert, no partial unique index | incidents/service.py:77 |
| M6 | OTLP ingest: no batch cap (events.py caps at 100, otlp.py doesn't) | otlp.py:79 |
| M7 | Rate limiting fails open at both layers | rate_limit.py:38, cache.py:104 |
| M8 | Dashboard card "Active Incidents" renders alerts, not incidents | ActiveIncidents.vue |
| M9 | Frontend duplication: 3 near-identical donuts, 5+ color-map copies (one inconsistent: HIGH=red vs orange), RANGE_OPTIONS ×3, formatBytes ×2 | — |
| M10 | Bugs: events stale-cursor-on-filter-change; servers page silently truncates; alerts pagination absent | events/index.vue:26, servers.ts:136, alert_service.py:150 |

### Low
Dead knobs (`correlation_state_backend`, no-op `retention.metrics_days`), `INCIDENT_UPDATED` published w/ zero subscribers, `/alerts` offset-vs-cursor drift, PATCH-as-PUT on correlation rules, unbounded `/incidents/{id}/timeline` + `/topology`, per-worker prometheus counters flapping under 4 uvicorn workers, triple JSON serialization per event, unsigned base64 cursors, topology edges missing tenant column, stale JWKS docstring, phantom "init SQL" comment in compose, hardcoded detector thresholds/buffer sizes, JetStream replay unwired.

---

## C. REMOVE

| Item | Reason |
|---|---|
| `AlertRule` engine: `/alerts/rules` GET/POST, `AlertService.create_rule/list_rules` | No evaluator ever reads conditions; no UI |
| `InfrastructureInventory` dashboard widget | 10-row slice of /servers duplicating an existing page |
| "Active Agents"/"Inactive Agents" KPI cards | Restate donut segments already on screen |
| MetricCard dead props `viewAllLabel`/`trendLabel` | No caller passes them |
| `RecentActivityFeed` from dashboard | `/admin/audit` page exists |
| `correlation_state_backend` config knob | Never read |
| `retention.metrics_days` setting | Admitted storage-only no-op |
| `INCIDENT_UPDATED` publish | Zero subscribers |
| Compose "init SQL" comment | File doesn't exist |
| Duplicate color maps ×5, `JOB_STATUS_COLOR` copy, local `formatBytes`, local `RANGES` ×2, `SEVERITY_COLORS` in servers/[id].vue | Consolidate into useSeverity/useJobs/utils |
| Custom SVG `OsDistributionDonut` | Fold into unified DonutCard |
| Topology nav entry | Demoted (decision) — CRUD moves to Settings → Infrastructure |
| docker-compose comment claiming chunk interval | Vestigial |

## D. MERGE

| Into | What |
|---|---|
| **Incidents page** | Signals (secondary tab), legacy Alerts (transition tab until convergence), correlation-rules editor (behind ⚙ dialog) |
| **Events page** | OTLP log viewing (already `source=otel` events); add time-range + severity + host_id filters repo already supports |
| **Overview composite endpoint** | 11 dashboard calls → 1 aggregated `GET /dashboard/overview` + trends + 2 module calls |
| One `DonutCard` | AgentStatus/VulnSeverity/Compliance/OsDistribution donuts (~80% identical markup) |
| One `publish_event()` helper | events.py:74 + otlp.py:55 duplication |
| Shared fingerprint function | Fixes M1 by construction |

## E. SIMPLIFY

- **Overview** → status-first layout. No chart wall.
- **Events page** → stream explorer: `[search] [time ▾] [source ▾] [severity ▾]` + virtualized rows; slide-over panel instead of `<details>`-per-row.
- **Alerts page** (transitional) → add status/severity selects + real cursor pagination.
- **Server detail** → shared severity colors, shared formatBytes; keep text-metric cards.
- Nav: 6 entries → 3 (`Overview`, `Incidents`, `Events`) + Settings→Infrastructure.
- `GET /dashboard/summary` → extend into overview composite with Redis cache (15s).

## F. REBUILD

1. **`CriticalIssues` card** replacing misnamed ActiveIncidents: each row = Problem → Impact → Root signal → Actions [View Host] [Investigate] [Run Runbook].
2. **Overview data layer**: `GET /api/v1/dashboard/overview` — status verdict + counts + critical issues + fleet health + event rate; single query batch, Redis 15s, frontend poll 30s.
3. **Signals suppression** → durable: upsert respects SUPPRESSED (doesn't reset/publish); suppress writes evaluator-consulted state.
4. **Redis error semantics**: `set_nx`/`zadd` distinguish infra-error from miss; on infra error pass through (dedup best-effort); correlation errors logged loudly.

## G. KEEP

NATS→worker pipeline shape; ClickHouse TTLs (30d/90d/180d); `EventIn` validation strictness (whitelist sources, clock-skew, size caps); parameterized ClickHouse queries (no injection found); GZip middleware; global rate-limit concept; CursorPage convention; correlation ZSET windowing design; RBAC on all other mutations; product principle "heartbeat latency is honest".

---

## H. Target Architecture

```
Backend
  Ingest:  POST /events · POST /otlp/v1/{logs,traces}   (shared publish_event + masking + caps)
  Stream:  NATS → EventProcessor → SignalProcessor → CorrelationWorker → IncidentWorker
  Stores:  ClickHouse (events 30d, occurrences 90d, evidence 180d)
           Postgres   (signals, incidents, alerts[legacy→drained], agent_health[+retention])
           Redis      (dedup, windows, caches)
  Reads:   GET /dashboard/overview      ← ONE composite, cached 15s   [NEW]
           GET /incidents[/id][/evidence] · /signals · /events(+since/until/severity)
           GET /servers/{id}/metrics[/history]                        [history NEW, P3]
           GET /alerts                ← read-only shim until drained
  Removed: /alerts/rules, INCIDENT_UPDATED, dead knobs

Frontend nav
  Observability:  Overview(/) · Incidents(/incidents: tabs Incidents|Signals|Alerts†, ⚙ rules)
                  Events(/events: stream+logs)
  Settings → Infrastructure: Topology CRUD, Correlation defaults    († transitional)
```

---

## I. Target UX

```
OBSERVABILITY — OVERVIEW                              ⟳ 30s   [7d|30d|90d]
┌──────────────────────────────────────────────────────────────┐
│ ● WARNING — 1 critical incident, 2 hosts late heartbeat      │
├──────────┬───────────┬────────────┬─────────────────────────┤
│ Hosts    │ Incidents │ Open       │ Events/hr               │
│ 124  ▁▂▃ │ 1    ▂    │ signals 7  │ 15.2k  err 0.4%         │
├──────────┴───────────┴────────────┴─────────────────────────┤
│ CRITICAL ISSUES                                              │
│ 🔴 api-prod-03 · CPU >95% for 8 min            started 12:34 │
│    impact: latency +38% · cause: java 94%                    │
│    [View Host] [Investigate] [Run Runbook]                   │
│ 🟡 db-prod-02 · Disk 87% …                                   │
├──────────────────────────────────────────────────────────────┤
│ Fleet: avg CPU 41% · mem 63% · 2 agents late │ Running jobs 2 │
└──────────────────────────────────────────────────────────────┘
```

5-10 second answers: healthy? what's wrong? impact? cause? act now — one page, one request, progressive disclosure everywhere else. Desktop-first; mobile = status banner + critical list (CSS-only collapse).

---

## J. Performance Plan

**Backend**
1. SignalProcessor: match event type against detector registry before session checkout (H3).
2. Heartbeat fanout: gate `host.heartbeat.ok` emission (resolve via Redis flag, not SELECT) (H4).
3. `agent_health`: Timescale compression @3d + retention @14d; daily rollup (H5, C1 partial).
4. IncidentWorker sweep → single EXISTS-subquery UPDATE; add LIMIT (M4).
5. retention_cleanup → chunked deletes (M3); alerts → CursorPage; incidents/timeline → cap 200.
6. Summary/overview → Redis TTL 15s; reuse shared count services (prevent definition drift).
7. Partial unique index `(tenant_id, group_key) WHERE status='OPEN'` (M5).

**Frontend**
1. Dashboard: 11 calls → overview(1) + trends(1) + vulns/compliance modules(2) ≈ 4.
2. Events stream: lightweight virtual list (>100 rows), server-side filtering only.
3. Kill per-widget fetch boilerplate triplication (dashboard.ts:104-158) → one generic loader.
4. Bundle: no new deps; Unovis retained; @vue-flow untouched.

---

## K. Security Plan

| Sev | Fix | Where |
|---|---|---|
| HIGH | Recursive secret masking at ingest: keys matching `password|passwd|secret|token|authorization|cookie|private_key|api_key` → `"***"` (irreversible by design) | events/schemas.py, otlp/translate.py |
| MED-HIGH | `maintenance` → `require_role("ADMIN","OPERATOR")` | servers.py:229 |
| MED | Redis dedup fail-open on infra error (availability over perfect dedup; JetStream replays cover gaps); correlation errors surfaced | cache.py, event_processor.py |
| MED | OTLP: cap records/request (1000) + enforce payload ceiling pre-fanout | otlp.py |
| MED | Decide rate-limit posture: fail-closed for ingest, fail-open acceptable for reads — document either way | rate_limit.py |
| LOW | Service-account identity for ingestion (separate from user sessions) — P3; tenant predicates on detail-fetches — P3 hygiene | events.py:42, various `_get_or_404` |

---

## FAZA 0 — P0: Securitate & Integritate (~1-2 zile)

### 0.1 Mascarea secretelor la ingest (C2 — HIGH)

**Fișiere:** `backend/lokilinux/events/schemas.py`, `backend/lokilinux/otlp/translate.py`, `backend/tests/unit/test_events_schemas.py` (nou)

**Pași:**
1. Utilitar recursiv de mascare în `events/schemas.py`:
```python
import re

_SECRET_KEY_RE = re.compile(
    r"(password|passwd|secret|token|authorization|cookie|private_key|api_key|credential)",
    re.IGNORECASE,
)
_MASK = "***"

def _mask_value(value):
    if isinstance(value, dict):
        return {k: _MASK if _SECRET_KEY_RE.search(k) else _mask_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_value(v) for v in value]
    return value
```
2. Leagă-l în `EventIn` ca validator pe `payload` (înainte de cel de mărime):
```python
@field_validator("payload")
@classmethod
def _mask_secrets(cls, v: dict[str, Any]) -> dict[str, Any]:
    return _mask_value(v)   # ireversibil prin design
```
3. OTLP acoperit automat: `translate.py` construiește `EventIn(payload=...)` → validatorul rulează la ingest.
4. Test unitar:
```python
def test_payload_secrets_masked():
    ev = EventIn(source="agent", type="otel.log",
                 payload={"body": "login", "headers": {"Authorization": "Bearer x", "ok": 1}})
    assert ev.payload["headers"]["Authorization"] == "***"
    assert ev.payload["headers"]["ok"] == 1
```

**Verificare:** `uv run pytest backend/tests/unit -k schemas`; POST /events cu payload conținând `password`; GET /events returnează `***`.
**Impact:** zero leakage spre orice rol autentificat; cost O(mărimea payload-ului) o singură dată la ingest.

### 0.2 RBAC maintenance (H2 — fix de 2 linii)

**Fișier:** `backend/lokilinux/api/v1/routers/servers.py:229`

```python
# ÎNAINTE
async def set_maintenance(..., current_user: dict = Depends(get_current_user)) -> dict:

# DUPĂ
from lokilinux.auth.dependencies import require_role
async def set_maintenance(..., current_user: dict = Depends(require_role("ADMIN", "OPERATOR"))) -> dict:
```

**Verificare:** test integrare — VIEWER primește 403 pe `POST /servers/{id}/maintenance`.
**Impact:** VIEWER nu mai poate ascunde fleet-ul de alerting.

### 0.3 Semantica erorilor Redis (C3 — CRITICAL)

**Fișiere:** `backend/lokilinux/cache.py`, `backend/lokilinux/workers/event_processor.py`, `backend/lokilinux/workers/correlation_worker.py`

Problemă: `cache.py:157` `set_nx` întoarce `False` la orice eroare Redis → `event_processor.py:66` tratează infra-failure ca „duplicate" și aruncă evenimentul.

**Pași:**
1. Distinge miss de eroare — ridică excepția, nu o înghite:
```python
# cache.py — ÎNAINTE
async def set_nx(self, key: str, ttl: int) -> bool:
    try:
        return bool(await self._redis.set(key, "1", nx=True, ex=ttl))
    except Exception:
        logger.error("cache.set_nx_failed", key=key, exc_info=True)
        return False          # ← BUG: infra-error arată ca "deja văzut"

# DUPĂ
class CacheUnavailableError(RuntimeError): ...

async def set_nx(self, key: str, ttl: int) -> bool | None:
    """True=first-seen, False=duplicate, None=infra error (best-effort)."""
    try:
        return bool(await self._redis.set(key, "1", nx=True, ex=ttl))
    except Exception as exc:
        raise CacheUnavailableError(str(exc)) from exc
```
2. În `event_processor.py`: la eroare → procesează în continuare:
```python
try:
    first = await self.cache.set_nx(dedup_key, ttl=300)
except CacheUnavailableError:
    logger.warning("event.dedup_unavailable_processing_anyway", event_id=...)
    first = True
if first is False:
    continue  # duplicat real
```
3. La fel pentru `zadd`/`zrangebyscore` în `correlation_worker`: eroare → log error + skip ciclu (nu window-goalire silențioasă).
4. `incr` rămâne fail-open (rate limit) — documentat explicit.

**Verificare:** test cu redis mock care ridică excepție → evenimentul tot ajunge în buffer; logs conțin `dedup_unavailable`.
**Impact:** zero pierdere de date silentioasă în outage-uri Redis.

### 0.4 Unificarea fingerprint-ului (M1 — correctness bug)

**Fișier:** `backend/lokilinux/incidents/service.py:67`

Problemă: `upsert_signal` calculează fingerprint cu `detected.resource`; `_resolve_member_signals` fără → `compliance.violation` nu e găsit.

**Fix robust — interoghează după `(tenant, type, host_id)` în loc de fingerprint IN:**
```python
async def _resolve_member_signals(self, candidate, tenant_id) -> list[Signal]:
    host_uuid = _safe_uuid(candidate.group_values.get("host_id") or None)
    rows = (
        await self.db.execute(
            select(Signal).where(
                Signal.tenant_id == tenant_id,
                Signal.type.in_(candidate.member_types),
                Signal.host_id == host_uuid if host_uuid else Signal.host_id.is_(None),
            )
        )
    ).scalars().all()
    return list(rows)
```
(Adaugă index `(tenant_id, type, host_id)` pe `signals` în migrație dacă nu există.)

**Verificare:** test unitar — incident din `compliance.violation` găsește semnalul; auto-resolve funcționează.
**Impact:** semnalele cu resursă participă corect la ciclul incident.

### 0.5 Cap batch OTLP (M6)

**Fișier:** `backend/lokilinux/api/v1/routers/otlp.py:79`

```python
_MAX_RECORDS = 1000
total = sum(len(rl.log_records) for rl in request.resource_logs)
if total > _MAX_RECORDS:
    raise HTTPException(413, f"{total} records exceeds {_MAX_RECORDS} per request")
```
(la fel pentru traces). **Impact:** blochează amplificarea unu-la-mii de mesaje NATS per request.

**Gate Faza 0:** toate testele unit+integration trec; chaos-test manual: `docker stop redis` → evenimente tot curg.

---

## FAZA 1 — P1: Consolidare UX (~3-4 zile)

### 1.1 Endpoint agregat `GET /dashboard/overview` (H6)

**Fișiere:** `backend/lokilinux/api/v1/routers/dashboard.py`, `backend/lokilinux/schemas/dashboard.py`

**Pași:**
1. Extinde pattern-ul din `summary`, dar: (a) adaugă surse pipeline-ul nou (incidents, signals), (b) cache Redis 15s.
2. Schema:
```python
class CriticalIssue(BaseModel):
    kind: str            # "incident" | "signal" | "alert"
    ref_id: str
    severity: str
    title: str
    entity: str | None   # hostname / service
    started_at: datetime
    cause: str | None    # root signal / top proces
    actions: list[str]   # ["view_host","investigate","run_runbook"]

class OverviewResponse(BaseModel):
    status: str                              # HEALTHY | WARNING | CRITICAL
    counts: dict[str, int]                   # hosts_total, hosts_down, incidents_open, signals_open, alerts_active
    critical_issues: list[CriticalIssue]     # max 10
    fleet_health: FleetHealthSnapshot        # avg cpu/mem, late heartbeats
    event_rate: dict[str, float]             # last_hour, error_pct
```
3. Status: `CRITICAL` dacă incident OPEN CRITICAL sau ≥N hosts down; `WARNING` dacă orice open warning; altfel `HEALTHY`.
4. Refolosește aceleași funcții de serviciu ca routerele individuale (evită drift — `dashboard.py:53`). Event rate: o interogare CH `SELECT count(), countIf(severity='ERROR') FROM events WHERE timestamp > now()-3600s`.

**Verificare:** curl endpoint → <150ms cald (cache).
**Impact:** 11 cereri → 1; pagina principală vede pipeline-ul nou.

### 1.2 Rebuild pagină Overview

**Fișiere:** `frontend/pages/index.vue`, `frontend/components/dashboard/CriticalIssues.vue` (nou), `frontend/composables/usePoll.ts` (nou)

**Pași:**
1. Composable de polling reutilizabil:
```ts
export function usePoll(fn: () => Promise<void>, ms: number) {
  let t: ReturnType<typeof setInterval> | undefined
  onMounted(() => { fn(); t = setInterval(fn, ms) })
  onUnmounted(() => clearInterval(t))
  document.addEventListener('visibilitychange', () =>
    document.hidden ? clearInterval(t) : (fn(), (t = setInterval(fn, ms))))
}
```
2. `CriticalIssues.vue`:
```html
<div v-for="issue in issues" :key="issue.ref_id" class="border rounded p-3">
  <Badge :color="severityColor(issue.severity)">{{ issue.severity }}</Badge>
  <span class="font-medium">{{ issue.entity }}</span> — {{ issue.title }}
  <p class="text-xs text-muted-foreground" v-if="issue.cause">cauză: {{ issue.cause }}</p>
  <div class="flex gap-2 mt-2">
    <Button v-if="issue.actions.includes('view_host')" size="sm" variant="outline"
      @click="navigateTo(`/servers/${issue.entity_id}`)">View Host</Button>
    <Button v-if="issue.kind === 'incident'" size="sm"
      @click="navigateTo(`/incidents/${issue.ref_id}`)">Investigate</Button>
  </div>
</div>
```
3. Layout: banner status → 4 count-carduri → CriticalIssues → fleet health + jobs. Fără InfrastructureInventory, Active/Inactive Agents, RecentActivityFeed.
4. Șterge din `stores/dashboard.ts`: `loadActiveIncidents`, `loadInventory`, boilerplate triplat (:104-158).

**Verificare:** ≤4 cereri la mount; refresh automat la 30s.
**Impact:** răspuns la cele 5 întrebări operaționale într-un singur ecran.

### 1.3 Restructurare navigație

**Fișier:** `frontend/layouts/default.vue:388-395`

```ts
// ÎNAINTE (6 intrări)
{ to: '/alerts', ... }, { to: '/incidents', ... }, { to: '/signals', ... },
{ to: '/events', ... }, { to: '/topology', ... }, { to: '/correlation', ... },

// DUPĂ (3)
{ to: '/',          label: 'Overview',  icon: Gauge },
{ to: '/incidents', label: 'Incidents', icon: Siren },
{ to: '/events',    label: 'Events',    icon: Activity },
```
Rute vechi primesc redirect (Nuxt routeRules / pagini-substitute).

### 1.4 Pagina Incidents cu tab-uri

**Fișiere:** `frontend/pages/incidents/index.vue`, componente tab extrase

Structură: `Incidents | Signals | Alerts†` + buton ⚙ (dialog reguli corelație).
- Tab Signals = conținutul actual `signals/index.vue`.
- Tab Alerts† = conținutul actual `alerts/index.vue` — tranzitoriu până la Faza 3.
- Mută markup în `IncidentsTable.vue` / `SignalsTable.vue` / `AlertsTable.vue`; zero logică nouă.

### 1.5 Rebuild Events (stream explorer)

**Backend** (`routers/events.py:81`): expune ce repository-ul suportă deja (`repository.py:135`):
```python
since: datetime | None = None, until: datetime | None = None,
severity: str | None = None, host_id: str | None = None,
```
**Frontend** (`pages/events/index.vue`): bară `[search type] [time ▾] [source ▾] [severity ▾]`; rânduri virtualizate (`content-visibility: auto` + fereastră 200 rânduri); panou slide-over cu payload (înlocuiește `<details>`); **fix bug cursor**: `watch(filters, () => { cursor.value = null })` înainte de refresh.

**Verificare:** filtru 15m+ERROR+nginx sub 300ms; Load-more nu amestecă cursor vechi.
**Impact:** explorer-ul devine unealta reală „ce s-a întâmplat înainte".

### 1.6 Ștergeri frontend (mecanic, o PR separată)

Lista exactă din §C: `InfrastructureInventory.vue`, cardurile Active/Inactive Agents, props moarte MetricCard, `RecentActivityFeed` din index, hărțile de culori duplicate (consolidate în `useSeverity`/`useJobs`), `formatBytes` local din MetricsCards, `RANGES` locale ×2, `OsDistributionDonut` → `DonutCard` unificat.

### 1.7 Fix trunchiere servers

`pages/servers/index.vue`: trece cursorul din store + buton „Load more"; badge-ul `{n} servers` folosește `total`.

**Gate Faza 1:** LCP egal sau mai bun; grep `setInterval` în pages = doar usePoll; rutele vechi redirectuiesc.

---

## FAZA 2 — P1: Performanță Backend (~2-3 zile)

### 2.1 Pre-filtrare în SignalProcessor (H3)

**Fișier:** `backend/lokilinux/workers/signal_processor.py:76`

```python
# ÎNAINTE: sesiune deschisă pentru ORICE mesaj
async def _process(self, msg):
    async with self.db_factory() as db:
        ...

# DUPĂ
_DB_TYPES = {"host.unreachable", "host.heartbeat.ok", "metric.sample", "job.failed",
             "compliance.drift.detected"}
async def _process(self, msg):
    evt = json.loads(msg.data)
    if evt["type"] not in _DB_TYPES:
        return                               # majoritatea mesajelor: zero DB
```
Pentru `host.heartbeat.ok` (cel mai frecvent): verifică mai întâi flag-ul Redis `sig:down:{host}`; absent → return fără sesiune DB.

**Impact:** checkout pgBouncer scade cu ~80-90% la volum tipic.

### 2.2 Reducerea fanout-ului per heartbeat (H4)

**Fișier:** `backend/lokilinux/api/grpc/agent_service.py:285`
1. `host.heartbeat.ok` emis condiționat (doar dacă există flag `sig:down:{host}`).
2. `metric.sample` rămâne per beat, dar fără sesiune DB (asigurat de 2.1).

### 2.3 Retenție `agent_health` (H5 + C1 parțial)

**Migrație Alembic nouă:**
```sql
SELECT add_compression_policy('agent_health', INTERVAL '3 days');
SELECT add_retention_policy('agent_health', INTERVAL '14 days');

CREATE MATERIALIZED VIEW agent_health_daily AS
SELECT agent_id, time_bucket('1 day', time) AS day,
       avg(cpu_percent) cpu, avg(mem_percent) mem, avg(disk_percent) disk, avg(load_1) load1
FROM agent_health GROUP BY agent_id, day;
CREATE INDEX ON agent_health_daily (agent_id, day DESC);
SELECT add_retention_policy('agent_health_daily', INTERVAL '365 days');
```
**Impact:** tabel bounded; fundația pentru `GET /servers/{id}/metrics/history` (Faza 4).

### 2.4 Sweep fără N+1 (M4)

`backend/lokilinux/workers/incident_worker.py:118`:
```sql
UPDATE incidents i SET status='RESOLVED', resolved_at=now()
WHERE i.status IN ('OPEN','ACKNOWLEDGED')
  AND NOT EXISTS (
    SELECT 1 FROM incident_signals is_
    JOIN signals s ON s.id = is_.signal_id
    WHERE is_.incident_id = i.id
      AND (s.status <> 'RESOLVED' OR s.last_seen > now() - interval '600 seconds'))
RETURNING i.id;
```
Apoi timeline-entry + publish pentru ID-urile returnate. Adaugă `LIMIT 500`.

### 2.5 Retenție pe bucăți (M3)

`workers/retention_cleanup.py:46`:
```python
while True:
    result = await db.execute(text("""
        DELETE FROM audit_logs WHERE id IN (
            SELECT id FROM audit_logs WHERE created_at < :cutoff LIMIT 5000)
    """), {"cutoff": cutoff})
    if result.rowcount < 5000: break
    await asyncio.sleep(0.5)
```

### 2.6 Alerts pe CursorPage (L3)

`services/alert_service.py:132` — keyset `(triggered_at, id)`; router primește `cursor`; `AlertsTable` capătă Load more.

### 2.7 Supresie durabilă (M2)

`signals/service.py` upsert:
```python
set_={
    ...,
    "status": case((Signal.status == "SUPPRESSED", "SUPPRESSED"), else_="OPEN"),
}
# + după RETURNING: dacă row.status == "SUPPRESSED": skip publish SIGNAL_DETECTED
```

### 2.8 Index unic incident deschis (M5)

Migrație: `CREATE UNIQUE INDEX uq_incident_open_group ON incidents(tenant_id, group_key) WHERE status IN ('OPEN','ACKNOWLEDGED');` + `open_from_candidate` prinde `UniqueViolation` → ramura „existing".

**Gate Faza 2:** sesiuni DB/sec ↓≥60%; sweep = 1 query; `agent_health` stagnează.

---

## FAZA 3 — P2: Convergență & Curățenie (~2-3 zile)

### 3.1 Elimină dublul de alerte host-down (H1)
`incidents/service.py:157-166` — șterge bridge-ul `AlertService.create_alert("Incident: ...")`.

### 3.2 Migrează producătorii legacy → signals
`workers/heartbeat_monitor.py` + `alert_processor.py`: AGENT_UNHEALTHY publică `EVENT_RAW.agent` cu `type=host.unreachable` în loc de scriere directă în `alerts`. La fel pentru CVE/POLICY/JOB_FAILED pe măsură ce atingem fiecare producător.

### 3.3 Scoate motorul AlertRule
Șterge `routers/alerts.py:69-92`, `AlertService.create_rule/list_rules`; DROP pe `alert_rules` după 1 release cu deprecație.

### 3.4 Drainează + pensionează `/alerts`
Pagina Alerts† din tab dispare, rută → redirect `/incidents`. Tabelul `alerts` read-only până la migrația de drop.

### 3.5 Topology → Settings
Mută `pages/topology/index.vue` → `pages/admin/infrastructure/topology.vue`; completează `tenant_id` pe `TopologyEdge`.

### 3.6 Curățenie finală
Șterge: `correlation_state_backend`, `retention.metrics_days`, publish `INCIDENT_UPDATED` fără subscriber (păstrează doar RESOLVED), comentariul init-SQL din compose, docstring JWKS învechit, `NoOpIncidentSink` dacă rămâne neutilizat. PATCH corelație → semantică parțială sau PUT.

**Gate Faza 3:** `grep -r AlertRule backend/ --include="*.py" | grep -v alembic` = gol; flux unic de alertare; nav 3 intrări observability.

---

## FAZA 4 — P3 Backlog

1. `GET /servers/{id}/metrics/history?range=` din `agent_health_daily` + sparkline pe server detail.
2. Contoare pipeline: agregare Redis sau Prometheus scrape (elimină flapping-ul per-worker).
3. Service accounts pentru ingest.
4. JetStream replay efectiv sau renunțare la streams.
5. Praguri detector + mărimi buffer → settings.
6. SSE pentru Overview — doar dacă polling-ul 30s e insuficient.

---

## Ordine & dependențe

```
F0 (0.1→0.5 independent, fiecare o PR) ──► F1 (1.1 backend primul, apoi 1.2-1.7)
                                        └─► F2 (independent de F1, poate rula paralel)
F1+F2 ──► F3 (convergența atinge frontend+backend simultan)
```

Teste de regresie existente la fiecare pas: `test_signal_service.py`, `test_incident_service.py`, `test_alerts_router.py`, `test_dashboard_router.py`, `test_signals_router.py`, `test_incidents_router.py` + teste noi per task.

---

```
LOKILINUX OBSERVABILITY

Overview · Incidents · Events
Simple. Fast. Operational. Enterprise.
```
