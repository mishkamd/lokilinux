import type { Workflow } from '~/types/workflow'

export const useWorkflowsStore = defineStore('workflows', () => {
  const api = useApi()

  const workflows = ref<Workflow[]>([])
  const total = ref(0)
  const loading = ref(false)

  async function fetchWorkflows() {
    loading.value = true
    try {
      const data = await api.get<{ items: Workflow[]; total: number | null }>('/workflows?limit=100')
      workflows.value = data.items
      total.value = data.total ?? data.items.length
    } catch {
      // swallow — global onResponseError already surfaces a toast; keep last-known-good list
    } finally {
      loading.value = false
    }
  }

  async function createWorkflow(name: string, yaml: string): Promise<Workflow> {
    const workflow = await api.post<Workflow>('/workflows', { name, yaml })
    workflows.value.unshift(workflow)
    return workflow
  }

  async function deleteWorkflow(id: string) {
    await api.del(`/workflows/${id}`)
    workflows.value = workflows.value.filter(w => w.id !== id)
  }

  return { workflows, total, loading, fetchWorkflows, createWorkflow, deleteWorkflow }
})
