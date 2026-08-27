import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport } from '@nuxt/test-utils/runtime'
import { setActivePinia, createPinia } from 'pinia'

const apiMocks = {
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}

mockNuxtImport('useApi', () => () => apiMocks)

describe('useComplianceStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    apiMocks.get.mockReset()
    apiMocks.post.mockReset()
  })

  describe('baselines', () => {
    it('fetchBaselines populates the list and total from a cursor page', async () => {
      apiMocks.get.mockResolvedValueOnce({
        items: [{ id: 'b1', name: 'Global Default', scope_type: 'GLOBAL' }],
        next_cursor: null,
        total: 1,
      })
      const store = useComplianceStore()

      await store.fetchBaselines()

      expect(apiMocks.get).toHaveBeenCalledWith(expect.stringContaining('/compliance/baselines?'))
      expect(store.baselines).toHaveLength(1)
      expect(store.baselinesTotal).toBe(1)
      expect(store.baselinesLoading).toBe(false)
    })

    it('createBaseline prepends the new baseline to the list', async () => {
      const store = useComplianceStore()
      store.baselines = [{ id: 'existing' } as any]
      apiMocks.post.mockResolvedValueOnce({ id: 'new-1', name: 'New Baseline' })

      const created = await store.createBaseline({
        name: 'New Baseline',
        scope_type: 'GLOBAL',
        scope_selector: {},
        expected_state: {},
      })

      expect(apiMocks.post).toHaveBeenCalledWith('/compliance/baselines', expect.objectContaining({ name: 'New Baseline' }))
      expect(created.id).toBe('new-1')
      expect(store.baselines[0]!.id).toBe('new-1')
      expect(store.baselines).toHaveLength(2)
    })
  })

  describe('policy engine', () => {
    it('fetchRules populates the rule catalog', async () => {
      apiMocks.get.mockResolvedValueOnce({ items: [{ id: 'r1', rule_key: 'sshd_disable_root' }], next_cursor: null, total: 1 })
      const store = useComplianceStore()

      await store.fetchRules()

      expect(apiMocks.get).toHaveBeenCalledWith(expect.stringContaining('/compliance/rules?'))
      expect(store.rules).toHaveLength(1)
      expect(store.rulesTotal).toBe(1)
    })

    it('createPolicySet prepends the new policy set', async () => {
      const store = useComplianceStore()
      apiMocks.post.mockResolvedValueOnce({ id: 'ps1', name: 'CIS Baseline', slug: 'cis-baseline' })

      const created = await store.createPolicySet({ name: 'CIS Baseline', slug: 'cis-baseline', framework: 'CIS' })

      expect(apiMocks.post).toHaveBeenCalledWith('/compliance/policy-sets', expect.objectContaining({ slug: 'cis-baseline' }))
      expect(store.policySets[0]!.id).toBe('ps1')
      expect(created.name).toBe('CIS Baseline')
    })

    it('importPolicySet posts to the import endpoint and returns the job', async () => {
      const store = useComplianceStore()
      apiMocks.post.mockResolvedValueOnce({ job_id: 'job-1', status: 'QUEUED' })

      const result = await store.importPolicySet({
        source: 'complianceascode',
        content_version: 'v1',
        datastream_url: 'https://example.com/ds.xml',
      })

      expect(apiMocks.post).toHaveBeenCalledWith('/compliance/policy-sets/import', expect.objectContaining({ content_version: 'v1' }))
      expect(result.job_id).toBe('job-1')
    })
  })

  describe('drift', () => {
    it('fetchDriftEvents populates events and total', async () => {
      apiMocks.get.mockResolvedValueOnce({
        items: [{ id: 'd1', domain: 'sshd', severity: 'HIGH', acknowledged_at: null }],
        next_cursor: null,
        total: 1,
      })
      const store = useComplianceStore()

      await store.fetchDriftEvents()

      expect(apiMocks.get).toHaveBeenCalledWith(expect.stringContaining('/compliance/drift-events?'))
      expect(store.driftEvents).toHaveLength(1)
      expect(store.driftTotal).toBe(1)
    })

    it('acknowledgeDrift patches both the list entry and selectedDriftEvent in place', async () => {
      const store = useComplianceStore()
      store.driftEvents = [{ id: 'd1', acknowledged_at: null } as any]
      store.selectedDriftEvent = { id: 'd1', acknowledged_at: null } as any
      apiMocks.post.mockResolvedValueOnce({ id: 'd1', acknowledged_at: '2026-01-01T00:00:00Z' })

      await store.acknowledgeDrift('d1')

      expect(apiMocks.post).toHaveBeenCalledWith('/compliance/drift-events/d1/acknowledge')
      expect(store.driftEvents[0]!.acknowledged_at).toBe('2026-01-01T00:00:00Z')
      expect(store.selectedDriftEvent?.acknowledged_at).toBe('2026-01-01T00:00:00Z')
    })
  })

  describe('findings', () => {
    it('fetchFindings defaults to result=FAIL and populates the list', async () => {
      apiMocks.get.mockResolvedValueOnce({
        items: [{ id: 'f1', domain: 'sshd', severity: 'HIGH', result: 'FAIL', acknowledged_at: null }],
        next_cursor: null,
        total: 1,
      })
      const store = useComplianceStore()

      await store.fetchFindings()

      expect(apiMocks.get).toHaveBeenCalledWith(expect.stringContaining('/compliance/findings?'))
      expect(apiMocks.get).toHaveBeenCalledWith(expect.stringContaining('result=FAIL'))
      expect(store.findings).toHaveLength(1)
      expect(store.findingsTotal).toBe(1)
    })

    it('fetchFinding populates selectedFinding', async () => {
      apiMocks.get.mockResolvedValueOnce({ id: 'f1', title: 'Disable root login', acknowledged_at: null })
      const store = useComplianceStore()

      await store.fetchFinding('f1')

      expect(apiMocks.get).toHaveBeenCalledWith('/compliance/findings/f1')
      expect(store.selectedFinding?.title).toBe('Disable root login')
    })

    it('acknowledgeFinding patches both the list entry and selectedFinding in place', async () => {
      const store = useComplianceStore()
      store.findings = [{ id: 'f1', acknowledged_at: null } as any]
      store.selectedFinding = { id: 'f1', acknowledged_at: null } as any
      apiMocks.post.mockResolvedValueOnce({ id: 'f1', acknowledged_at: '2026-01-01T00:00:00Z' })

      await store.acknowledgeFinding('f1')

      expect(apiMocks.post).toHaveBeenCalledWith('/compliance/findings/f1/acknowledge')
      expect(store.findings[0]!.acknowledged_at).toBe('2026-01-01T00:00:00Z')
      expect(store.selectedFinding?.acknowledged_at).toBe('2026-01-01T00:00:00Z')
    })
  })

  describe('remediation', () => {
    it('fetchRemediationPlans populates the plan list', async () => {
      apiMocks.get.mockResolvedValueOnce({ items: [{ id: 'p1', status: 'DRAFT' }], next_cursor: null, total: 1 })
      const store = useComplianceStore()

      await store.fetchRemediationPlans()

      expect(apiMocks.get).toHaveBeenCalledWith(expect.stringContaining('/compliance/remediation-plans?'))
      expect(store.remediationPlans).toHaveLength(1)
    })

    it('submitRemediationPlan updates selectedRemediationPlan when it matches', async () => {
      const store = useComplianceStore()
      store.selectedRemediationPlan = { id: 'p1', status: 'DRAFT' } as any
      apiMocks.post.mockResolvedValueOnce({ id: 'p1', status: 'PENDING_APPROVAL' })

      const updated = await store.submitRemediationPlan('p1')

      expect(apiMocks.post).toHaveBeenCalledWith('/compliance/remediation-plans/p1/submit')
      expect(updated.status).toBe('PENDING_APPROVAL')
      expect(store.selectedRemediationPlan?.status).toBe('PENDING_APPROVAL')
    })
  })

  describe('file integrity', () => {
    it('fetchFileHashes requests the per-agent endpoint', async () => {
      apiMocks.get.mockResolvedValueOnce([{ agent_id: 'a1', path: '/etc/passwd', hash: 'abc' }])
      const store = useComplianceStore()

      await store.fetchFileHashes('a1')

      expect(apiMocks.get).toHaveBeenCalledWith(expect.stringContaining('/compliance/agents/a1/file-hashes?'))
      expect(store.fileHashes).toHaveLength(1)
    })

    it('fetchFileChanges populates change history', async () => {
      apiMocks.get.mockResolvedValueOnce({
        items: [{ path: '/etc/passwd', change_kind: 'MODIFIED' }],
        next_cursor: null,
        total: 1,
      })
      const store = useComplianceStore()

      await store.fetchFileChanges()

      expect(apiMocks.get).toHaveBeenCalledWith(expect.stringContaining('/compliance/file-changes?'))
      expect(store.fileChanges).toHaveLength(1)
      expect(store.fileChangesTotal).toBe(1)
    })
  })

  describe('reports', () => {
    it('fetchReports populates the report list', async () => {
      apiMocks.get.mockResolvedValueOnce({ items: [{ id: 'r1', status: 'PENDING' }], next_cursor: null, total: 1 })
      const store = useComplianceStore()

      await store.fetchReports()

      expect(apiMocks.get).toHaveBeenCalledWith(expect.stringContaining('/compliance/reports?'))
      expect(store.reports).toHaveLength(1)
    })

    it('createReport prepends the new report to the list', async () => {
      const store = useComplianceStore()
      apiMocks.post.mockResolvedValueOnce({ id: 'r1', report_type: 'FLEET_SUMMARY', format: 'JSON', status: 'PENDING' })

      const created = await store.createReport({ report_type: 'FLEET_SUMMARY', format: 'JSON' })

      expect(apiMocks.post).toHaveBeenCalledWith('/compliance/reports', expect.objectContaining({ report_type: 'FLEET_SUMMARY' }))
      expect(created.id).toBe('r1')
      expect(store.reports[0]!.id).toBe('r1')
    })
  })
})
