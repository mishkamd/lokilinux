export type CveSeverity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'NONE'

export interface Cve {
  cve_id: string
  description: string | null
  cvss_v3_score: number | null
  cvss_v3_severity: CveSeverity | null
  published_date: string | null
  is_actively_exploited: boolean
  is_zero_day: boolean
  affected_count: number // servers affected, returned by API summary
}

export interface CveSummary {
  CRITICAL: number
  HIGH: number
  MEDIUM: number
  LOW: number
}

export const useCveStore = defineStore('cve', () => {
  const api = useApi()

  const cves = ref<Cve[]>([])
  const total = ref(0)
  const loading = ref(false)
  const summary = ref<CveSummary>({ CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 })
  const filters = ref({ severity: '', search: '', exploited_only: false })

  async function fetchCves(cursor?: string) {
    loading.value = true
    try {
      const params = new URLSearchParams()
      if (cursor) params.set('cursor', cursor)
      if (filters.value.severity) params.set('severity', filters.value.severity)
      if (filters.value.search) params.set('search', filters.value.search)
      if (filters.value.exploited_only) params.set('exploited_only', 'true')

      const data = await api.get<{ items: Cve[]; next_cursor: string | null; total: number; summary: CveSummary }>(
        `/vulnerabilities?${params}`,
      )
      cves.value = data.items
      total.value = data.total ?? 0
      if (data.summary) summary.value = data.summary
    } finally {
      loading.value = false
    }
  }

  return { cves, total, loading, summary, filters, fetchCves }
})
