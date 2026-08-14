export type VulnerabilitySeverity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
export type VulnerabilityStatus = 'OPEN' | 'PATCH_AVAILABLE' | 'IN_PROGRESS' | 'MITIGATED' | 'RESOLVED' | 'ACCEPTED_RISK'

export interface Cve {
  id: number
  cve_id: string
  title: string | null
  description: string | null
  cvss_v3_score: number | null
  cvss_v3_severity: VulnerabilitySeverity | null
  published_date: string | null
  is_actively_exploited: boolean
  is_zero_day: boolean
  affected_packages: Record<string, unknown> | null
  affected_count: number
}

export interface CveSummary {
  CRITICAL: number
  HIGH: number
  MEDIUM: number
  LOW: number
}

export interface Vulnerability {
  id: number
  agent_id: string
  hostname: string | null
  cve_id: string
  package_name: string
  package_version: string
  fixed_version: string | null
  cvss_score: number | null
  severity: VulnerabilitySeverity | null
  fix_available: boolean
  is_remediated: boolean
  status: VulnerabilityStatus
  discovered_at: string
  last_scan_at: string | null
}

export interface VulnerabilitySummary {
  resources_scanned: number
  resources_total: number
  critical: number
  high: number
  medium: number
  low: number
  critical_delta_pct: number | null
  high_delta_pct: number | null
  medium_delta_pct: number | null
}

export interface VulnerabilityTrendPoint {
  day: string
  critical: number
  high: number
  medium: number
  low: number
}

export interface TopVulnerableResource {
  agent_id: string
  hostname: string | null
  environment: string | null
  project: string | null
  os_distro: string | null
  os_version: string | null
  critical: number
  high: number
  medium: number
  low: number
  total: number
}

export interface PatchableVulnerability {
  cve_id: string
  cvss_v3_score: number | null
  cvss_v3_severity: VulnerabilitySeverity | null
  package_name: string
  fixed_version: string | null
  affected_count: number
}

export interface VulnerabilityResourceDetail {
  agent_id: string
  hostname: string | null
  ip: string | null
  os_distro: string | null
  os_version: string | null
  package_name: string
  package_version: string
  fixed_version: string | null
  environment: string | null
  project: string | null
  last_scan_at: string | null
  status: VulnerabilityStatus
}

export const useVulnerabilitiesStore = defineStore('vulnerabilities', () => {
  const api = useApi()

  // ── Catalog list ─────────────────────────────────────────────────────────
  const cves = ref<Cve[]>([])
  const cvesTotal = ref(0)
  const cvesLoading = ref(false)
  const cvesNextCursor = ref<string | null>(null)
  const cveFilters = ref({ severity: '', search: '', exploited_only: false })
  // ponytail: only the filters list_vulnerabilities actually accepts today
  // (severity/search/exploited_only/agent_id). status/package/environment/
  // os filters are a real gap in the backend — extend this + the endpoint
  // together when that's prioritized, not the frontend alone.

  async function fetchCves(cursor?: string) {
    cvesLoading.value = true
    try {
      const params = new URLSearchParams()
      if (cursor) params.set('cursor', cursor)
      if (cveFilters.value.severity) params.set('severity', cveFilters.value.severity)
      if (cveFilters.value.search) params.set('search', cveFilters.value.search)
      if (cveFilters.value.exploited_only) params.set('exploited_only', 'true')

      const data = await api.get<{ items: Cve[]; next_cursor: string | null; total: number; summary: CveSummary }>(
        `/vulnerabilities?${params}`,
      )
      if (cursor) {
        cves.value = [...cves.value, ...data.items]
      } else {
        cves.value = data.items
      }
      cvesTotal.value = data.total ?? 0
      cvesNextCursor.value = data.next_cursor
      if (data.summary) cveSummaryBySeverity.value = data.summary
    } catch {
      // swallow — global onResponseError already surfaces a toast; keep last-known-good list
    } finally {
      cvesLoading.value = false
    }
  }

  const cveSummaryBySeverity = ref<CveSummary>({ CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 })

  // ── CVE detail ───────────────────────────────────────────────────────────
  const selectedCve = ref<Cve | null>(null)
  const selectedCveResources = ref<VulnerabilityResourceDetail[]>([])

  async function fetchCve(cveId: string) {
    selectedCve.value = await api.get<Cve>(`/vulnerabilities/${cveId}`)
  }

  async function fetchCveResources(cveId: string) {
    selectedCveResources.value = await api.get<VulnerabilityResourceDetail[]>(`/vulnerabilities/${cveId}/resources`)
  }

  // ── Overview dashboard ───────────────────────────────────────────────────
  const summary = ref<VulnerabilitySummary | null>(null)
  const summaryLoading = ref(false)
  const trend = ref<VulnerabilityTrendPoint[]>([])
  const trendLoading = ref(false)
  const trendRange = ref('30d')
  const topResources = ref<TopVulnerableResource[]>([])
  const topResourcesLoading = ref(false)
  const patchable = ref<PatchableVulnerability[]>([])
  const patchableLoading = ref(false)

  async function fetchSummary() {
    summaryLoading.value = true
    try {
      summary.value = await api.get<VulnerabilitySummary>('/vulnerabilities/summary')
    } catch {
      // swallow — global onResponseError already surfaces a toast
    } finally {
      summaryLoading.value = false
    }
  }

  async function fetchTrend(range?: string) {
    if (range) trendRange.value = range
    trendLoading.value = true
    try {
      trend.value = await api.get<VulnerabilityTrendPoint[]>(`/vulnerabilities/trend?range=${trendRange.value}`)
    } catch {
      // swallow
    } finally {
      trendLoading.value = false
    }
  }

  async function fetchTopResources(limit = 10) {
    topResourcesLoading.value = true
    try {
      topResources.value = await api.get<TopVulnerableResource[]>(`/vulnerabilities/top-resources?limit=${limit}`)
    } catch {
      // swallow
    } finally {
      topResourcesLoading.value = false
    }
  }

  async function fetchPatchable(limit = 10) {
    patchableLoading.value = true
    try {
      patchable.value = await api.get<PatchableVulnerability[]>(`/vulnerabilities/patchable?limit=${limit}`)
    } catch {
      // swallow
    } finally {
      patchableLoading.value = false
    }
  }

  // ── Remediation ──────────────────────────────────────────────────────────

  async function remediateCve(cveId: string, body: { agent_ids?: string[]; maintenance_window_id?: string; is_emergency?: boolean }) {
    return await api.post(`/vulnerabilities/${cveId}/remediate`, body)
  }

  async function acceptRisk(cveId: string, body: { reason: string; until?: string; agent_ids?: string[] }) {
    const resources = await api.post<VulnerabilityResourceDetail[]>(`/vulnerabilities/${cveId}/accept-risk`, body)
    selectedCveResources.value = resources
    return resources
  }

  async function rescanCve(cveId: string, agentIds?: string[]) {
    return await api.post<{ agents_queued: number }>(`/vulnerabilities/${cveId}/rescan`, { agent_ids: agentIds })
  }

  return {
    cves, cvesTotal, cvesLoading, cvesNextCursor, cveFilters, cveSummaryBySeverity, fetchCves,
    selectedCve, selectedCveResources, fetchCve, fetchCveResources,
    summary, summaryLoading, trend, trendLoading, trendRange, fetchSummary, fetchTrend,
    topResources, topResourcesLoading, fetchTopResources,
    patchable, patchableLoading, fetchPatchable,
    remediateCve, acceptRisk, rescanCve,
  }
})
