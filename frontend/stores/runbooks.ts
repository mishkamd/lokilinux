export interface Runbook {
  id: string
  tenant_id: string
  name: string
  incident_type: string
  workflow_id: string | null
  trigger_mode: 'MANUAL' | 'AUTO'
  min_severity: string
  enabled: boolean
  created_at: string
}

export interface RunbookInput {
  name: string
  incident_type: string
  workflow_id: string | null
  trigger_mode: 'MANUAL' | 'AUTO'
  min_severity: string
  enabled: boolean
}

export const useRunbooksStore = defineStore('runbooks', () => {
  const api = useApi()

  const runbooks = ref<Runbook[]>([])
  const loading = ref(false)

  async function fetchRunbooks() {
    loading.value = true
    try {
      runbooks.value = await api.get<Runbook[]>('/runbooks')
    } catch {
      // swallow — global onResponseError already surfaces a toast
    } finally {
      loading.value = false
    }
  }

  async function createRunbook(payload: RunbookInput): Promise<Runbook> {
    const runbook = await api.post<Runbook>('/runbooks', payload)
    runbooks.value.unshift(runbook)
    return runbook
  }

  async function updateRunbook(id: string, payload: RunbookInput): Promise<Runbook> {
    const updated = await api.patch<Runbook>(`/runbooks/${id}`, payload)
    const idx = runbooks.value.findIndex((r) => r.id === id)
    if (idx !== -1) runbooks.value[idx] = updated
    return updated
  }

  async function deleteRunbook(id: string) {
    await api.del(`/runbooks/${id}`)
    runbooks.value = runbooks.value.filter((r) => r.id !== id)
  }

  async function toggleEnabled(runbook: Runbook) {
    await updateRunbook(runbook.id, {
      name: runbook.name, incident_type: runbook.incident_type, workflow_id: runbook.workflow_id,
      trigger_mode: runbook.trigger_mode, min_severity: runbook.min_severity, enabled: !runbook.enabled,
    })
  }

  return { runbooks, loading, fetchRunbooks, createRunbook, updateRunbook, deleteRunbook, toggleEnabled }
})
