export type PluginStatus =
  | 'PENDING_INSTALL'
  | 'INSTALLING'
  | 'INSTALLED'
  | 'INSTALLING_FAILED'
  | 'ENABLED'
  | 'DISABLED'
  | 'ERROR'

export interface Plugin {
  id: string
  name: string
  display_name: string | null
  version: string
  description: string | null
  author: string | null
  icon_url: string | null
  plugin_type: string
  installation_status: PluginStatus
  is_enabled: boolean
  is_installed: boolean
  security_verified: boolean
  download_count: number
  rating: number
  installed_at: string | null
  created_at: string
}

export const usePluginsStore = defineStore('plugins', () => {
  const api = useApi()

  const plugins = ref<Plugin[]>([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchPlugins() {
    loading.value = true
    error.value = null
    try {
      const data = await api.get<{ items: Plugin[]; total: number | null }>('/plugins')
      plugins.value = data.items
      total.value = data.total ?? 0
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load plugins'
    } finally {
      loading.value = false
    }
  }

  async function installPlugin(pluginId: string, agentIds: string[] = []) {
    await api.post(`/plugins/${pluginId}/install`, agentIds)
    await fetchPlugins()
  }

  async function enablePlugin(pluginId: string) {
    const updated = await api.post<Plugin>(`/plugins/${pluginId}/enable`)
    const idx = plugins.value.findIndex(p => p.id === pluginId)
    if (idx !== -1) plugins.value[idx] = updated
  }

  async function disablePlugin(pluginId: string) {
    const updated = await api.post<Plugin>(`/plugins/${pluginId}/disable`)
    const idx = plugins.value.findIndex(p => p.id === pluginId)
    if (idx !== -1) plugins.value[idx] = updated
  }

  return { plugins, total, loading, error, fetchPlugins, installPlugin, enablePlugin, disablePlugin }
})
