export type ScopeType = 'GLOBAL' | 'OS' | 'ROLE' | 'ENVIRONMENT' | 'DATACENTER' | 'CLUSTER' | 'APPLICATION'
export type BaselineVersionStatus = 'DRAFT' | 'PENDING_APPROVAL' | 'APPROVED' | 'PUBLISHED' | 'DEPRECATED'

export interface Baseline {
  id: string
  name: string
  description: string | null
  scope_type: ScopeType
  scope_selector: Record<string, unknown>
  parent_baseline_id: string | null
  is_enabled: boolean
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface BaselineVersion {
  id: string
  baseline_id: string
  version: number
  status: BaselineVersionStatus
  expected_state: Record<string, unknown>
  content_hash: string
  signed_by: string | null
  change_summary: string | null
  created_by: string | null
  created_at: string
  published_at: string | null
  deprecated_at: string | null
}

export interface InventorySnapshot {
  id: string
  agent_id: string
  domain: string
  content_hash: string
  taken_at: string
  facts: Record<string, unknown> | null
}

export interface InventoryDelta {
  time: string
  agent_id: string
  domain: string
  prev_hash: string | null
  new_hash: string
  diff: Record<string, unknown> | null
}

export const useComplianceStore = defineStore('compliance', () => {
  const api = useApi()

  const baselines = ref<Baseline[]>([])
  const baselinesTotal = ref(0)
  const baselinesLoading = ref(false)
  const baselinesNextCursor = ref<string | null>(null)
  const baselineFilters = ref({ scope_type: '' })

  const selectedBaseline = ref<Baseline | null>(null)
  const versions = ref<BaselineVersion[]>([])
  const versionsLoading = ref(false)

  async function fetchBaselines(cursor?: string) {
    baselinesLoading.value = true
    try {
      const params = new URLSearchParams()
      if (cursor) params.set('cursor', cursor)
      if (baselineFilters.value.scope_type) params.set('scope_type', baselineFilters.value.scope_type)

      const data = await api.get<{ items: Baseline[]; next_cursor: string | null; total: number }>(
        `/compliance/baselines?${params}`,
      )
      baselines.value = data.items
      baselinesTotal.value = data.total ?? 0
      baselinesNextCursor.value = data.next_cursor
    } finally {
      baselinesLoading.value = false
    }
  }

  async function createBaseline(body: {
    name: string
    description?: string
    scope_type: ScopeType
    scope_selector: Record<string, unknown>
    expected_state: Record<string, unknown>
  }) {
    const baseline = await api.post<Baseline>('/compliance/baselines', body)
    baselines.value = [baseline, ...baselines.value]
    return baseline
  }

  async function fetchBaseline(id: string) {
    selectedBaseline.value = await api.get<Baseline>(`/compliance/baselines/${id}`)
  }

  async function fetchVersions(baselineId: string) {
    versionsLoading.value = true
    try {
      versions.value = await api.get<BaselineVersion[]>(`/compliance/baselines/${baselineId}/versions`)
    } finally {
      versionsLoading.value = false
    }
  }

  async function createVersion(baselineId: string, body: { expected_state: Record<string, unknown>; change_summary?: string }) {
    const version = await api.post<BaselineVersion>(`/compliance/baselines/${baselineId}/versions`, body)
    versions.value = [version, ...versions.value]
    return version
  }

  function _patchVersion(updated: BaselineVersion) {
    const idx = versions.value.findIndex((v: BaselineVersion) => v.id === updated.id)
    if (idx !== -1) versions.value[idx] = updated
    else versions.value = [updated, ...versions.value]
  }

  async function submitVersion(baselineId: string, versionId: string) {
    _patchVersion(await api.post<BaselineVersion>(`/compliance/baselines/${baselineId}/versions/${versionId}/submit`))
  }

  async function approveVersion(baselineId: string, versionId: string) {
    _patchVersion(await api.post<BaselineVersion>(`/compliance/baselines/${baselineId}/versions/${versionId}/approve`))
  }

  async function publishVersion(baselineId: string, versionId: string) {
    _patchVersion(await api.post<BaselineVersion>(`/compliance/baselines/${baselineId}/versions/${versionId}/publish`))
  }

  async function rollbackVersion(baselineId: string, versionId: string) {
    _patchVersion(await api.post<BaselineVersion>(`/compliance/baselines/${baselineId}/versions/${versionId}/rollback`))
  }

  // ── Inventory ────────────────────────────────────────────────────────────

  const inventorySnapshot = ref<InventorySnapshot | null>(null)
  const inventorySnapshotError = ref<string | null>(null)
  const inventoryHistory = ref<InventoryDelta[]>([])
  const inventoryLoading = ref(false)

  async function fetchInventorySnapshot(agentId: string, domain: string) {
    inventoryLoading.value = true
    inventorySnapshotError.value = null
    inventorySnapshot.value = null
    try {
      inventorySnapshot.value = await api.get<InventorySnapshot>(`/compliance/agents/${agentId}/inventory/${domain}`)
    } catch (err) {
      inventorySnapshotError.value = 'No snapshot found for this agent/domain yet.'
    } finally {
      inventoryLoading.value = false
    }
  }

  async function fetchInventoryHistory(agentId: string, domain: string) {
    const data = await api.get<{ items: InventoryDelta[]; next_cursor: string | null; total: number }>(
      `/compliance/agents/${agentId}/inventory/${domain}/history`,
    )
    inventoryHistory.value = data.items
  }

  return {
    baselines, baselinesTotal, baselinesLoading, baselinesNextCursor, baselineFilters,
    selectedBaseline, versions, versionsLoading,
    fetchBaselines, createBaseline, fetchBaseline, fetchVersions, createVersion,
    submitVersion, approveVersion, publishVersion, rollbackVersion,
    inventorySnapshot, inventorySnapshotError, inventoryHistory, inventoryLoading,
    fetchInventorySnapshot, fetchInventoryHistory,
  }
})
