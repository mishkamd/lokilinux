export interface PolicyAction {
  type: string
  params: Record<string, unknown>
}

export interface PolicyExecution {
  requires_approval?: boolean
  timeout_seconds?: number | null
}

export interface PolicyTargetServers {
  all?: boolean
  agent_ids?: string[]
  filters?: {
    os_family?: string
    os_distro?: string
    category_id?: string
    project_id?: string
    status?: string
  }
}

export interface Policy {
  id: string
  name: string
  description: string | null
  policy_type: 'UPDATE' | 'SECURITY' | 'COMPLIANCE' | 'MAINTENANCE' | 'PLUGIN' | null
  rules: Record<string, unknown>
  target_servers: PolicyTargetServers | null
  is_enabled: boolean
  priority: number
  version: number
  created_by: string | null
  created_at: string
  updated_at: string
  trigger_type: 'MANUAL' | 'SCHEDULE'
  cron_expr: string | null
  next_run_at: string | null
  last_run_at: string | null
  actions: PolicyAction[]
  execution: PolicyExecution
  severity: string | null
  tags: string[]
}

export interface PolicyAuditRow {
  id: number
  policy_id: string
  changed_by: string | null
  change_type: string
  old_value: Record<string, unknown> | null
  new_value: Record<string, unknown> | null
  changed_at: string
}

export const usePoliciesStore = defineStore('policies', () => {
  const api = useApi()

  const policies = ref<Policy[]>([])
  const total = ref(0)
  const loading = ref(false)
  const selectedPolicy = ref<Policy | null>(null)
  const filters = ref({ policy_type: '' })

  async function fetchPolicies() {
    loading.value = true
    try {
      const params = new URLSearchParams()
      if (filters.value.policy_type) params.set('policy_type', filters.value.policy_type)
      const data = await api.get<{ items: Policy[]; total: number }>(`/policies?${params}`)
      policies.value = data.items
      total.value = data.total ?? 0
    } finally {
      loading.value = false
    }
  }

  async function fetchPolicy(id: string) {
    selectedPolicy.value = await api.get<Policy>(`/policies/${id}`)
    return selectedPolicy.value
  }

  async function toggleEnabled(policy: Policy) {
    const updated = await api.patch<Policy>(`/policies/${policy.id}`, { is_enabled: !policy.is_enabled })
    const idx = policies.value.findIndex((p) => p.id === policy.id)
    if (idx !== -1) policies.value[idx] = updated
    return updated
  }

  async function runPolicy(id: string) {
    return api.post<{ job_ids: string[]; matched_agents: number }>(`/policies/${id}/run`, {})
  }

  async function deletePolicy(id: string) {
    await api.del(`/policies/${id}`)
    policies.value = policies.value.filter((p) => p.id !== id)
  }

  async function fetchAudit(id: string) {
    return api.get<PolicyAuditRow[]>(`/policies/${id}/audit`)
  }

  return {
    policies, total, loading, selectedPolicy, filters,
    fetchPolicies, fetchPolicy, toggleEnabled, runPolicy, deletePolicy, fetchAudit,
  }
})
