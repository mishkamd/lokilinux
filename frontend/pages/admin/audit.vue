<script setup lang="ts">
definePageMeta({ layout: 'default' })

interface AuditLog {
  id: string
  timestamp: string
  actor_name: string | null
  action: string
  resource_type: string | null
  resource_id: string | null
  status: string
}

const api = useApi()

const cursor = ref<number | null>(null)
const { data, pending, error, refresh } = await useAsyncData('audit-logs', () =>
  api.get<{ items: AuditLog[]; next_cursor: number | null; total: number }>(
    '/admin/audit',
    { params: { limit: 50, ...(cursor.value ? { cursor: cursor.value } : {}) } },
  ),
)

async function loadNext() {
  if (data.value?.next_cursor) {
    cursor.value = data.value.next_cursor
    await refresh()
  }
}

const columns = [
  { key: 'timestamp', label: 'Time' },
  { key: 'actor_name', label: 'Actor' },
  { key: 'action', label: 'Action' },
  { key: 'resource_type', label: 'Resource' },
  { key: 'resource_id', label: 'ID' },
  { key: 'status', label: 'Status' },
]
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="Audit Log" />

    <div v-if="error" class="rounded-md border border-destructive p-4 text-sm text-destructive">
      Failed to load audit logs: {{ error.message }}
    </div>

    <DataTable :rows="data?.items ?? []" :columns="columns" :loading="pending">
      <template #timestamp-data="{ row }">
        <span class="font-mono text-xs text-muted-foreground">{{ new Date(String(row.timestamp)).toLocaleString() }}</span>
      </template>
      <template #resource_id-data="{ row }">
        <span class="font-mono text-xs">{{ row.resource_id ?? '—' }}</span>
      </template>
      <template #status-data="{ row }">
        <Badge :color="row.status === 'success' ? 'green' : 'red'" size="xs">{{ row.status }}</Badge>
      </template>
    </DataTable>

    <div v-if="data?.next_cursor" class="flex justify-center">
      <Button variant="ghost" @click="loadNext">Load more</Button>
    </div>
  </div>
</template>
