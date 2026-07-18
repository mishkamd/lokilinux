<script setup lang="ts">
interface Alert {
  id: string
  title: string
  description: string | null
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO'
  status: 'ACTIVE' | 'ACKNOWLEDGED' | 'RESOLVED' | 'EXPIRED'
  alert_type: string | null
  created_at: string
}

const api = useApi()
const { canEdit } = useCurrentUser()

const { data: alerts, refresh } = await useAsyncData('alerts', () =>
  api.get<{ items: Alert[] }>('/alerts?limit=100').then((r) => r.items),
)

const severityColor = (s: string) =>
  ({ CRITICAL: 'red', HIGH: 'red', MEDIUM: 'gray', LOW: 'gray', INFO: 'gray' } as Record<string, string>)[s] ?? 'gray'

const statusColor = (s: string) =>
  ({ ACTIVE: 'red', ACKNOWLEDGED: 'gray', RESOLVED: 'green', EXPIRED: 'gray' } as Record<string, string>)[s] ?? 'gray'

const openCount = computed(() => alerts.value?.filter((a) => a.status === 'ACTIVE').length ?? 0)

const toast = useToast()

async function acknowledge(id: string) {
  try {
    await api.post(`/alerts/${id}/acknowledge`, {})
    await refresh()
  } catch {
    toast.add({ title: 'Error', description: 'Failed to acknowledge alert', color: 'red' })
  }
}

async function resolve(id: string) {
  try {
    await api.post(`/alerts/${id}/resolve`, {})
    await refresh()
  } catch {
    toast.add({ title: 'Error', description: 'Failed to resolve alert', color: 'red' })
  }
}
</script>

<template>
  <div>
    <div class="flex items-center justify-end mb-4">
      <Badge color="red">{{ openCount }} active</Badge>
    </div>

    <div class="space-y-3">
      <Card v-for="alert in alerts" :key="alert.id">
        <div class="flex items-start justify-between gap-4">
          <div class="flex items-start gap-3 min-w-0">
            <Badge :color="severityColor(alert.severity)" class="shrink-0">{{ alert.severity }}</Badge>
            <div class="min-w-0">
              <p class="font-medium truncate">{{ alert.title }}</p>
              <p v-if="alert.description" class="text-sm text-muted-foreground truncate">{{ alert.description }}</p>
              <p class="text-xs text-muted-foreground mt-1">{{ new Date(alert.created_at).toLocaleString() }}</p>
            </div>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <Badge :color="statusColor(alert.status)">{{ alert.status }}</Badge>
            <Button
              v-if="alert.status === 'ACTIVE' && canEdit"
              size="xs"
              variant="outline"
              @click="acknowledge(alert.id)"
            >Acknowledge</Button>
            <Button
              v-if="alert.status !== 'RESOLVED' && alert.status !== 'EXPIRED' && canEdit"
              size="xs"
              variant="outline"
              @click="resolve(alert.id)"
            >Resolve</Button>
          </div>
        </div>
      </Card>

      <p v-if="!alerts?.length" class="text-center text-muted-foreground py-12">No alerts</p>
    </div>
  </div>
</template>
