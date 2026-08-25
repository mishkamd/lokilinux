export interface IncidentSignal {
  id: string
  tenant_id: string
  type: string
  severity: string
  status: string
  host_id: string | null
  service: string | null
  fingerprint: string
  occurrence_count: number
  first_seen: string
  last_seen: string
}

export interface IncidentTimelineEntry {
  id: string
  ts: string
  kind: string
  message: string
  payload: Record<string, unknown>
}

export interface Incident {
  id: string
  tenant_id: string
  title: string
  type: string
  severity: string
  status: 'OPEN' | 'ACKNOWLEDGED' | 'IN_PROGRESS' | 'RESOLVED' | 'CLOSED'
  root_cause_signal_id: string | null
  confidence: number | null
  group_key: string | null
  started_at: string
  updated_at: string
  resolved_at: string | null
  acknowledged_at: string | null
}

export interface IncidentDetail extends Incident {
  signals: IncidentSignal[]
  timeline: IncidentTimelineEntry[]
}

export interface IncidentEvidenceItem {
  timestamp: string
  tenant: string
  incident_id: string
  kind: string
  ref: string
  summary: string
}

export const useIncidentsStore = defineStore('incidents', () => {
  const api = useApi()

  const incidents = ref<Incident[]>([])
  const total = ref(0)
  const loading = ref(false)
  const nextCursor = ref<string | null>(null)
  const filters = ref({ status: '', severity: '', type: '' })

  async function fetchIncidents(cursor?: string) {
    loading.value = true
    try {
      const params = new URLSearchParams()
      if (cursor) params.set('cursor', cursor)
      if (filters.value.status) params.set('status', filters.value.status)
      if (filters.value.severity) params.set('severity', filters.value.severity)
      if (filters.value.type) params.set('type', filters.value.type)

      const data = await api.get<{ items: Incident[]; next_cursor: string | null; total: number | null }>(
        `/incidents?${params}`,
      )
      incidents.value = cursor ? [...incidents.value, ...data.items] : data.items
      total.value = data.total ?? incidents.value.length
      nextCursor.value = data.next_cursor
    } catch {
      // swallow — global onResponseError already surfaces a toast; keep last-known-good list
    } finally {
      loading.value = false
    }
  }

  function loadMore() {
    if (nextCursor.value) return fetchIncidents(nextCursor.value)
  }

  async function fetchIncident(id: string): Promise<IncidentDetail> {
    return await api.get<IncidentDetail>(`/incidents/${id}`)
  }

  async function fetchEvidence(id: string): Promise<IncidentEvidenceItem[]> {
    const data = await api.get<{ items: IncidentEvidenceItem[] }>(`/incidents/${id}/evidence`)
    return data.items
  }

  function _replaceInList(updated: Incident) {
    const idx = incidents.value.findIndex((i) => i.id === updated.id)
    if (idx !== -1) incidents.value[idx] = updated
  }

  async function ackIncident(id: string): Promise<Incident> {
    const updated = await api.post<Incident>(`/incidents/${id}/ack`)
    _replaceInList(updated)
    return updated
  }

  async function resolveIncident(id: string): Promise<Incident> {
    const updated = await api.post<Incident>(`/incidents/${id}/resolve`)
    _replaceInList(updated)
    return updated
  }

  async function reopenIncident(id: string): Promise<Incident> {
    const updated = await api.post<Incident>(`/incidents/${id}/reopen`)
    _replaceInList(updated)
    return updated
  }

  return {
    incidents, total, loading, nextCursor, filters,
    fetchIncidents, loadMore, fetchIncident, fetchEvidence,
    ackIncident, resolveIncident, reopenIncident,
  }
})
