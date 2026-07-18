export interface AnsibleProject {
  id: string
  name: string
  description: string | null
  default_agent_ids: string[]
  created_by: string | null
  created_at: string
  updated_at: string
}

export const useAnsibleProjectsStore = defineStore('ansibleProjects', () => {
  const api = useApi()

  const projects = ref<AnsibleProject[]>([])
  const loading = ref(false)

  async function fetchProjects() {
    loading.value = true
    try {
      projects.value = await api.get<AnsibleProject[]>('/ansible-projects')
    } finally {
      loading.value = false
    }
  }

  async function createProject(payload: { name: string; description?: string; default_agent_ids?: string[] }) {
    const project = await api.post<AnsibleProject>('/ansible-projects', payload)
    projects.value.unshift(project)
    return project
  }

  async function updateProject(id: string, payload: Partial<Pick<AnsibleProject, 'name' | 'description' | 'default_agent_ids'>>) {
    const updated = await api.patch<AnsibleProject>(`/ansible-projects/${id}`, payload)
    const idx = projects.value.findIndex((p) => p.id === id)
    if (idx !== -1) projects.value[idx] = updated
    return updated
  }

  async function deleteProject(id: string) {
    await api.del(`/ansible-projects/${id}`)
    projects.value = projects.value.filter((p) => p.id !== id)
  }

  return { projects, loading, fetchProjects, createProject, updateProject, deleteProject }
})
