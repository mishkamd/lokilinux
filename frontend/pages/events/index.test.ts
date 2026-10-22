import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import EventsPage from './index.vue'

const apiMocks = {
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}
mockNuxtImport('useApi', () => () => apiMocks)

function event(n: number, type = 'host.heartbeat.ok') {
  return {
    timestamp: '2026-10-21T10:00:00.000Z',
    event_id: `evt-${n}`,
    tenant: 'default',
    source: 'agent',
    type,
    severity: 'INFO',
    host_id: 'host-1',
    service: '',
    fingerprint: 'fp',
    schema_version: 1,
    payload: '{}',
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

describe('pages/events — filtering and pagination', () => {
  beforeEach(() => {
    apiMocks.get.mockReset()
    apiMocks.get.mockImplementation((path: string) => {
      // The saved-views chip loads its own list from the account API.
      if (path.startsWith('/account/views')) return Promise.resolve([])
      // A filtered query matches nothing, so a stale row would mean the
      // list was appended to instead of replaced.
      if (path.includes('search=')) return Promise.resolve({ items: [], next_cursor: null })
      return Promise.resolve({ items: [event(1)], next_cursor: null })
    })
  })

  it('refetches when a filter changes and replaces the rows', async () => {
    const wrapper = await mountSuspended(EventsPage)
    await sleep(50)
    const callsAfterMount = apiMocks.get.mock.calls.length
    expect(callsAfterMount).toBeGreaterThan(0)
    expect(wrapper.text()).toContain('host.heartbeat.ok')

    const input = wrapper.find('input')
    await input.setValue('heartbeat')
    await sleep(400)

    // The filter has to reach the server, and the previous rows must be
    // replaced — the old page used to keep showing the unfiltered feed.
    // The filter has to reach the server, and the previous rows must be
    // replaced — the old page used to keep showing the unfiltered feed.
    // (Some call contains the filter: a later background refetch is not
    // what this test is about.)
    const calls = apiMocks.get.mock.calls.map((c) => c[0] as string)
    expect(calls.some((c) => c.includes('search=heartbeat'))).toBe(true)
    expect(wrapper.text()).not.toContain('host.heartbeat.ok')
  })

  it('appends the next page on "Load more" instead of replacing the list', async () => {
    apiMocks.get.mockImplementation((path: string) => {
      if (path.startsWith('/account/views')) return Promise.resolve([])
      return Promise.resolve({ items: [event(1)], next_cursor: 'cursor-2' })
    })
    const wrapper = await mountSuspended(EventsPage)
    await sleep(50)
    expect(wrapper.text()).toContain('host.heartbeat.ok')

    apiMocks.get.mockImplementation((path: string) => {
      if (path.startsWith('/account/views')) return Promise.resolve([])
      return Promise.resolve({ items: [event(2, 'metric.sample')], next_cursor: null })
    })
    const loadMore = wrapper.findAll('button').find((b) => b.text().includes('Load more'))
    expect(loadMore).toBeDefined()
    await loadMore!.trigger('click')
    await sleep(50)

    const calls = apiMocks.get.mock.calls.map((c) => c[0] as string)
    expect(calls.some((c) => c.includes('cursor=cursor-2'))).toBe(true)
    // Both pages on screen: the old page replaced the list, so page two was
    // the only thing the operator ever saw.
    expect(wrapper.text()).toContain('host.heartbeat.ok')
    expect(wrapper.text()).toContain('metric.sample')
  })
})
