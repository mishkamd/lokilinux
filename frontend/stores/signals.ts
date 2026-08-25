export interface Signal {
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

export const useSignalsStore = defineStore('signals', () => {
  const api = useApi()

  const signals = ref<Signal[]>([])
  const total = ref(0)
  const loading = ref(false)
  const nextCursor = ref<string | null>(null)
  const filters = ref({ status: '', severity: '', type: '', host_id: '' })

  async function fetchSignals(cursor?: string) {
    loading.value = true
    try {
      const params = new URLSearchParams()
      if (cursor) params.set('cursor', cursor)
      if (filters.value.status) params.set('status', filters.value.status)
      if (filters.value.severity) params.set('severity', filters.value.severity)
      if (filters.value.type) params.set('type', filters.value.type)
      if (filters.value.host_id) params.set('host_id', filters.value.host_id)

      const data = await api.get<{ items: Signal[]; next_cursor: string | null; total: number | null }>(
        `/signals?${params}`,
      )
      signals.value = cursor ? [...signals.value, ...data.items] : data.items
      total.value = data.total ?? signals.value.length
      nextCursor.value = data.next_cursor
    } catch {
      // swallow — global onResponseError already surfaces a toast; keep last-known-good list
    } finally {
      loading.value = false
    }
  }

  function loadMore() {
    if (nextCursor.value) return fetchSignals(nextCursor.value)
  }

  function _replaceInList(updated: Signal) {
    const idx = signals.value.findIndex((s) => s.id === updated.id)
    if (idx !== -1) signals.value[idx] = updated
  }

  async function resolveSignal(id: string): Promise<Signal> {
    const updated = await api.post<Signal>(`/signals/${id}/resolve`)
    _replaceInList(updated)
    return updated
  }

  async function suppressSignal(id: string): Promise<Signal> {
    const updated = await api.post<Signal>(`/signals/${id}/suppress`)
    _replaceInList(updated)
    return updated
  }

  return { signals, total, loading, nextCursor, filters, fetchSignals, loadMore, resolveSignal, suppressSignal }
})
