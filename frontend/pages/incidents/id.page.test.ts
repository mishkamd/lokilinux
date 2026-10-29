import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { setActivePinia, createPinia } from 'pinia'
import { nextTick, reactive } from 'vue'
import IncidentDetailPage from './[id].vue'

const apiMocks = {
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}

mockNuxtImport('useApi', () => () => apiMocks)
mockNuxtImport('useCurrentUser', () => () => ({ canEdit: true }))

const route = reactive({ params: { id: 'inc-1' as string } })
mockNuxtImport('useRoute', () => () => route)

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

function incident(id: string) {
  return {
    id,
    tenant_id: 'default',
    title: `Incident ${id}`,
    type: 'BRUTE_FORCE',
    severity: 'HIGH',
    status: 'OPEN',
    root_cause_signal_id: null,
    confidence: 0.9,
    group_key: null,
    started_at: '2026-10-29T10:00:00Z',
    updated_at: '2026-10-29T10:00:00Z',
    resolved_at: null,
    acknowledged_at: null,
    signals: [],
    timeline: [],
  }
}

describe('pages/incidents/[id].vue — route changes and per-action feedback', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    route.params.id = 'inc-1'
    apiMocks.get.mockReset()
    apiMocks.post.mockReset()
    apiMocks.get.mockImplementation((path: string) => {
      if (path === '/runbooks') return Promise.resolve([])
      if (path.endsWith('/evidence')) {
        return Promise.resolve({ items: [{ kind: 'log', summary: `evidence for ${path}` }] })
      }
      const id = path.split('/')[2] ?? ''
      return Promise.resolve(incident(id))
    })
  })

  it('reloads the incident and drops the old evidence when the route id changes', async () => {
    const wrapper = await mountSuspended(IncidentDetailPage)
    await sleep(50)
    expect(apiMocks.get).toHaveBeenCalledWith('/incidents/inc-1')

    const details = wrapper.find('details')
    ;(details.element as HTMLDetailsElement).open = true
    await details.trigger('toggle')
    await sleep(50)
    expect(apiMocks.get).toHaveBeenCalledWith('/incidents/inc-1/evidence')
    expect(wrapper.text()).toContain('evidence for /incidents/inc-1/evidence')

    // Navigate to another incident without remounting the page.
    route.params.id = 'inc-2'
    await nextTick()
    await sleep(50)

    expect(apiMocks.get).toHaveBeenCalledWith('/incidents/inc-2')
    expect(wrapper.text()).not.toContain('evidence for /incidents/inc-1/evidence')
  })

  it('spins only the action that was pressed', async () => {
    let releaseAck: (() => void) | undefined
    apiMocks.post.mockImplementation(
      () => new Promise((resolve) => { releaseAck = () => resolve(incident('inc-1')) }),
    )

    const wrapper = await mountSuspended(IncidentDetailPage)
    await sleep(50)

    const buttons = wrapper.findAll('button')
    const ack = buttons.find((b) => b.text().includes('Acknowledge'))!
    const resolve = buttons.find((b) => b.text().includes('Resolve'))!

    await ack.trigger('click')
    await nextTick()

    expect(ack.attributes('disabled')).toBeDefined()
    expect(resolve.attributes('disabled')).toBeUndefined()

    releaseAck?.()
    await sleep(50)
    expect(ack.attributes('disabled')).toBeUndefined()
  })
})
