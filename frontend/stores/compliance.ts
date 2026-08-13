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

export type CheckSource = 'CEL' | 'OVAL_UNMAPPED' | 'OSCAP_FALLBACK'

export interface ComplianceRule {
  id: string
  rule_key: string
  title: string
  description: string | null
  rationale: string | null
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  domain: string
  check_source: CheckSource
  check_expr: string | null
  standard_refs: Record<string, string>
  source: string
  source_version: string | null
  is_enabled: boolean
  imported_at: string
}

export interface FrameworkMapping {
  framework_key: string
  framework_name: string
  framework_version: string
  control_id: string
  control_title: string
}

export interface FailingAgent {
  agent_id: string
  hostname: string | null
}

export interface RuleDetail extends ComplianceRule {
  framework_mappings: FrameworkMapping[]
  coverage: Record<string, number>
  failing_agents: FailingAgent[]
}

export interface PolicySet {
  id: string
  name: string
  slug: string
  framework: string
  version: string | null
  description: string | null
  source_profile: string | null
  is_enabled: boolean
  created_at: string
  status: 'DRAFT' | 'PUBLISHED' | 'ARCHIVED'
  published_at: string | null
  published_version: number
  parent_policy_set_id: string | null
}

export interface PolicySetCoverage {
  policy_set_id: string
  mapped: number
  unmapped: number
  coverage_pct: number
}

export interface DriftEvent {
  id: string
  time: string
  agent_id: string
  hostname: string | null
  domain: string
  compared_against: string
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  change_type: string
  summary: string
  root_cause: Record<string, unknown> | null
  acknowledged_by: string | null
  acknowledged_at: string | null
  status: 'OPEN' | 'ACKNOWLEDGED' | 'IN_REMEDIATION' | 'RESOLVED' | 'SUPPRESSED' | 'EXCEPTION'
  occurrences: number
  first_seen: string | null
  last_seen: string | null
  correlation_key: string | null
  resolved_at: string | null
  suppressed_by: string | null
}

export interface DriftDetail {
  drift_event_id: string
  field_path: string
  old_value: unknown
  new_value: unknown
}

export type RemediationPlanStatus = 'DRAFT' | 'PENDING_APPROVAL' | 'APPROVED' | 'EXECUTING' | 'VERIFYING' | 'COMPLETED' | 'FAILED' | 'ROLLED_BACK'

export interface RemediationPlan {
  id: string
  name: string
  status: RemediationPlanStatus
  trigger_type: 'MANUAL' | 'SCHEDULED' | 'AUTOMATIC' | 'AI_SUGGESTED'
  is_emergency: boolean
  maintenance_window_id: string | null
  created_by: string | null
  approved_by: string | null
  approved_at: string | null
  created_at: string
}

export interface RemediationAction {
  id: string
  remediation_plan_id: string
  rule_id: string | null
  drift_event_id: string | null
  agent_id: string
  hostname: string | null
  provider: string
  rendered_body: string
  rollback_body: string | null
  sequence: number
}

export interface MaintenanceWindow {
  id: string
  name: string
  scope_type: string
  scope_selector: Record<string, unknown>
  cron_expr: string | null
  duration_minutes: number
  timezone: string
  is_enabled: boolean
  created_at: string
}

export interface RemediationExecutionResult {
  agent_id: string
  hostname: string | null
  status: string
  exit_code: number | null
  error_message: string | null
  stdout: string | null
  stderr: string | null
  duration_seconds: number | null
}

export interface RemediationExecution {
  job_id: string | null
  operation: 'APPLY' | 'ROLLBACK' | 'DRY_RUN' | null
  job_status: string | null
  results: RemediationExecutionResult[]
}

export interface FileHash {
  agent_id: string
  path: string
  algo: string
  hash: string
  mode: number | null
  uid: number | null
  gid: number | null
  size_bytes: number | null
  mtime: string | null
  updated_at: string
}

export type FileChangeKind = 'CREATED' | 'MODIFIED' | 'DELETED' | 'PERMISSION_CHANGED' | 'OWNER_CHANGED'

export interface FileChange {
  time: string
  agent_id: string
  hostname: string | null
  path: string
  old_hash: string | null
  new_hash: string | null
  change_kind: FileChangeKind
  old_mode: number | null
  new_mode: number | null
  old_uid: number | null
  new_uid: number | null
  old_gid: number | null
  new_gid: number | null
}

