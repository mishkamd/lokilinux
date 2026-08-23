<script setup lang="ts">
import { Check, CheckCheck } from 'lucide-vue-next'
import type { Alert } from '~/stores/dashboard'

const api = useApi()
const { canEdit } = useCurrentUser()
const { severityColor } = useSeverity()

const { data: alerts, refresh, status: fetchStatus } = await useAsyncData('alerts', () =>
  api.get<{ items: Alert[] }>('/alerts?limit=100').then((r) => r.items),
)

const columns = [
  { key: 'severity', label: 'Severity' },
  { key: 'title', label: 'Alert' },
  { key: 'status', label: 'Status' },
  { key: 'created_at', label: 'Triggered' },
  { key: 'actions', label: '' },
]

const statusColor = (s: string) =>
  ({ ACTIVE: 'red', ACKNOWLEDGED: 'gray', RESOLVED: 'green', EXPIRED: 'gray' } as Record<string, string>)[s] ?? 'gray'

const openCount = computed(() => alerts.value?.filter((a) => a.status === 'ACTIVE').length ?? 0)

const toast = useToast()
const acting = ref<string | null>(null)

async function acknowledge(id: string) {
  acting.value = id
  try {
    await api.post(`/alerts/${id}/acknowledge`, {})
    await refresh()
  } catch {
    toast.add({ title: 'Error', description: 'Failed to acknowledge alert', color: 'red' })
  } finally {
    acting.value = null
  }
}

async function resolve(id: string) {
  acting.value = id
  try {
    await api.post(`/alerts/${id}/resolve`, {})
    await refresh()
  } catch {
    toast.add({ title: 'Error', description: 'Failed to resolve alert', color: 'red' })
  } finally {
    acting.value = null
  }
}
</script>

<template>
  <div>
    <div class="flex items-center justify-end mb-3">
      <Badge color="red">{{ openCount }} active</Badge>
    </div>

    <DataTable :rows="alerts ?? []" :columns="columns" :loading="fetchStatus === 'pending'">
      <template #severity-data="{ row }">
        <Badge :color="severityColor(String(row.severity))" size="xs">{{ row.severity }}</Badge>
      </template>
      <template #title-data="{ row }">
        <p class="font-medium leading-tight">{{ row.title }}</p>
        <p v-if="row.description" class="text-xs text-muted-foreground truncate max-w-md">{{ row.description }}</p>
      </template>
      <template #status-data="{ row }">
        <Badge :color="statusColor(String(row.status))" size="xs">{{ row.status }}</Badge>
      </template>
      <template #created_at-data="{ row }">
        <span class="font-mono text-xs text-muted-foreground">{{ new Date(String(row.created_at)).toLocaleString() }}</span>
      </template>
      <template #actions-data="{ row }">
        <div v-if="canEdit" class="flex items-center justify-end gap-1">
          <Button
            v-if="row.status === 'ACTIVE'"
            size="xs"
            variant="ghost"
            class="text-muted-foreground"
            :loading="acting === row.id"
            @click="acknowledge(String(row.id))"
          >
            <Check class="size-3.5" />
          </Button>
          <Button
            v-if="row.status !== 'RESOLVED' && row.status !== 'EXPIRED'"
            size="xs"
            variant="ghost"
            class="text-muted-foreground"
            :loading="acting === row.id"
            @click="resolve(String(row.id))"
          >
            <CheckCheck class="size-3.5" />
          </Button>
        </div>
      </template>
    </DataTable>
  </div>
</template>
