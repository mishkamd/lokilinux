import { useComplianceStore } from './compliance'
import { useVulnerabilitiesStore } from './vulnerabilities'

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
    if (!summary.value || force) tasks.push(loadSummary())
    if (!trends.value || force) tasks.push(loadTrends())

    tasks.push(vulnerabilities.fetchTopResources())
    tasks.push(vulnerabilities.fetchPatchable(), loadRecentFailedJobs())

    tasks.push(compliance.fetchOverview())

    await Promise.all(tasks)
  }

  return {
    summary, summaryLoading, summaryError, loadSummary,
    trends, trendsLoading, trendsError, loadTrends,
    recentFailedJobs, recentFailedJobsLoading, recentFailedJobsError,
    range, setRange,
    loadOverview,
  }
})
