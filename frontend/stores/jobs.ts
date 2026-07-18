export interface Job {
  id: string
  name: string
  target_servers: { agent_ids: string[] }
  job_type: string
  status: 'QUEUED' | 'SCHEDULED' | 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'TIMEOUT' | 'CANCELLED'
  priority: number
  created_by: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  parameters: Record<string, unknown> | null
  requires_approval: boolean
  approved_by: string | null
  approved_at: string | null
}

export interface JobResult {
  agent_id: string
  hostname: string | null
  status: string
  exit_code: number | null
  error_message: string | null
  stdout: string | null
  stderr: string | null
  duration_seconds: number | null
  started_at: string | null
  completed_at: string | null
}

export const useJobsStore = defineStore('jobs', () => {
  const api = useApi()

  const jobs = ref<Job[]>([])
  const total = ref(0)
  const loading = ref(false)
  const filters = ref({ status: '', agent_id: '', job_type: '' })

  async function fetchJobs(agentId?: string, cursor?: string) {
    loading.value = true
    try {
      const params = new URLSearchParams()
      if (cursor) params.set('cursor', cursor)
      if (agentId) params.set('agent_id', agentId)
      else if (filters.value.agent_id) params.set('agent_id', filters.value.agent_id)
      if (filters.value.status) params.set('status', filters.value.status)
      if (filters.value.job_type) params.set('job_type', filters.value.job_type)

      const data = await api.get<{ items: Job[]; next_cursor: string | null; total: number }>(
        `/jobs?${params}`,
      )
      jobs.value = data.items
      total.value = data.total ?? 0
    } finally {
      loading.value = false
    }
  }

  async function createJob(payload: Partial<Job>) {
    const job = await api.post<Job>('/jobs', payload)
    jobs.value.unshift(job)
    total.value += 1
    return job
  }

  async function cancelJob(id: string) {
    await api.patch(`/jobs/${id}/cancel`)
    const idx = jobs.value.findIndex((j) => j.id === id)
    if (idx !== -1) jobs.value[idx]!.status = 'CANCELLED'
  }

  async function approveJob(id: string) {
    const updated = await api.post<Job>(`/jobs/${id}/approve`)
    const idx = jobs.value.findIndex((j) => j.id === id)
    if (idx !== -1) jobs.value[idx] = updated
  }

  async function fetchJobResults(jobId: string) {
    return await api.get<JobResult[]>(`/jobs/${jobId}/results`)
  }

  return { jobs, total, loading, filters, fetchJobs, createJob, cancelJob, approveJob, fetchJobResults }
})
