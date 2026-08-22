import { useComplianceStore } from './compliance'
import { useVulnerabilitiesStore } from './vulnerabilities'
import { useJobsStore } from './jobs'

export type DashboardRange = '7d' | '30d' | '90d'

export interface DashboardHealth {
  cpu_usage: number | null
  memory_usage: number | null
  disk_usage: number | null
  network_latency_ms: number | null
}

export interface DashboardSummary {
  agents: {
    total: number
    by_status: Record<string, number>
    active: number
    updates_available: number
    os_distribution: Record<string, number>
  }
  vulnerabilities: { unresolved_total: number; by_severity: Record<string, number> }
  jobs: { total: number; by_status: Record<string, number>; running: number }
  alerts: { active_total: number; by_severity: Record<string, number> }
  policies: { total: number; enabled: number }
  plugins: { total: number; enabled: number }
  health: DashboardHealth
}

export interface ServerTrendPoint { day: string; total: number }
export interface JobTrendPoint { day: string; successful: number; failed: number; running: number }
export interface AlertTrendPoint { day: string; created: number; resolved: number }
export interface DashboardVulnerabilityTrendPoint { day: string; critical: number; high: number; medium: number; low: number }

export interface DashboardTrends {
  servers: ServerTrendPoint[]
  vulnerabilities: DashboardVulnerabilityTrendPoint[]
  jobs: JobTrendPoint[]
  alerts: AlertTrendPoint[]
}

export interface RecentFailedJob {
  id: string
  name: string
  job_type: string
  status: string
  completed_at: string | null
}

export interface Alert {
  id: string
  title: string
  description: string | null
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO'
  status: 'ACTIVE' | 'ACKNOWLEDGED' | 'RESOLVED' | 'EXPIRED'
  alert_type: string | null
  agent_id: string | null
  triggered_at: string
  created_at: string
}

export interface InventoryServer {
  id: string
  hostname: string
  os_name: string | null
  status: string
  ip_address: string | null
  category_id: string | null
  last_seen_at: string | null
  cve_count: number
}

export interface RunningJob {
  id: string
  name: string
  job_type: string
  target_servers: { agent_ids: string[] }
  started_at: string | null
  progress: number | null
}

