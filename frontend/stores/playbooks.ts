import type { Job } from '~/stores/jobs'

export interface Playbook {
  id: string
  name: string
  description: string | null
  content: string
  version: number
  is_enabled: boolean
  generated_by: string | null
  default_extra_vars: Record<string, unknown> | null
  role_ids: string[]
  project_id: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export const usePlaybooksStore = defineStore('playbooks', () => {
  const api = useApi()

  const playbooks = ref<Playbook[]>([])
  const loading = ref(false)

  async function fetchPlaybooks() {
    loading.value = true
    try {
      playbooks.value = await api.get<Playbook[]>('/playbooks')
    } finally {
      loading.value = false
    }
  }

  async function fetchPlaybook(id: string) {
    return await api.get<Playbook>(`/playbooks/${id}`)
  }

  async function createPlaybook(payload: { name: string; description?: string; content: string; role_ids?: string[]; project_id?: string | null }) {
    const playbook = await api.post<Playbook>('/playbooks', payload)
    playbooks.value.unshift(playbook)
    return playbook
  }

  async function updatePlaybook(id: string, payload: Partial<Pick<Playbook, 'name' | 'description' | 'content' | 'is_enabled' | 'default_extra_vars' | 'role_ids' | 'project_id'>>) {
    const updated = await api.patch<Playbook>(`/playbooks/${id}`, payload)
    const idx = playbooks.value.findIndex((p) => p.id === id)
    if (idx !== -1) playbooks.value[idx] = updated
    return updated
  }

  async function deletePlaybook(id: string) {
    await api.del(`/playbooks/${id}`)
    playbooks.value = playbooks.value.filter((p) => p.id !== id)
  }

  async function executePlaybook(id: string, agentIds: string[], extraVars?: Record<string, unknown>) {
    return await api.post<Job>(`/playbooks/${id}/execute`, { agent_ids: agentIds, extra_vars: extraVars ?? null })
  }

  return { playbooks, loading, fetchPlaybooks, fetchPlaybook, createPlaybook, updatePlaybook, deletePlaybook, executePlaybook }
})
