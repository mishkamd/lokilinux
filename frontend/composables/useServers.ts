import { storeToRefs } from 'pinia'

const STATUS_COLORS: Record<string, string> = {
  ACTIVE: 'green',
  INACTIVE: 'gray',
  UNHEALTHY: 'red',
  MAINTENANCE: 'gray',
  PENDING: 'gray',
  REGISTERED: 'gray',
}

export function useServers() {
  const store = useServersStore()

  function statusColor(status: string): string {
    return STATUS_COLORS[status] ?? 'gray'
  }

  return {
    ...storeToRefs(store),
    statusColor,
    fetchServers: store.fetchServers,
    toggleMaintenance: store.toggleMaintenance,
    fetchCategories: store.fetchCategories,
    fetchProjects: store.fetchProjects,
    createCategory: store.createCategory,
    createProject: store.createProject,
    assignServer: store.assignServer,
  }
}
