import { storeToRefs } from 'pinia'

const JOB_STATUS_COLORS: Record<string, string> = {
  QUEUED: 'gray',
  SCHEDULED: 'gray',
  PENDING: 'gray',
  RUNNING: 'blue',
  COMPLETED: 'green',
  FAILED: 'red',
  TIMEOUT: 'red',
  CANCELLED: 'gray',
}

export function useJobs(agentId?: string) {
  const store = useJobsStore()

  onMounted(() => store.fetchJobs(agentId))

  function statusColor(status: string): string {
    return JOB_STATUS_COLORS[status] ?? 'gray'
  }

  return { ...storeToRefs(store), statusColor, refresh: () => store.fetchJobs(agentId) }
}
