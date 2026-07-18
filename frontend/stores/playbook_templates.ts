import type { Job } from '~/stores/jobs'

export interface PlaybookTemplate {
  id: string
  name: string
  description: string | null
  playbook_id: string
  agent_ids: string[]
  extra_vars: Record<string, unknown> | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export const usePlaybookTemplatesStore = defineStore('playbookTemplates', () => {
  const api = useApi()

  const templates = ref<PlaybookTemplate[]>([])
  const loading = ref(false)

  async function fetchTemplates() {
    loading.value = true
    try {
      templates.value = await api.get<PlaybookTemplate[]>('/playbook-templates')
    } finally {
      loading.value = false
    }
  }

  async function createTemplate(payload: { name: string; description?: string; playbook_id: string; agent_ids: string[]; extra_vars?: Record<string, unknown> }) {
    const template = await api.post<PlaybookTemplate>('/playbook-templates', payload)
    templates.value.unshift(template)
    return template
  }

  async function updateTemplate(id: string, payload: Partial<Pick<PlaybookTemplate, 'name' | 'description' | 'agent_ids' | 'extra_vars'>>) {
    const updated = await api.patch<PlaybookTemplate>(`/playbook-templates/${id}`, payload)
    const idx = templates.value.findIndex((t) => t.id === id)
    if (idx !== -1) templates.value[idx] = updated
    return updated
  }

  async function deleteTemplate(id: string) {
    await api.del(`/playbook-templates/${id}`)
    templates.value = templates.value.filter((t) => t.id !== id)
  }

  async function launchTemplate(id: string, overrides?: { agent_ids?: string[]; extra_vars?: Record<string, unknown> }) {
    return await api.post<Job>(`/playbook-templates/${id}/launch`, {
      agent_ids: overrides?.agent_ids ?? null,
      extra_vars: overrides?.extra_vars ?? null,
    })
  }

  async function fetchHistory(id: string) {
    return await api.get<Job[]>(`/playbook-templates/${id}/history`)
  }

  return { templates, loading, fetchTemplates, createTemplate, updateTemplate, deleteTemplate, launchTemplate, fetchHistory }
})