export interface RelatedRule {
  rule_id: string
  rule_key: string
  title: string
  domain: string
}

export interface FileChangePathDetail {
  path: string
  servers: FailingAgent[]
  timeline: FileChange[]
  related_rules: RelatedRule[]
  related_drift: DriftEvent[]
}

export type ReportType = 'FLEET_SUMMARY' | 'POLICY_SET' | 'DATACENTER' | 'CUSTOM' | 'FRAMEWORK' | 'EXCEPTION' | 'EXECUTIVE_SUMMARY'
export type ReportFormat = 'JSON' | 'CSV' | 'XLSX' | 'PDF'
export type ReportStatus = 'PENDING' | 'GENERATING' | 'COMPLETED' | 'FAILED'

export interface ComplianceReport {
  id: string
  report_type: ReportType
  format: ReportFormat
  params: Record<string, unknown>
  status: ReportStatus
  artifact_uri: string | null
  error_message: string | null
  generated_by: string | null
  created_at: string
  completed_at: string | null
}

export interface TopViolatingRule {
  rule_id: string
  rule_key: string
  title: string
  domain: string
  severity: string
  fail_count: number
}

export interface TopChangedFile {
  path: string
  change_count: number
}

export interface TopViolations {
  top_rules: TopViolatingRule[]
  recent_drift: DriftEvent[]
}

export interface ComplianceOverview {
  overall_compliance_pct: number
  critical_violations: number
  high_violations: number
  open_drift: number
  active_baselines: number
  enabled_policies: number
  servers_evaluated: number
  servers_non_compliant: number
  exceptions_active: number
}

export interface TrendPoint {
  day: string
  compliance_pct: number
}

