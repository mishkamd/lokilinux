<script setup lang="ts">
import { Braces, RefreshCw } from 'lucide-vue-next'

interface Event {
  timestamp: string
  event_id: string
  tenant: string
  source: string
  type: string
  severity: string
  host_id: string
  service: string
  fingerprint: string
  schema_version: number
  payload: string
}

const api = useApi()
const { severityColor } = useSeverity()
const { format: fmtDateTime } = useDateTime()

const SOURCES = ['', 'agent', 'metrics', 'security', 'compliance', 'patch', 'network', 'ansible', 'job', 'external', 'otel']

// Filter state lives in the URL: an event feed is shareable and bookmarkable.
const view = reactive({ source: '', search: '' })
useUrlFilters(view)

const events = ref<Event[]>([])
const nextCursor = ref<string | null>(null)
const loading = ref(false)
const payloadEvent = ref<Event | null>(null)

const columns = [
  { key: 'timestamp', label: 'Time' },
  { key: 'severity', label: 'Severity' },
  { key: 'source', label: 'Source' },
  { key: 'type', label: 'Type' },
  { key: 'host_id', label: 'Host' },
  { key: 'actions', label: '', noSort: true },
]

async function fetchEvents(cursor?: string) {
  loading.value = true
  try {
    const params = new URLSearchParams({ limit: '50' })
    if (view.source) params.set('source', view.source)
    if (view.search) params.set('search', view.search)
    if (cursor) params.set('cursor', cursor)
    const data = await api.get<{ items: Event[]; next_cursor: string | null }>(`/events?${params}`)
    // Append on "load more" — replacing the list meant the operator could
    // only ever see one page of the feed.
    events.value = cursor ? [...events.value, ...data.items] : data.items
    nextCursor.value = data.next_cursor
  } catch {
    // swallow — the global onResponseError handler already surfaces a toast
  } finally {
    loading.value = false
  }
}

function prettyPayload(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
}

// Typing in the search box must not fire a request per keystroke; the
// source filter rides the same debounce.
let debounce: ReturnType<typeof setTimeout> | undefined
watch(
  view,
  () => {
    clearTimeout(debounce)
    debounce = setTimeout(() => fetchEvents(), 300)
  },
  { deep: true },
)

onMounted(() => fetchEvents())
</script>

<template>
  <div>
    <PageHeader>
      <div class="flex flex-wrap items-center gap-3">
        <Select v-model="view.source" :options="SOURCES" placeholder="Source" class="w-40" />
        <Input
          v-model="view.search"
          placeholder="Search type (e.g. host.heartbeat)..."
          class="w-64"
          aria-label="Search event types"
        />
        <Button variant="outline" @click="fetchEvents()">
          <RefreshCw class="size-4" />
          Refresh
        </Button>
      </div>
      <div class="flex items-center gap-3">
        <Badge color="gray">{{ events.length }} events</Badge>
      </div>
    </PageHeader>

    <div class="mb-3">
      <SavedViews scope="events" />
    </div>

    <DataTable
      :rows="events"
      :columns="columns"
      :loading="loading"
      sortable
      :page-size="25"
      empty-title="No events"
      empty-description="Events appear here once agents and services report activity."
      caption="Events"
      preferences-key="events"
    >
      <template #timestamp-data="{ row }">
        <span class="font-mono text-xs text-muted-foreground">{{ fmtDateTime(String(row.timestamp)) }}</span>
      </template>
      <template #severity-data="{ row }">
        <Badge :color="severityColor(String(row.severity))" size="xs">{{ row.severity }}</Badge>
      </template>
      <template #source-data="{ row }">
        <span class="font-mono text-xs text-muted-foreground">{{ row.source }}</span>
      </template>
      <template #type-data="{ row }">
        <span class="font-mono text-xs">{{ row.type }}</span>
      </template>
      <template #host_id-data="{ row }">
        <span class="font-mono text-xs text-muted-foreground" :title="row.host_id">
          {{ row.host_id ? `${String(row.host_id).slice(0, 8)}…` : '—' }}
        </span>
      </template>
      <template #actions-data="{ row }">
        <div class="flex items-center justify-end gap-1">
          <Tooltip text="View payload">
            <Button
              size="xs"
              variant="ghost"
              aria-label="View event payload"
              @click="payloadEvent = row as Event"
            >
              <Braces class="size-3.5" />
            </Button>
          </Tooltip>
        </div>
      </template>
    </DataTable>

    <div v-if="nextCursor" class="flex justify-center mt-3">
      <Button variant="ghost" @click="fetchEvents(nextCursor)">Load more</Button>
    </div>

    <Dialog :model-value="!!payloadEvent" title="Event payload" @update:model-value="payloadEvent = null">
      <template #body>
        <div v-if="payloadEvent" class="space-y-3">
          <dl class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <dt class="text-muted-foreground">Type</dt>
            <dd class="font-mono">{{ payloadEvent.type }}</dd>
            <dt class="text-muted-foreground">Source</dt>
            <dd class="font-mono">{{ payloadEvent.source }}</dd>
            <dt class="text-muted-foreground">Severity</dt>
            <dd class="font-mono">{{ payloadEvent.severity }}</dd>
            <dt class="text-muted-foreground">Time</dt>
            <dd class="font-mono">{{ fmtDateTime(payloadEvent.timestamp) }}</dd>
            <dt class="text-muted-foreground">Fingerprint</dt>
            <dd class="font-mono break-all">{{ payloadEvent.fingerprint }}</dd>
          </dl>
          <pre class="text-xs bg-muted rounded p-2 overflow-auto max-h-80">{{ prettyPayload(payloadEvent.payload) }}</pre>
        </div>
      </template>
    </Dialog>
  </div>
</template>
