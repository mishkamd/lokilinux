import { useComplianceStore } from './compliance'
import { useVulnerabilitiesStore } from './vulnerabilities'

export type DashboardRange = '7d' | '30d' | '90d'
export type DashboardTab = 'overview' | 'infrastructure' | 'security' | 'automation' | 'compliance' | 'observability'

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

export const useDashboardStore = defineStore('dashboard', () => {
  const api = useApi()

  const summary = ref<DashboardSummary | null>(null)
  const summaryLoading = ref(false)
  const summaryError = ref(false)

  const trends = ref<DashboardTrends | null>(null)
  const trendsLoading = ref(false)
  const trendsError = ref(false)

  const range = ref<DashboardRange>('30d')
  const loadedTabs = ref(new Set<DashboardTab>())

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
    const vulnerabilities = useVulnerabilitiesStore()
    const compliance = useComplianceStore()
    compliance.trendRange = next
    await Promise.all([
      loadTrends(),
      vulnerabilities.fetchTrend(next),
      compliance.fetchTrend(),
    ])
  }

  /** Lazily loads whatever a tab needs, once — repeat visits to an already
   * loaded tab are a no-op unless `force` (used by error-state Retry). */
  async function loadTab(tab: DashboardTab, force = false) {
    if (loadedTabs.value.has(tab) && !force) return
    loadedTabs.value.add(tab)

    const vulnerabilities = useVulnerabilitiesStore()
    const compliance = useComplianceStore()

    const tasks: Promise<unknown>[] = []
    if (!summary.value || force) tasks.push(loadSummary())
    if (!trends.value || force) tasks.push(loadTrends())

    if (tab === 'overview' || tab === 'security') {
      tasks.push(vulnerabilities.fetchSummary(), vulnerabilities.fetchTopResources())
      if (!vulnerabilities.trend.length || force) tasks.push(vulnerabilities.fetchTrend(range.value))
    }
    if (tab === 'overview' || tab === 'compliance') {
      tasks.push(compliance.fetchOverview())
      if (!compliance.trend.length || force) tasks.push(compliance.fetchTrend())
    }

    await Promise.all(tasks)
  }

  return {
    summary, summaryLoading, summaryError, loadSummary,
    trends, trendsLoading, trendsError, loadTrends,
    range, setRange,
    loadTab,
  }
})
