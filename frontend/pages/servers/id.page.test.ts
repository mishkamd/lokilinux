import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { setActivePinia, createPinia } from 'pinia'
// @ts-expect-error — Nuxt dynamic route brackets aren't in generated type declarations
import ServerDetailPage from './[id].vue'

const apiMocks = {
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}

mockNuxtImport('useApi', () => () => apiMocks)
mockNuxtImport('useRoute', () => () => ({ params: { id: 'srv-1' } }))

const baseServer = {
  id: 'srv-1',
  hostname: 'web-01',
  status: 'ACTIVE',
  fqdn: null,
  ip_address: '10.0.0.1',
  os_name: 'rocky',
  os_version: '9.8',
  kernel_version: '5.14.0',
  agent_version: null,
  tags: {},
  system_users: [],
  recent_logs: null,
  last_seen_at: null,
}

describe('servers/[id].vue — Vulnerabilities & Settings tabs', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    apiMocks.get.mockReset()
    apiMocks.post.mockReset()
    apiMocks.get.mockResolvedValue({ items: [], next_cursor: null }) // jobs default fetch on mount
  })

  it('lazy-loads vulnerabilities only when the Vulnerabilities tab is selected', async () => {
    apiMocks.get.mockImplementation((path: string) => {
      if (path === '/servers/srv-1') return Promise.resolve({ ...baseServer })
      if (path.startsWith('/vulnerabilities/servers/')) {
        return Promise.resolve({ items: [{ id: 1, cve_id: 'CVE-2026-0001', severity: 'HIGH', fix_available: true }], next_cursor: null })
      }
      return Promise.resolve({ items: [], next_cursor: null })
    })

    const wrapper = await mountSuspended(ServerDetailPage)

    expect(apiMocks.get).not.toHaveBeenCalledWith('/vulnerabilities/servers/srv-1')

    // Vulnerabilities is the 4th tab (index 3)
    const tabButtons = wrapper.findAll('button')
    await tabButtons[3]!.trigger('click')

    expect(apiMocks.get).toHaveBeenCalledWith('/vulnerabilities/servers/srv-1')
    expect(wrapper.text()).toContain('CVE-2026-0001')
  })

  it('renders the maintenance toggle in Settings and calls the API on click', async () => {
    apiMocks.get.mockImplementation((path: string) => {
      if (path === '/servers/srv-1') return Promise.resolve({ ...baseServer })
      return Promise.resolve({ items: [], next_cursor: null })
    })
    apiMocks.post.mockResolvedValue({ ...baseServer, status: 'MAINTENANCE' })

    const wrapper = await mountSuspended(ServerDetailPage)

    // Settings is the last (8th) tab (index 7)
    const tabButtons = wrapper.findAll('button')
    await tabButtons[7]!.trigger('click')

    const toggleButton = wrapper.findAll('button').find(b => b.text().includes('maintenance'))
    expect(toggleButton).toBeTruthy()

    await toggleButton!.trigger('click')
    await vi.waitFor(() => expect(apiMocks.post).toHaveBeenCalledWith('/servers/srv-1/maintenance'))
  })
})