export interface ComplianceAssessment {
  id: string
  scope_selector: Record<string, unknown>
  policy_set_id: string | null
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'
  servers_total: number
  servers_done: number
  rules_total: number
  rules_done: number
  created_by: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface ComplianceException {
  id: string
  rule_id: string
  rule_key: string | null
  rule_title: string | null
  agent_id: string | null
  hostname: string | null
  scope_selector: Record<string, unknown>
  reason: string
  owner: string
  requested_by: string | null
  approved_by: string | null
  approved_at: string | null
  status: 'PENDING' | 'ACTIVE' | 'EXPIRED' | 'REVOKED'
  expires_at: string
  created_at: string
  updated_at: string
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
      if (cursor) {
        baselines.value = [...baselines.value, ...data.items]
      } else {
        baselines.value = data.items
      }
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

  // ── Policy Engine ────────────────────────────────────────────────────────

  const rules = ref<ComplianceRule[]>([])
  const rulesTotal = ref(0)
  const rulesLoading = ref(false)
  const rulesNextCursor = ref<string | null>(null)
  const ruleFilters = ref({
    domain: '', check_source: '', severity: '', search: '', framework: '', platform: '', source: '', status: '',
  })
  const selectedRule = ref<RuleDetail | null>(null)

  const policySets = ref<PolicySet[]>([])
  const policySetsTotal = ref(0)
  const policySetsLoading = ref(false)
  const policySetsNextCursor = ref<string | null>(null)
  const selectedPolicySet = ref<PolicySet | null>(null)
  const policySetRules = ref<ComplianceRule[]>([])
  const policySetCoverage = ref<PolicySetCoverage | null>(null)

  async function fetchRules(cursor?: string) {
    rulesLoading.value = true
    try {
      const params = new URLSearchParams()
      if (cursor) params.set('cursor', cursor)
      if (ruleFilters.value.domain) params.set('domain', ruleFilters.value.domain)
      if (ruleFilters.value.check_source) params.set('check_source', ruleFilters.value.check_source)
      if (ruleFilters.value.severity) params.set('severity', ruleFilters.value.severity)
      if (ruleFilters.value.search) params.set('search', ruleFilters.value.search)
      if (ruleFilters.value.framework) params.set('framework', ruleFilters.value.framework)
      if (ruleFilters.value.platform) params.set('platform', ruleFilters.value.platform)
      if (ruleFilters.value.source) params.set('source', ruleFilters.value.source)
      if (ruleFilters.value.status) params.set('status', ruleFilters.value.status)
      const data = await api.get<{ items: ComplianceRule[]; next_cursor: string | null; total: number }>(
        `/compliance/rules?${params}`,
      )
      if (cursor) {
        rules.value = [...rules.value, ...data.items]
      } else {
        rules.value = data.items
      }
      rulesTotal.value = data.total ?? 0
      rulesNextCursor.value = data.next_cursor
    } finally {
      rulesLoading.value = false
    }
  }

  async function fetchRule(id: string) {
    selectedRule.value = await api.get<RuleDetail>(`/compliance/rules/${id}`)
  }

  async function fetchPolicySets(cursor?: string) {
    policySetsLoading.value = true
    try {
      const params = new URLSearchParams()
      if (cursor) params.set('cursor', cursor)
      const data = await api.get<{ items: PolicySet[]; next_cursor: string | null; total: number }>(
        `/compliance/policy-sets?${params}`,
      )
      if (cursor) {
        policySets.value = [...policySets.value, ...data.items]
      } else {
        policySets.value = data.items
      }
      policySetsTotal.value = data.total ?? 0
      policySetsNextCursor.value = data.next_cursor
    } finally {
      policySetsLoading.value = false
    }
  }

  async function createPolicySet(body: { name: string; slug: string; framework: string; version?: string; description?: string }) {
    const policySet = await api.post<PolicySet>('/compliance/policy-sets', body)
    policySets.value = [policySet, ...policySets.value]
    return policySet
  }

  async function fetchPolicySet(id: string) {
    selectedPolicySet.value = await api.get<PolicySet>(`/compliance/policy-sets/${id}`)
  }

  async function fetchPolicySetRules(id: string) {
    policySetRules.value = await api.get<ComplianceRule[]>(`/compliance/policy-sets/${id}/rules`)
  }

  async function fetchPolicySetCoverage(id: string) {
    policySetCoverage.value = await api.get<PolicySetCoverage>(`/compliance/policy-sets/${id}/coverage`)
  }

  async function importPolicySet(body: { source: string; profile_id?: string; content_version: string; datastream_url: string }) {
    return await api.post<{ job_id: string; status: string }>('/compliance/policy-sets/import', body)
  }

  async function publishPolicySet(id: string) {
    const updated = await api.post<PolicySet>(`/compliance/policy-sets/${id}/publish`)
    if (selectedPolicySet.value?.id === id) selectedPolicySet.value = updated
    return updated
  }

  async function archivePolicySet(id: string) {
    const updated = await api.post<PolicySet>(`/compliance/policy-sets/${id}/archive`)
    if (selectedPolicySet.value?.id === id) selectedPolicySet.value = updated
    return updated
  }

  async function newPolicySetVersion(id: string) {
    return await api.post<PolicySet>(`/compliance/policy-sets/${id}/new-version`)
  }

  // ── Drift ────────────────────────────────────────────────────────────────

  const driftEvents = ref<DriftEvent[]>([])
  const driftTotal = ref(0)
  const driftLoading = ref(false)
  const driftNextCursor = ref<string | null>(null)
  const driftFilters = ref({ severity: '', domain: '', acknowledged: '', status: '' })

  const selectedDriftEvent = ref<DriftEvent | null>(null)
  const driftDetails = ref<DriftDetail[]>([])

  async function fetchDriftEvents(cursor?: string) {
    driftLoading.value = true
    try {
      const params = new URLSearchParams()
      if (cursor) params.set('cursor', cursor)
      if (driftFilters.value.severity) params.set('severity', driftFilters.value.severity)
      if (driftFilters.value.domain) params.set('domain', driftFilters.value.domain)
      if (driftFilters.value.acknowledged) params.set('acknowledged', driftFilters.value.acknowledged)
      if (driftFilters.value.status) params.set('status', driftFilters.value.status)
      const data = await api.get<{ items: DriftEvent[]; next_cursor: string | null; total: number }>(
        `/compliance/drift-events?${params}`,
      )
      if (cursor) {
        driftEvents.value = [...driftEvents.value, ...data.items]
      } else {
        driftEvents.value = data.items
      }
      driftTotal.value = data.total ?? 0
      driftNextCursor.value = data.next_cursor
    } finally {
      driftLoading.value = false
    }
  }

  async function fetchDriftEvent(id: string) {
    selectedDriftEvent.value = await api.get<DriftEvent>(`/compliance/drift-events/${id}`)
  }

  async function fetchDriftDetails(id: string) {
    driftDetails.value = await api.get<DriftDetail[]>(`/compliance/drift-events/${id}/details`)
  }

  async function acknowledgeDrift(id: string) {
    const updated = await api.post<DriftEvent>(`/compliance/drift-events/${id}/acknowledge`)
    applyDriftUpdate(id, updated)
  }

  async function suppressDrift(id: string, reason?: string) {
    const updated = await api.post<DriftEvent>(`/compliance/drift-events/${id}/suppress`, { reason: reason ?? null })
    applyDriftUpdate(id, updated)
  }

  async function resolveDrift(id: string) {
    const updated = await api.post<DriftEvent>(`/compliance/drift-events/${id}/resolve`)
    applyDriftUpdate(id, updated)
  }

  function applyDriftUpdate(id: string, updated: DriftEvent) {
    // acknowledge/suppress/resolve responses don't re-join hostname (only
    // status fields change) — keep the row's existing hostname instead of
    // letting the null from `updated` blank it out on a full replace.
    const idx = driftEvents.value.findIndex((e) => e.id === id)
    const existing = idx !== -1 ? driftEvents.value[idx] : undefined
    if (existing) driftEvents.value[idx] = { ...updated, hostname: updated.hostname ?? existing.hostname }
    const selected = selectedDriftEvent.value
    if (selected?.id === id) {
      selectedDriftEvent.value = { ...updated, hostname: updated.hostname ?? selected.hostname }
    }
  }

  // ── Exceptions ───────────────────────────────────────────────────────────

  const exceptions = ref<ComplianceException[]>([])
  const exceptionsTotal = ref(0)
  const exceptionsLoading = ref(false)
  const exceptionsNextCursor = ref<string | null>(null)
  const exceptionFilters = ref({ status: '' })

  async function fetchExceptions(cursor?: string) {
    exceptionsLoading.value = true
    try {
      const params = new URLSearchParams()
      if (cursor) params.set('cursor', cursor)
      if (exceptionFilters.value.status) params.set('status', exceptionFilters.value.status)
      const data = await api.get<{ items: ComplianceException[]; next_cursor: string | null; total: number }>(
        `/compliance/exceptions?${params}`,
      )
      if (cursor) {
        exceptions.value = [...exceptions.value, ...data.items]
      } else {
        exceptions.value = data.items
      }
      exceptionsTotal.value = data.total ?? 0
      exceptionsNextCursor.value = data.next_cursor
    } finally {
      exceptionsLoading.value = false
    }
  }

  async function createException(body: {
    rule_id: string
    reason: string
    owner: string
    expires_at: string
    agent_id?: string
    scope_selector?: Record<string, unknown>
  }) {
    const exc = await api.post<ComplianceException>('/compliance/exceptions', body)
    // refetch instead of unshifting the raw create response — that response has
    // no rule_key/hostname join and would also show up under a status filter
    // it doesn't belong to (a fresh row is always PENDING).
    await fetchExceptions()
    return exc
  }

  async function approveException(id: string) {
    const updated = await api.post<ComplianceException>(`/compliance/exceptions/${id}/approve`)
    applyExceptionUpdate(id, updated)
  }

  async function revokeException(id: string) {
    const updated = await api.post<ComplianceException>(`/compliance/exceptions/${id}/revoke`)
    applyExceptionUpdate(id, updated)
  }

  function applyExceptionUpdate(id: string, updated: ComplianceException) {
    // approve/revoke responses don't re-join rule_key/rule_title/hostname —
    // keep the row's existing values instead of letting the null from
    // `updated` blank them out on a full replace (same fix as applyDriftUpdate).
    const idx = exceptions.value.findIndex((e) => e.id === id)
    const existing = idx !== -1 ? exceptions.value[idx] : undefined
    if (existing) {
      exceptions.value[idx] = {
        ...updated,
        rule_key: updated.rule_key ?? existing.rule_key,
        rule_title: updated.rule_title ?? existing.rule_title,
        hostname: updated.hostname ?? existing.hostname,
      }
    }
  }

  // ── Remediation ──────────────────────────────────────────────────────────

  const remediationPlans = ref<RemediationPlan[]>([])
  const remediationTotal = ref(0)
  const remediationLoading = ref(false)
  const remediationNextCursor = ref<string | null>(null)
  const remediationError = ref<string | null>(null)
  const remediationFilters = ref({ status: '' })

  const selectedRemediationPlan = ref<RemediationPlan | null>(null)
  const remediationActions = ref<RemediationAction[]>([])
  const remediationExecution = ref<RemediationExecution | null>(null)
  const maintenanceWindows = ref<MaintenanceWindow[]>([])

  async function fetchRemediationPlans(cursor?: string) {
    remediationLoading.value = true
    remediationError.value = null
    try {
      const params = new URLSearchParams()
      if (cursor) params.set('cursor', cursor)
      if (remediationFilters.value.status) params.set('status', remediationFilters.value.status)
      const data = await api.get<{ items: RemediationPlan[]; next_cursor: string | null; total: number }>(
        `/compliance/remediation-plans?${params}`,
      )
      if (cursor) {
        remediationPlans.value = [...remediationPlans.value, ...data.items]
      } else {
        remediationPlans.value = data.items
      }
      remediationTotal.value = data.total ?? 0
      remediationNextCursor.value = data.next_cursor
    } catch (err) {
      remediationError.value = 'Failed to load remediation plans'
    } finally {
      remediationLoading.value = false
    }
  }

  function _patchRemediationPlan(updated: RemediationPlan) {
    if (selectedRemediationPlan.value?.id === updated.id) selectedRemediationPlan.value = updated
    const idx = remediationPlans.value.findIndex((p) => p.id === updated.id)
    if (idx !== -1) remediationPlans.value[idx] = updated
    else remediationPlans.value = [updated, ...remediationPlans.value]
  }

  async function fetchRemediationPlan(id: string) {
    selectedRemediationPlan.value = await api.get<RemediationPlan>(`/compliance/remediation-plans/${id}`)
  }

  async function fetchRemediationActions(id: string) {
    remediationActions.value = await api.get<RemediationAction[]>(`/compliance/remediation-plans/${id}/actions`)
  }

  async function createRemediationPlan(body: {
    name: string
    trigger_type?: string
    is_emergency?: boolean
    maintenance_window_id?: string | null
    actions: Array<{
      agent_id: string
      provider: 'ansible' | 'shell' | 'python'
      rendered_body: string
      rollback_body?: string | null
      rule_id?: string | null
      drift_event_id?: string | null
    }>
  }) {
    const plan = await api.post<RemediationPlan>('/compliance/remediation-plans', body)
    remediationPlans.value = [plan, ...remediationPlans.value]
    remediationTotal.value += 1
    return plan
  }

  async function submitRemediationPlan(id: string) {
    const updated = await api.post<RemediationPlan>(`/compliance/remediation-plans/${id}/submit`)
    _patchRemediationPlan(updated)
    return updated
  }

  async function approveRemediationPlan(id: string) {
    const updated = await api.post<RemediationPlan>(`/compliance/remediation-plans/${id}/approve`)
    _patchRemediationPlan(updated)
    return updated
  }

  async function dryRunRemediationPlan(id: string) {
    return await api.post<RemediationPlan>(`/compliance/remediation-plans/${id}/dry-run`)
  }

  async function fetchRemediationExecution(id: string) {
    remediationExecution.value = await api.get<RemediationExecution>(`/compliance/remediation-plans/${id}/execution`)
  }

  async function rollbackRemediationPlan(id: string) {
    _patchRemediationPlan(await api.post<RemediationPlan>(`/compliance/remediation-plans/${id}/rollback`))
  }

  async function fetchMaintenanceWindows() {
    maintenanceWindows.value = await api.get<MaintenanceWindow[]>('/compliance/maintenance-windows')
  }

  async function createMaintenanceWindow(body: {
    name: string
    scope_type?: string
    scope_selector?: Record<string, unknown>
    cron_expr?: string | null
    duration_minutes: number
    timezone?: string
    is_enabled?: boolean
  }) {
    const window = await api.post<MaintenanceWindow>('/compliance/maintenance-windows', body)
    maintenanceWindows.value = [...maintenanceWindows.value, window]
    return window
  }

  // ── File Integrity ───────────────────────────────────────────────────────

  const fileHashes = ref<FileHash[]>([])
  const fileHashesLoading = ref(false)
  const fileHashPathPrefix = ref('')

  const fileChanges = ref<FileChange[]>([])
  const fileChangesTotal = ref(0)
  const fileChangesLoading = ref(false)
  const fileChangesNextCursor = ref<string | null>(null)
  const fileChangeFilters = ref({ agent_id: '', change_kind: '' })

  async function fetchFileHashes(agentId: string) {
    fileHashesLoading.value = true
    try {
      const params = new URLSearchParams()
      if (fileHashPathPrefix.value) params.set('path_prefix', fileHashPathPrefix.value)
      fileHashes.value = await api.get<FileHash[]>(`/compliance/agents/${agentId}/file-hashes?${params}`)
    } finally {
      fileHashesLoading.value = false
    }
  }

  async function fetchFileChanges(cursor?: string) {
    fileChangesLoading.value = true
    try {
      const params = new URLSearchParams()
      if (cursor) params.set('cursor', cursor)
      if (fileChangeFilters.value.agent_id) params.set('agent_id', fileChangeFilters.value.agent_id)
      if (fileChangeFilters.value.change_kind) params.set('change_kind', fileChangeFilters.value.change_kind)
      const data = await api.get<{ items: FileChange[]; next_cursor: string | null; total: number }>(
        `/compliance/file-changes?${params}`,
      )
      if (cursor) {
        fileChanges.value = [...fileChanges.value, ...data.items]
      } else {
        fileChanges.value = data.items
      }
      fileChangesTotal.value = data.total ?? 0
      fileChangesNextCursor.value = data.next_cursor
    } finally {
      fileChangesLoading.value = false
    }
  }

  const fileChangePathDetail = ref<FileChangePathDetail | null>(null)
  const fileChangePathDetailLoading = ref(false)

  async function fetchFileChangesByPath(path: string) {
    fileChangePathDetailLoading.value = true
    try {
      fileChangePathDetail.value = await api.get<FileChangePathDetail>(
        `/compliance/file-changes/by-path?path=${encodeURIComponent(path)}`,
      )
    } finally {
      fileChangePathDetailLoading.value = false
    }
  }

  // ── Reporting Engine ─────────────────────────────────────────────────────

  const reports = ref<ComplianceReport[]>([])
  const reportsTotal = ref(0)
  const reportsLoading = ref(false)
  const reportsNextCursor = ref<string | null>(null)

  async function fetchReports(cursor?: string) {
    reportsLoading.value = true
    try {
      const params = new URLSearchParams()
      if (cursor) params.set('cursor', cursor)
      const data = await api.get<{ items: ComplianceReport[]; next_cursor: string | null; total: number }>(
        `/compliance/reports?${params}`,
      )
      if (cursor) {
        reports.value = [...reports.value, ...data.items]
      } else {
        reports.value = data.items
      }
      reportsTotal.value = data.total ?? 0
      reportsNextCursor.value = data.next_cursor
    } finally {
      reportsLoading.value = false
    }
  }

  async function createReport(body: { report_type: ReportType; format: ReportFormat; params?: Record<string, unknown> }) {
    const report = await api.post<ComplianceReport>('/compliance/reports', body)
    reports.value = [report, ...reports.value]
    return report
  }

  // ── Dashboard widgets ────────────────────────────────────────────────────

  const topViolations = ref<TopViolations>({ top_rules: [], recent_drift: [] })
  const topViolationsLoading = ref(false)
  const topChangedFiles = ref<TopChangedFile[]>([])
  const topChangedFilesLoading = ref(false)

  async function fetchTopViolations() {
    topViolationsLoading.value = true
    try {
      topViolations.value = await api.get<TopViolations>('/compliance/dashboard/top-violations')
    } finally {
      topViolationsLoading.value = false
    }
  }

  async function fetchTopChangedFiles() {
    topChangedFilesLoading.value = true
    try {
      topChangedFiles.value = await api.get<TopChangedFile[]>('/compliance/dashboard/top-changed-files')
    } finally {
      topChangedFilesLoading.value = false
    }
  }

  const overview = ref<ComplianceOverview | null>(null)
  const overviewLoading = ref(false)

  async function fetchOverview() {
    overviewLoading.value = true
    try {
      overview.value = await api.get<ComplianceOverview>('/compliance/overview')
    } finally {
      overviewLoading.value = false
    }
  }

  const trend = ref<TrendPoint[]>([])
  const trendLoading = ref(false)
  const trendRange = ref<'7d' | '30d' | '90d' | '1y'>('30d')

  async function fetchTrend() {
    trendLoading.value = true
    try {
      trend.value = await api.get<TrendPoint[]>(`/compliance/trend?range=${trendRange.value}`)
    } finally {
      trendLoading.value = false
    }
  }

  const assessments = ref<ComplianceAssessment[]>([])
  const assessmentsLoading = ref(false)

  async function fetchAssessments() {
    assessmentsLoading.value = true
    try {
      const data = await api.get<{ items: ComplianceAssessment[]; next_cursor: string | null; total: number }>(
        '/compliance/assessments?limit=5',
      )
      assessments.value = data.items
    } finally {
      assessmentsLoading.value = false
    }
  }

  async function createAssessment(body: { policy_set_id: string; scope_selector?: Record<string, unknown> }) {
    const created = await api.post<ComplianceAssessment>('/compliance/assessments', body)
    assessments.value = [created, ...assessments.value]
    return created
  }

  async function fetchAssessment(id: string) {
    const updated = await api.get<ComplianceAssessment>(`/compliance/assessments/${id}`)
    const idx = assessments.value.findIndex((a) => a.id === id)
    if (idx !== -1) assessments.value[idx] = updated
    return updated
  }

  return {
    baselines, baselinesTotal, baselinesLoading, baselinesNextCursor, baselineFilters,
    selectedBaseline, versions, versionsLoading,
    fetchBaselines, createBaseline, fetchBaseline, fetchVersions, createVersion,
    submitVersion, approveVersion, publishVersion, rollbackVersion,
    inventorySnapshot, inventorySnapshotError, inventoryHistory, inventoryLoading,
    fetchInventorySnapshot, fetchInventoryHistory,
    rules, rulesTotal, rulesLoading, rulesNextCursor, ruleFilters, fetchRules,
    selectedRule, fetchRule,
    policySets, policySetsTotal, policySetsLoading, policySetsNextCursor, selectedPolicySet, policySetRules, policySetCoverage,
    fetchPolicySets, createPolicySet, fetchPolicySet, fetchPolicySetRules, fetchPolicySetCoverage, importPolicySet,
    publishPolicySet, archivePolicySet, newPolicySetVersion,
    driftEvents, driftTotal, driftLoading, driftNextCursor, driftFilters,
    selectedDriftEvent, driftDetails,
    fetchDriftEvents, fetchDriftEvent, fetchDriftDetails, acknowledgeDrift, suppressDrift, resolveDrift,
    exceptions, exceptionsTotal, exceptionsLoading, exceptionsNextCursor, exceptionFilters,
    fetchExceptions, createException, approveException, revokeException,
    remediationPlans, remediationTotal, remediationLoading, remediationNextCursor, remediationError, remediationFilters,
    selectedRemediationPlan, remediationActions, remediationExecution, maintenanceWindows,
    fetchRemediationPlans, fetchRemediationPlan, fetchRemediationActions,
    createRemediationPlan, submitRemediationPlan, approveRemediationPlan, dryRunRemediationPlan,
    fetchRemediationExecution, rollbackRemediationPlan,
    fetchMaintenanceWindows, createMaintenanceWindow,
    fileHashes, fileHashesLoading, fileHashPathPrefix, fetchFileHashes,
    fileChanges, fileChangesTotal, fileChangesLoading, fileChangesNextCursor, fileChangeFilters, fetchFileChanges,
    fileChangePathDetail, fileChangePathDetailLoading, fetchFileChangesByPath,
    reports, reportsTotal, reportsLoading, reportsNextCursor, fetchReports, createReport,
    topViolations, topViolationsLoading, topChangedFiles, topChangedFilesLoading,
    fetchTopViolations, fetchTopChangedFiles,
    overview, overviewLoading, fetchOverview,
    trend, trendLoading, trendRange, fetchTrend,
    assessments, assessmentsLoading, fetchAssessments, createAssessment, fetchAssessment,
  }
})
