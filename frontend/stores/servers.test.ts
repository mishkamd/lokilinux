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

describe('useServersStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    apiMocks.get.mockReset()
    apiMocks.post.mockReset()
  })

  it('fetchServer stores the response and clears any previous error', async () => {
    apiMocks.get.mockResolvedValueOnce({ id: 'srv-1', hostname: 'web-01', status: 'ACTIVE' })
    const store = useServersStore()

    await store.fetchServer('srv-1')

    expect(apiMocks.get).toHaveBeenCalledWith('/servers/srv-1')
    expect(store.selectedServer?.hostname).toBe('web-01')
    expect(store.selectedServerError).toBeNull()
  })

  it('fetchServer records the error and clears selectedServer on failure', async () => {
    apiMocks.get.mockRejectedValueOnce(new Error('boom'))
    const store = useServersStore()

    await store.fetchServer('srv-1')

    expect(store.selectedServer).toBeNull()
    expect(store.selectedServerError).toBe('boom')
  })

  it('fetchPackages populates packages and toggles the loading flag', async () => {
    apiMocks.get.mockResolvedValueOnce([{ id: 1, name: 'curl', version: '8.1.0' }])
    const store = useServersStore()

    const promise = store.fetchPackages('srv-1')
    expect(store.packagesLoading).toBe(true)
    await promise

    expect(apiMocks.get).toHaveBeenCalledWith('/servers/srv-1/packages')
    expect(store.packages).toHaveLength(1)
    expect(store.packagesLoading).toBe(false)
  })

  it('fetchVulnerabilities populates vulnerabilities from the cursor page items', async () => {
    apiMocks.get.mockResolvedValueOnce({
      items: [{ id: 1, cve_id: 'CVE-2026-0001', severity: 'HIGH' }],
      next_cursor: null,
    })
    const store = useServersStore()

    await store.fetchVulnerabilities('srv-1')

    expect(apiMocks.get).toHaveBeenCalledWith('/vulnerabilities/servers/srv-1')
    expect(store.vulnerabilities).toHaveLength(1)
    expect(store.vulnerabilities[0].cve_id).toBe('CVE-2026-0001')
    expect(store.vulnerabilitiesLoading).toBe(false)
  })

  it('toggleMaintenance updates both the list entry and the selected server', async () => {
    const store = useServersStore()
    store.servers = [{ id: 'srv-1', hostname: 'web-01', status: 'ACTIVE' } as any]
    store.selectedServer = { id: 'srv-1', hostname: 'web-01', status: 'ACTIVE' } as any

    apiMocks.post.mockResolvedValueOnce({ id: 'srv-1', hostname: 'web-01', status: 'MAINTENANCE' })

    await store.toggleMaintenance('srv-1')

    expect(apiMocks.post).toHaveBeenCalledWith('/servers/srv-1/maintenance')
    expect(store.servers[0].status).toBe('MAINTENANCE')
    expect(store.selectedServer?.status).toBe('MAINTENANCE')
  })
})
