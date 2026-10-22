export interface CorrelationCondition {
  signal: string
  weight: number
}

export interface CorrelationRule {
  id: string
  tenant_id: string
  name: string
  enabled: boolean
  window_seconds: number
  group_by: string[]
  conditions: CorrelationCondition[]
  threshold_score: number
  incident_type: string
  incident_severity: string
  // Maintenance windows. The API used to hide them, so every save sent an
  // empty list back and wiped the operator's suppressions.
  suppressions: Array<Record<string, unknown>>
  version: number
  created_at: string
}

export interface CorrelationRuleInput {
  name: string
  enabled: boolean
  window_seconds: number
  group_by: string[]
  conditions: CorrelationCondition[]
  threshold_score: number
  incident_type: string
  incident_severity: string
  suppressions?: Array<Record<string, unknown>>
}

export const useCorrelationStore = defineStore('correlation', () => {
  const api = useApi()

  const rules = ref<CorrelationRule[]>([])
  const loading = ref(false)

  async function fetchRules() {
    loading.value = true
    try {
      rules.value = await api.get<CorrelationRule[]>('/correlation/rules')
    } catch {
      // swallow — global onResponseError already surfaces a toast
    } finally {
      loading.value = false
    }
  }

  async function createRule(payload: CorrelationRuleInput): Promise<CorrelationRule> {
    const rule = await api.post<CorrelationRule>('/correlation/rules', payload)
    rules.value.unshift(rule)
    return rule
  }

  async function updateRule(id: string, payload: CorrelationRuleInput): Promise<CorrelationRule> {
    const updated = await api.patch<CorrelationRule>(`/correlation/rules/${id}`, payload)
    const idx = rules.value.findIndex((r) => r.id === id)
    if (idx !== -1) rules.value[idx] = updated
    return updated
  }

  async function deleteRule(id: string) {
    await api.del(`/correlation/rules/${id}`)
    rules.value = rules.value.filter((r) => r.id !== id)
  }

  async function toggleEnabled(rule: CorrelationRule) {
    await updateRule(rule.id, {
      name: rule.name, enabled: !rule.enabled, window_seconds: rule.window_seconds,
      group_by: rule.group_by, conditions: rule.conditions, threshold_score: rule.threshold_score,
      incident_type: rule.incident_type, incident_severity: rule.incident_severity,
      // Round-trip the suppressions: the API only writes the fields it is
      // sent, but dropping them here would still clear the operator's
      // maintenance windows on every toggle.
      suppressions: rule.suppressions ?? [],
    })
  }

  return { rules, loading, fetchRules, createRule, updateRule, deleteRule, toggleEnabled }
})
