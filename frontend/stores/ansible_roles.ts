export interface AnsibleRole {
  id: string
  name: string
  description: string | null
  files: Record<string, string>
  version: number
  is_enabled: boolean
  created_by: string | null
  created_at: string
  updated_at: string
}

export const useAnsibleRolesStore = defineStore('ansibleRoles', () => {
  const api = useApi()

  const roles = ref<AnsibleRole[]>([])
  const loading = ref(false)

  async function fetchRoles() {
    loading.value = true
    try {
      roles.value = await api.get<AnsibleRole[]>('/ansible-roles')
    } finally {
      loading.value = false
    }
  }

  async function fetchRole(id: string) {
    return await api.get<AnsibleRole>(`/ansible-roles/${id}`)
  }

  async function createRole(payload: { name: string; description?: string; files: Record<string, string> }) {
    const role = await api.post<AnsibleRole>('/ansible-roles', payload)
    roles.value.unshift(role)
    return role
  }

  async function updateRole(id: string, payload: Partial<Pick<AnsibleRole, 'name' | 'description' | 'files' | 'is_enabled'>>) {
    const updated = await api.patch<AnsibleRole>(`/ansible-roles/${id}`, payload)
    const idx = roles.value.findIndex((r) => r.id === id)
    if (idx !== -1) roles.value[idx] = updated
    return updated
  }

  async function deleteRole(id: string) {
    await api.del(`/ansible-roles/${id}`)
    roles.value = roles.value.filter((r) => r.id !== id)
  }

  return { roles, loading, fetchRoles, fetchRole, createRole, updateRole, deleteRole }
})
