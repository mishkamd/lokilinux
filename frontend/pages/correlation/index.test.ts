import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { setActivePinia, createPinia } from 'pinia'
import { nextTick } from 'vue'
import CorrelationPage from './index.vue'

const apiMocks = {
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}

mockNuxtImport('useApi', () => () => apiMocks)
mockNuxtImport('useCurrentUser', () => () => ({ canEdit: true }))

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

function rule() {
  return {
    id: 'rule-1',
    tenant_id: 'default',
    name: 'SSH brute force',
    enabled: true,
    window_seconds: 300,
    group_by: ['host_id'],
    conditions: [{ signal: 'ssh.failed', weight: 1 }],
    threshold_score: 5,
    incident_type: 'BRUTE_FORCE',
    incident_severity: 'HIGH',
    suppressions: [],
    version: 1,
    created_at: '2026-10-29T10:00:00Z',
  }
}

describe('pages/correlation — the enabled switch', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    apiMocks.get.mockReset()
    apiMocks.patch.mockReset()
    apiMocks.get.mockResolvedValue([rule()])
    apiMocks.patch.mockImplementation((_path: string, body: { enabled: boolean }) =>
      Promise.resolve({ ...rule(), enabled: body.enabled }),
    )
  })

  it('sends exactly one PATCH per click, with the value the switch emitted', async () => {
    const wrapper = await mountSuspended(CorrelationPage)
    await sleep(50)

    const toggle = wrapper.find('[role="switch"]')
    expect(toggle.exists()).toBe(true)

    await toggle.trigger('click')
    await sleep(50)

    expect(apiMocks.patch).toHaveBeenCalledTimes(1)
    const [path, body] = apiMocks.patch.mock.calls[0]!
    expect(path).toBe('/correlation/rules/rule-1')
    expect(body.enabled).toBe(false)
  })

  it('ignores a second click while the first PATCH is in flight', async () => {
    let release: (() => void) | undefined
    apiMocks.patch.mockImplementation(
      (_path: string, body: { enabled: boolean }) =>
        new Promise((resolve) => { release = () => resolve({ ...rule(), enabled: body.enabled }) }),
    )

    const wrapper = await mountSuspended(CorrelationPage)
    await sleep(50)

    const toggle = wrapper.find('[role="switch"]')
    await toggle.trigger('click')
    await nextTick()
    await toggle.trigger('click')
    await sleep(50)

    expect(apiMocks.patch).toHaveBeenCalledTimes(1)

    release?.()
    await sleep(50)
  })
})
