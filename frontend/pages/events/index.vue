<script setup lang="ts">
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

const filters = ref({ type: '', source: '' })
const cursor = ref<string | null>(null)

async function load() {
  const params = new URLSearchParams({ limit: '50' })
  if (filters.value.type) params.set('type', filters.value.type)
  if (filters.value.source) params.set('source', filters.value.source)
  if (cursor.value) params.set('cursor', cursor.value)
  return await api.get<{ items: Event[]; next_cursor: string | null }>(`/events?${params}`)
}

const { data, pending, refresh } = await useAsyncData('events', load, { watch: [filters] })

function loadNext() {
  if (data.value?.next_cursor) {
    cursor.value = data.value.next_cursor
    refresh()
  }
}

function parsedPayload(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
}

const SOURCES = ['', 'agent', 'metrics', 'security', 'compliance', 'patch', 'network', 'ansible', 'job', 'external', 'otel']
</script>

<template>
  <div>
    <PageHeader>
      <div class="flex flex-wrap items-center gap-3">
        <Select v-model="filters.source" :options="SOURCES" placeholder="Source" class="w-40" />
        <Input v-model="filters.type" placeholder="Type (e.g. host.heartbeat.ok)..." class="w-64" @keyup.enter="refresh()" />
      </div>
    </PageHeader>

    <p v-if="pending" class="text-sm text-muted-foreground">Loading…</p>
    <EmptyState v-else-if="!data?.items.length">No events found.</EmptyState>
    <div v-else class="space-y-1">
      <details v-for="e in data.items" :key="e.event_id" class="rounded border border-border p-2 text-sm">
        <summary class="cursor-pointer flex items-center gap-2 flex-wrap">
          <Badge :color="severityColor(e.severity)" size="xs">{{ e.severity }}</Badge>
          <span class="font-mono text-xs text-muted-foreground">{{ e.source }}</span>
          <span class="font-mono flex-1">{{ e.type }}</span>
          <span class="font-mono text-xs text-muted-foreground">{{ new Date(e.timestamp).toLocaleString() }}</span>
        </summary>
        <pre class="mt-2 text-xs bg-muted rounded p-2 overflow-auto max-h-60">{{ parsedPayload(e.payload) }}</pre>
      </details>
    </div>

    <div v-if="data?.next_cursor" class="flex justify-center mt-3">
      <Button variant="ghost" @click="loadNext">Load more</Button>
    </div>
  </div>
</template>
