<!-- generated-by: claude -->
# Frontend — Nuxt 4 / Vue 3 Page Structure

Confirmed by exploration: this is **Nuxt 4 + Vue 3.5 + Pinia**, not React — the brief's
"React + shadcn/ui + TanStack" describes a stack this repo doesn't have. UI primitives are a
hand-rolled shadcn-*style* component set (`radix-vue` + `cva` + `clsx`/`tailwind-merge`), not
the shadcn CLI/registry, living under `components/ui/*.vue`, auto-imported unprefixed. There is
no TanStack Query/Table — data fetching is `useApi()` + Pinia setup-stores, and there is no
charting library at all (existing charts are hand-rolled inline SVG). All of this section
follows those real conventions, not the brief's assumed stack.

## 1. Pages (file-based routing, `pages/` at repo root — Nuxt 4 v3-compatibility layout, no `app/` dir)

```
pages/compliance/
├── index.vue                 → /compliance                (fleet overview: scores, top violations, heatmap)
├── baselines/
│   ├── index.vue             → /compliance/baselines       (list + scope tree filter)
│   └── [id].vue               → /compliance/baselines/:id  (versions, approval workflow, diff viewer)
├── policies/
│   ├── index.vue             → /compliance/policies        (policy sets, import from ComplianceAsCode)
│   └── [id].vue               → /compliance/policies/:id   (rules in set, coverage %, edit)
├── rules/index.vue           → /compliance/rules            (searchable rule catalog, framework filter)
├── drift/
│   ├── index.vue             → /compliance/drift            (drift event list, severity/domain filters)
│   └── [id].vue               → /compliance/drift/:id       (field-level diff, root cause, ack, create plan)
├── file-integrity/index.vue  → /compliance/file-integrity   (per-agent FIM browser)
├── remediation/
│   ├── index.vue             → /compliance/remediation      (plan list, approval queue)
│   └── [id].vue               → /compliance/remediation/:id (actions, provider output, rollback)
├── reports/index.vue         → /compliance/reports          (generate/download)
└── assistant.vue             → /compliance/assistant        (AI chat-style Q&A, per-subject context panel)
```

No `definePageMeta` needed on any of these — route protection is already global
(`middleware/auth.global.ts`), so new pages inherit auth automatically, matching every existing
page except `pages/admin/audit.vue` and `pages/auth/login.vue`.

Nav entry added to the `navSections` computed in `layouts/default.vue` — a new `{ title:
'Compliance', links: [...] }` section (matching how `Automation Engine` groups its own pages),
so `currentPageTitle` derives the header text automatically the way it already does everywhere.

## 2. Store — `stores/compliance.ts` (matches `stores/cve.ts` shape exactly)

```ts
export interface DriftEvent {
  id: string
  agent_id: string
  domain: string
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  change_type: string
  summary: string
  acknowledged_at: string | null
  time: string
}

export interface ComplianceScore {
  category: 'overall' | 'security' | 'configuration' | 'filesystem' | 'packages' | 'kernel'
  score: number
  trend: number
}

export const useComplianceStore = defineStore('compliance', () => {
  const api = useApi()

  const driftEvents = ref<DriftEvent[]>([])
  const total = ref(0)
  const loading = ref(false)
  const fleetScores = ref<ComplianceScore[]>([])
  const filters = ref({ severity: '', domain: '', acknowledged: '' })

  async function fetchDriftEvents(cursor?: string) {
    loading.value = true
    try {
      const params = new URLSearchParams()
      if (cursor) params.set('cursor', cursor)
      if (filters.value.severity) params.set('severity', filters.value.severity)
      if (filters.value.domain) params.set('domain', filters.value.domain)
      const data = await api.get<{ items: DriftEvent[]; next_cursor: string | null; total: number }>(
        `/compliance/drift-events?${params}`,
      )
      driftEvents.value = data.items
      total.value = data.total
    } finally {
      loading.value = false
    }
  }

  async function fetchFleetScores() {
    fleetScores.value = await api.get<ComplianceScore[]>('/compliance/scores/fleet')
  }

  async function acknowledgeDrift(id: string) {
    await api.post(`/compliance/drift-events/${id}/acknowledge`)
    const idx = driftEvents.value.findIndex((e) => e.id === id)
    if (idx !== -1) driftEvents.value[idx] = { ...driftEvents.value[idx], acknowledged_at: new Date().toISOString() }
  }

  return { driftEvents, total, loading, fleetScores, filters, fetchDriftEvents, fetchFleetScores, acknowledgeDrift }
})
```

Same rules as every existing store: setup-store syntax, `useApi()` at the top, paths relative
to `/api/v1`, mutations patch the local array in place instead of refetching, types exported
for pages to import.

## 3. Representative page — `pages/compliance/drift/index.vue`

