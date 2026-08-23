export interface ServerDisk {
  mount_point: string
  filesystem: string
  total_size: number
  used_size: number
  free_size: number
}

export interface ServerNetworkInterface {
  name: string
  mac_address: string
  ip_addresses: string[]
  is_up: boolean
  rx_bytes: number
  tx_bytes: number
}

export interface ServerBlockDevice {
  name: string
  type: string
  size: number
  mount_point: string
  parent_name: string
}

export interface ServerListeningPort {
  protocol: string
  local_address: string
  local_port: number
  pid: number
  process_name: string
}

export interface Server {
  id: string
  hostname: string
  fqdn: string | null
  ip_address: string | null
  os_name: string | null
  os_version: string | null
  kernel_version: string | null
  status: 'PENDING' | 'REGISTERED' | 'ACTIVE' | 'INACTIVE' | 'UNHEALTHY' | 'MAINTENANCE'
  agent_version: string | null
  last_seen_at: string | null
  tags: Record<string, string>
  system_users: string[] | null
  recent_logs: {
    lines: string[]
    connections: number
    informative: number
    critical: number
  } | null
  disks: ServerDisk[] | null
  network_interfaces: ServerNetworkInterface[] | null
  block_devices: ServerBlockDevice[] | null
  listening_ports: ServerListeningPort[] | null
  category_id: string | null
  project_id: string | null
}

export interface Category {
  id: string
  name: string
  created_at: string
}

export interface Project {
  id: string
  name: string
  category_id: string | null
  created_at: string
}

export interface ServerPackage {
  id: number
  name: string
  version: string
  architecture: string | null
  repository: string | null
  is_security_update_available: boolean
  is_update_available: boolean
  latest_version: string | null
}

export interface ServerVulnerability {
  id: number
  agent_id: string
  cve_id: string
  package_name: string
  package_version: string
  cvss_score: number | null
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | null
  fix_available: boolean
  is_remediated: boolean
  status: 'OPEN' | 'PATCH_AVAILABLE' | 'IN_PROGRESS' | 'MITIGATED' | 'RESOLVED' | 'ACCEPTED_RISK'
  discovered_at: string
}

export interface ServerMetrics {
  agent_id: string
  status: string
  cpu_usage: number | null
  cpu_count: number | null
  memory_usage: number | null
  memory_total_bytes: number | null
  memory_used_bytes: number | null
  disk_usage: number | null
  disk_total_bytes: number | null
  disk_used_bytes: number | null
  swap_usage: number | null
  swap_total_bytes: number | null
  swap_used_bytes: number | null
  network_latency_ms: number | null
  connection_failures: number
  recorded_at: string | null
}

export const useServersStore = defineStore('servers', () => {
  const api = useApi()

  const servers = ref<Server[]>([])
  const total = ref(0)
  const loading = ref(false)
  const selectedServer = ref<Server | null>(null)
  const selectedServerError = ref<string | null>(null)
  const filters = ref({ status: '', search: '' })
  const packages = ref<ServerPackage[]>([])
  const packagesLoading = ref(false)
  const vulnerabilities = ref<ServerVulnerability[]>([])
  const vulnerabilitiesLoading = ref(false)
  const metrics = ref<ServerMetrics | null>(null)
  const metricsLoading = ref(false)
  const categories = ref<Category[]>([])
  const projects = ref<Project[]>([])

  async function fetchServers(cursor?: string) {
    loading.value = true
    try {
      const params = new URLSearchParams()
      if (cursor) params.set('cursor', cursor)
      if (filters.value.status) params.set('status', filters.value.status)
      if (filters.value.search) params.set('search', filters.value.search)

      const data = await api.get<{ items: Server[]; next_cursor: string | null; total: number }>(
        `/servers?${params}`,
      )
      servers.value = data.items
      total.value = data.total ?? 0
    } catch {
      // swallow — global onResponseError already surfaces a toast; keep last-known-good list
    } finally {
      loading.value = false
    }
  }

  async function fetchServer(id: string) {
    selectedServerError.value = null
    try {
      selectedServer.value = await api.get<Server>(`/servers/${id}`)
    } catch (e) {
      selectedServer.value = null
      selectedServerError.value = e instanceof Error ? e.message : 'Failed to load server'
    }
  }

  async function fetchPackages(id: string) {
    packagesLoading.value = true
    try {
      packages.value = await api.get<ServerPackage[]>(`/servers/${id}/packages`)
    } finally {
      packagesLoading.value = false
    }
  }

  async function fetchVulnerabilities(id: string, includeResolved = false) {
    vulnerabilitiesLoading.value = true
    try {
      const params = new URLSearchParams()
      if (includeResolved) params.set('include_resolved', 'true')
      const data = await api.get<{ items: ServerVulnerability[] }>(`/vulnerabilities/servers/${id}?${params}`)
      vulnerabilities.value = data.items
    } finally {
      vulnerabilitiesLoading.value = false
    }
  }

  async function fetchMetrics(id: string) {
    metricsLoading.value = true
    try {
      metrics.value = await api.get<ServerMetrics>(`/servers/${id}/metrics`)
    } catch (e) {
      metrics.value = null
    } finally {
      metricsLoading.value = false
    }
  }

  async function toggleMaintenance(id: string) {
    const updated = await api.post<Server>(`/servers/${id}/maintenance`)
    const idx = servers.value.findIndex((s: Server) => s.id === id)
    if (idx !== -1) servers.value[idx] = updated
    if (selectedServer.value?.id === id) selectedServer.value = updated
    return updated
  }

  async function fetchAgentsForSelect() {
    try {
      const data = await api.get<{ items: Server[] }>('/servers?limit=100')
      return data.items.map((s) => ({
        label: s.hostname || s.id,
        value: s.id,
      }))
    } catch (e) {
      console.error('Failed to fetch agents:', e)
      return []
    }
  }

  async function fetchCategories() {
    categories.value = await api.get<Category[]>('/categories')
  }

  async function createCategory(name: string) {
    const created = await api.post<Category>('/categories', { name })
    categories.value.push(created)
    return created
  }

  async function fetchProjects() {
    projects.value = await api.get<Project[]>('/projects')
  }

  async function createProject(name: string, categoryId: string | null) {
    const created = await api.post<Project>('/projects', { name, category_id: categoryId })
    projects.value.push(created)
    return created
  }

  async function assignServer(id: string, categoryId: string | null, projectId: string | null) {
    const updated = await api.patch<Server>(`/servers/${id}/assignment`, {
      category_id: categoryId,
      project_id: projectId,
    })
    const idx = servers.value.findIndex((s: Server) => s.id === id)
    if (idx !== -1) servers.value[idx] = updated
    if (selectedServer.value?.id === id) selectedServer.value = updated
    return updated
  }

  return {
    servers, total, loading, selectedServer, selectedServerError, filters,
    fetchServers, fetchServer,
    packages, packagesLoading, fetchPackages,
    vulnerabilities, vulnerabilitiesLoading, fetchVulnerabilities,
    metrics, metricsLoading, fetchMetrics,
    toggleMaintenance,
    fetchAgentsForSelect,
    categories, projects, fetchCategories, fetchProjects, createCategory, createProject, assignServer,
  }
})
