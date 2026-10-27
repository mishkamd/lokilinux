<script setup lang="ts">
import { Check, CheckCheck, RefreshCw } from 'lucide-vue-next'
import type { Alert } from '~/stores/dashboard'

const api = useApi()
const { canEdit } = useCurrentUser()
const { severityColor } = useSeverity()
const { statusColor } = useStatusColor()
const { format: fmtDateTime } = useDateTime()
const toast = useToast()

const STATUSES = ['', 'ACTIVE', 'ACKNOWLEDGED', 'RESOLVED', 'EXPIRED']
const SEVERITIES = ['', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']

// Filter state lives in the URL: an alert list is shareable, bookmarkable
// and linkable from the command palette.
const view = reactive({ status: '', severity: '', search: '' })
useUrlFilters(view)

const alerts = ref<Alert[]>([])
const total = ref(0)
const nextCursor = ref<string | null>(null)
const loading = ref(false)
const acting = ref<{ id: string; action: string } | null>(null)

const columns = [
  { key: 'severity', label: 'Severity' },
  { key: 'title', label: 'Alert' },
  { key: 'hostname', label: 'Host' },
  { key: 'status', label: 'Status' },
  { key: 'triggered_at', label: 'Triggered' },
  { key: 'actions', label: '', noSort: true },
]

async function fetchAlerts(cursor?: string) {
  loading.value = true
  try {
    const params = new URLSearchParams({ limit: '50' })
    if (view.status) params.set('status', view.status)
    if (view.severity) params.set('severity', view.severity)
    if (view.search) params.set('search', view.search)
    if (cursor) params.set('cursor', cursor)
    const data = await api.get<{
      items: Alert[]
      next_cursor: string | null
      total: number | null
    }>(`/alerts?${params}`)
    alerts.value = cursor ? [...alerts.value, ...data.items] : data.items
    // The server counts the whole filtered set — never the rows we happen
    // to have loaded, which is what the badge used to show.
    total.value = data.total ?? alerts.value.length
    nextCursor.value = data.next_cursor
  } catch {
    // swallow — the global onResponseError handler already surfaces a toast
  } finally {
    loading.value = false
  }
}

// Typing in the search box must not fire a request per keystroke; the
// select filters ride the same debounce.
let debounce: ReturnType<typeof setTimeout> | undefined
watch(
  view,
  () => {
    clearTimeout(debounce)
    debounce = setTimeout(() => fetchAlerts(), 300)
  },
  { deep: true },
)

async function acknowledge(id: string) {
  acting.value = { id, action: 'ack' }
  try {
    const updated = await api.post<{ id: string; status: string }>(`/alerts/${id}/acknowledge`, {})
    const row = alerts.value.find((a) => a.id === id)
    if (row) row.status = updated.status as Alert['status']
  } catch {
    toast.add({ title: 'Error', description: 'Failed to acknowledge alert', color: 'red' })
  } finally {
    acting.value = null
  }
}

async function resolve(id: string) {
  acting.value = { id, action: 'resolve' }
  try {
    const updated = await api.post<{ id: string; status: string }>(`/alerts/${id}/resolve`, {})
    const row = alerts.value.find((a) => a.id === id)
    if (row) row.status = updated.status as Alert['status']
  } catch {
    toast.add({ title: 'Error', description: 'Failed to resolve alert', color: 'red' })
  } finally {
    acting.value = null
  }
}

onMounted(() => fetchAlerts())
</script>

<template>
  <div>
    <PageHeader>
      <div class="flex flex-wrap items-center gap-3">
        <Select v-model="view.status" :options="STATUSES" placeholder="Status" class="w-40" />
        <Select v-model="view.severity" :options="SEVERITIES" placeholder="Severity" class="w-40" />
        <Input v-model="view.search" placeholder="Search alerts..." class="w-56" aria-label="Search alerts" />
      </div>
      <div class="flex items-center gap-3">
        <Badge color="gray">{{ total }} alerts</Badge>
        <Button variant="outline" @click="fetchAlerts()">
          <RefreshCw class="size-4" />
          Refresh
        </Button>
      </div>
    </PageHeader>

    <div class="mb-3">
      <SavedViews scope="alerts" />
    </div>

    <DataTable
      :rows="alerts"
      :columns="columns"
      :loading="loading"
      sortable
      :page-size="25"
      empty-title="No alerts"
      empty-description="Alerts appear here when a rule triggers."
      caption="Alerts"
      preferences-key="alerts"
    >
      <template #severity-data="{ row }">
        <Badge :color="severityColor(String(row.severity))" size="xs">{{ row.severity }}</Badge>
      </template>
      <template #title-data="{ row }">
        <p class="font-medium leading-tight">{{ row.title }}</p>
        <p v-if="row.description" class="text-xs text-muted-foreground truncate max-w-md">
          {{ row.description }}
        </p>
      </template>
      <template #hostname-data="{ row }">
        <span class="font-mono text-xs">{{ row.hostname ?? '—' }}</span>
      </template>
      <template #status-data="{ row }">
        <Badge :color="statusColor(String(row.status))" size="xs">{{ row.status }}</Badge>
      </template>
      <template #triggered_at-data="{ row }">
        <span class="font-mono text-xs text-muted-foreground">{{ fmtDateTime(String(row.triggered_at)) }}</span>
      </template>
      <template #actions-data="{ row }">
        <div v-if="canEdit" class="flex items-center justify-end gap-1">
          <Tooltip v-if="row.status === 'ACTIVE'" text="Acknowledge alert">
            <Button
              size="xs"
              variant="ghost"
              aria-label="Acknowledge alert"
              :loading="acting?.id === row.id && acting?.action === 'ack'"
              @click="acknowledge(String(row.id))"
            >
              <Check class="size-3.5" />
            </Button>
          </Tooltip>
          <Tooltip v-if="row.status !== 'RESOLVED' && row.status !== 'EXPIRED'" text="Resolve alert">
            <Button
              size="xs"
              variant="ghost"
              aria-label="Resolve alert"
              :loading="acting?.id === row.id && acting?.action === 'resolve'"
              @click="resolve(String(row.id))"
            >
              <CheckCheck class="size-3.5" />
            </Button>
          </Tooltip>
        </div>
      </template>
    </DataTable>

    <div v-if="nextCursor" class="flex justify-center mt-3">
      <Button variant="ghost" @click="fetchAlerts(nextCursor)">Load more</Button>
    </div>
  </div>
</template>