export const useDashboardStore = defineStore('dashboard', () => {
  const api = useApi()

  const summary = ref<DashboardSummary | null>(null)
  const summaryLoading = ref(false)
  const summaryError = ref(false)

  const trends = ref<DashboardTrends | null>(null)
  const trendsLoading = ref(false)
  const trendsError = ref(false)

  const range = ref<DashboardRange>('30d')
  const loaded = ref(false)

  // Own fetch, own state — deliberately not routed through useJobsStore().
  // That store's `jobs` ref is a single shared array also driving /jobs and
  // the server-detail Jobs tab; reusing it here would let this widget's
  // status=FAILED&limit=5 request clobber whatever those pages are showing.
  const recentFailedJobs = ref<RecentFailedJob[]>([])
  const recentFailedJobsLoading = ref(false)
  const recentFailedJobsError = ref(false)

  async function loadRecentFailedJobs() {
    recentFailedJobsLoading.value = true
    recentFailedJobsError.value = false
    try {
      const data = await api.get<{ items: RecentFailedJob[] }>('/jobs?status=FAILED&limit=5')
      recentFailedJobs.value = data.items
    } catch {
      recentFailedJobs.value = []
      recentFailedJobsError.value = true
    } finally {
      recentFailedJobsLoading.value = false
    }
  }

  // Own state too — /alerts?status=ACTIVE is a different query than the
  // alerts page's own (unpaginated, unfiltered) fetch, and duplicating the
  // request here is cheaper than routing this widget's fetch through a page
  // that doesn't expose one.
  const activeIncidents = ref<Alert[]>([])
  const activeIncidentsLoading = ref(false)
  const activeIncidentsError = ref(false)

  async function loadActiveIncidents() {
    activeIncidentsLoading.value = true
    activeIncidentsError.value = false
    try {
      const data = await api.get<{ items: Alert[] }>('/alerts?status=ACTIVE&limit=5')
      activeIncidents.value = data.items
    } catch {
      activeIncidents.value = []
      activeIncidentsError.value = true
    } finally {
      activeIncidentsLoading.value = false
    }
  }

  // Same isolation reasoning as recentFailedJobs — /servers?limit=10 must
  // not clobber the /servers page's own filtered, cursor-paginated list.
  const inventory = ref<InventoryServer[]>([])
  const inventoryLoading = ref(false)
  const inventoryError = ref(false)

  async function loadInventory() {
    inventoryLoading.value = true
    inventoryError.value = false
    try {
      const data = await api.get<{ items: InventoryServer[] }>('/servers?limit=10')
      inventory.value = data.items
    } catch {
      inventory.value = []
      inventoryError.value = true
    } finally {
      inventoryLoading.value = false
    }
  }

  const RESULT_TERMINAL_STATUSES = new Set(['COMPLETED', 'FAILED', 'TIMEOUT', 'CANCELLED'])

  const runningJobs = ref<RunningJob[]>([])
  const runningJobsLoading = ref(false)
  const runningJobsError = ref(false)

  // N+1 by design, tightly bounded: at most 5 jobs (already capped by the
  // list query), fetched in parallel, and only called at all when
  // summary.jobs.running > 0 (see loadOverview) — running jobs are rare, and
  // without per-agent results this widget would show a bare list, no progress.
  async function loadRunningJobs() {
    runningJobsLoading.value = true
    runningJobsError.value = false
    try {
      const data = await api.get<{ items: RunningJob[] }>('/jobs?status=RUNNING&limit=5')
      const jobsStore = useJobsStore()
      runningJobs.value = await Promise.all(data.items.map(async (job) => {
        const total = job.target_servers.agent_ids.length
        if (total === 0) return { ...job, progress: null }
        try {
          const results = await jobsStore.fetchJobResults(job.id)
          const done = results.filter((r) => RESULT_TERMINAL_STATUSES.has(r.status)).length
          return { ...job, progress: Math.round((done / total) * 100) }
        } catch {
          return { ...job, progress: null }
        }
      }))
    } catch {
      runningJobs.value = []
      runningJobsError.value = true
    } finally {
      runningJobsLoading.value = false
    }
  }

  async function loadSummary() {
    summaryLoading.value = true
    summaryError.value = false
    try {
      summary.value = await api.get<DashboardSummary>('/dashboard/summary')
    } catch {
      summaryError.value = true
    } finally {
      summaryLoading.value = false
    }
  }

  async function loadTrends() {
    trendsLoading.value = true
    trendsError.value = false
    try {
      trends.value = await api.get<DashboardTrends>(`/dashboard/trends?range=${range.value}`)
    } catch {
      trendsError.value = true
    } finally {
      trendsLoading.value = false
    }
  }

  /** Changes the period filter for every trend-driven widget on the page —
   * this store's own /dashboard/trends plus the sibling stores that already
   * own their own ranged trend endpoints, so the filter is real (a fresh
   * request per range), not just a relabeled selector. */
  async function setRange(next: DashboardRange) {
    if (range.value === next) return
    range.value = next
    const compliance = useComplianceStore()
    compliance.trendRange = next
    await Promise.all([
      loadTrends(),
      compliance.fetchTrend(),
    ])
  }

  /** Loads everything the (single) dashboard view needs, once — repeat
   * calls are a no-op unless `force` (used by error-state Retry). */
  async function loadOverview(force = false) {
    if (loaded.value && !force) return
    loaded.value = true

    const vulnerabilities = useVulnerabilitiesStore()
    const compliance = useComplianceStore()

    const tasks: Promise<unknown>[] = []
    tasks.push(!summary.value || force ? loadSummary() : Promise.resolve())
    if (!trends.value || force) tasks.push(loadTrends())

    tasks.push(vulnerabilities.fetchTopResources())
    tasks.push(vulnerabilities.fetchPatchable(), loadRecentFailedJobs())

    tasks.push(compliance.fetchOverview())
    tasks.push(compliance.fetchTrend())
    tasks.push(loadActiveIncidents())
    tasks.push(loadInventory())

    await Promise.all(tasks)

    // Gated on the just-loaded summary — running jobs are rare, so most
    // loads skip the N+1 progress fetch entirely (see loadRunningJobs).
    if ((summary.value?.jobs.running ?? 0) > 0) {
      await loadRunningJobs()
    } else {
      runningJobs.value = []
    }
  }

  /** Cheap, cross-page load for the topbar's status/critical pills — just
   * /dashboard/summary (60s server-side cache), not the full loadOverview
   * fan-out. No-op once summary is already populated by either path. */
  async function ensureSummary() {
    if (summary.value) return
    await loadSummary()
  }

  return {
    summary, summaryLoading, summaryError, loadSummary, ensureSummary,
    trends, trendsLoading, trendsError, loadTrends,
    recentFailedJobs, recentFailedJobsLoading, recentFailedJobsError,
    activeIncidents, activeIncidentsLoading, activeIncidentsError,
    inventory, inventoryLoading, inventoryError,
    runningJobs, runningJobsLoading, runningJobsError,
    range, setRange,
    loadOverview,
  }
})