Matches the "summary cards + filters + DataTable + Dialog" shape of `pages/vulnerabilities/index.vue`
exactly — same primitives, same slot pattern, nothing invented:

```vue
<script setup lang="ts">
import { RefreshCw } from 'lucide-vue-next'

const store = useComplianceStore()
const { driftEvents, total, loading, filters } = storeToRefs(store)
const { canEdit } = useCurrentUser()

onMounted(() => store.fetchDriftEvents())

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'red', HIGH: 'red', MEDIUM: 'amber', LOW: 'gray',
}

const columns = [
  { key: 'time', label: 'Detected' },
  { key: 'agent_id', label: 'Server' },
  { key: 'domain', label: 'Domain' },
  { key: 'severity', label: 'Severity' },
  { key: 'change_type', label: 'Change' },
  { key: 'acknowledged_at', label: 'Status' },
]
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div class="flex flex-wrap items-center gap-3">
        <Select v-model="filters.severity" :options="['', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW']"
                placeholder="Severity" class="w-36" @change="store.fetchDriftEvents()" />
        <Button variant="outline" @click="store.fetchDriftEvents()">
          <RefreshCw class="size-4" /> Refresh
        </Button>
      </div>
      <Badge color="gray">{{ total }} drift events</Badge>
    </div>

    <DataTable :rows="driftEvents" :columns="columns" :loading="loading" rows-clickable
               @row-click="(row) => navigateTo(`/compliance/drift/${row.id}`)">
      <template #severity-data="{ row }">
        <Badge :color="SEVERITY_COLORS[String(row.severity)] ?? 'gray'" size="xs">{{ row.severity }}</Badge>
      </template>
      <template #acknowledged_at-data="{ row }">
        <Badge v-if="row.acknowledged_at" color="green" size="xs">Acknowledged</Badge>
        <Button v-else-if="canEdit" size="xs" variant="ghost" @click.stop="store.acknowledgeDrift(String(row.id))">
          Acknowledge
        </Button>
        <span v-else class="text-muted-foreground text-sm">Open</span>
      </template>
    </DataTable>
  </div>
</template>
```

Note `SEVERITY_COLORS` uses `amber` for MEDIUM — that variant doesn't exist on `Badge` today
(only `red`/`green`/`gray`), so this module's frontend work includes extending
`components/ui/Badge.vue`'s `COLOR` map with `amber`/`orange` (D9) rather than overloading
`gray` for a medium-severity finding, which would read as "no severity" to an operator.

## 4. Charts — the one new dependency

No chart library exists (`frontend/package.json` has none; existing dashboard visuals are
hand-rolled inline SVG in `components/dashboard/OsDistributionDonut.vue` /
`SeverityBarList.vue`). The brief asks for heatmaps, trend lines, a risk matrix, and a
drift/audit timeline — beyond what hand-rolled SVG comfortably scales to. **`@unovis/vue`** is
added (Vue-native, tree-shakeable, no bundled CSS framework, composes with existing Tailwind
tokens via CSS variables) for exactly these four visuals:

```
components/compliance/
├── ComplianceHeatmap.vue      # datacenter x category grid, cell color from --chart-1..5 tokens
├── ComplianceTrendChart.vue   # unovis Line — fleet score over time, reads compliance_scores_daily
├── RiskMatrix.vue             # unovis Scatter — severity x blast-radius
└── DriftTimeline.vue          # unovis Timeline — drift_events for one agent, chronological
```

Everything else (score tiles, top-violations list, coverage bars) reuses the existing
`StatCard`/`SeverityBarList`-style hand-rolled components — the new dependency is scoped to
the four visuals that genuinely need a real charting engine, not adopted wholesale.

## 5. Detail page — `AppTabs` pattern (matches `pages/servers/[id].vue`'s 7-tab shape)

```vue
<!-- pages/compliance/baselines/[id].vue (excerpt) -->
<script setup lang="ts">
const route = useRoute()
const baseline = ref<Baseline | null>(null)
const tabs = [
  { label: 'Versions', slot: 'versions' },
  { label: 'Effective Preview', slot: 'preview' },
  { label: 'Approval History', slot: 'approvals' },
]
async function onTabChange(index: number) {
  // lazy per-tab fetch, same pattern as the server detail page
}
</script>
<template>
  <AppTabs :items="tabs" @change="onTabChange">
    <template #versions>...</template>
    <template #preview>...</template>
    <template #approvals>...</template>
  </AppTabs>
</template>
```

## 6. Test

`stores/compliance.test.ts` follows the exact `mockNuxtImport('useApi', ...)` +
`setActivePinia(createPinia())` pattern already used in `stores/servers.test.ts` — no new test
infrastructure needed, `vitest.config.ts` (`environment: 'nuxt'`) already covers it.
