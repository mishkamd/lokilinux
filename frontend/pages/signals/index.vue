<script setup lang="ts">
import { Ban, Check, RefreshCw } from 'lucide-vue-next'

const store = useSignalsStore()
const { signals, total, loading, nextCursor, filters } = storeToRefs(store)
const { severityColor } = useSeverity()
const toast = useToast()

const STATUSES = ['', 'OPEN', 'RESOLVED', 'SUPPRESSED']
const SEVERITIES = ['', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW']

const columns = [
  { key: 'severity', label: 'Severity' },
  { key: 'type', label: 'Type' },
  { key: 'host_id', label: 'Host' },
  { key: 'occurrence_count', label: 'Occurrences' },
  { key: 'last_seen', label: 'Last seen' },
  { key: 'status', label: 'Status' },
  { key: 'actions', label: '' },
]

const statusColor = (s: string) =>
  ({ OPEN: 'red', RESOLVED: 'green', SUPPRESSED: 'gray' } as Record<string, string>)[s] ?? 'gray'

const acting = ref<string | null>(null)

async function resolve(id: string) {
  acting.value = id
  try {
    await store.resolveSignal(id)
  } catch {
    toast.add({ title: 'Error', description: 'Failed to resolve signal', color: 'red' })
  } finally {
    acting.value = null
  }
}

async function suppress(id: string) {
  acting.value = id
  try {
    await store.suppressSignal(id)
  } catch {
    toast.add({ title: 'Error', description: 'Failed to suppress signal', color: 'red' })
  } finally {
    acting.value = null
  }
}

onMounted(() => store.fetchSignals())
</script>

<template>
  <div>
    <PageHeader>
      <div class="flex flex-wrap items-center gap-3">
        <Select v-model="filters.status" :options="STATUSES" placeholder="Status" class="w-40" @change="store.fetchSignals()" />
        <Select v-model="filters.severity" :options="SEVERITIES" placeholder="Severity" class="w-40" @change="store.fetchSignals()" />
        <Button variant="outline" @click="store.fetchSignals()">
          <RefreshCw class="size-4" />
          Refresh
        </Button>
      </div>
      <Badge color="gray">{{ total }} signals</Badge>
    </PageHeader>

    <DataTable :rows="signals" :columns="columns" :loading="loading">
      <template #severity-data="{ row }">
        <Badge :color="severityColor(String(row.severity))" size="xs">{{ row.severity }}</Badge>
      </template>
      <template #type-data="{ row }">
        <span class="font-mono text-xs">{{ row.type }}</span>
      </template>
      <template #host_id-data="{ row }">
        <span class="font-mono text-xs text-muted-foreground">{{ row.host_id ?? '—' }}</span>
      </template>
      <template #occurrence_count-data="{ row }">
        <span class="font-mono text-xs tabular-nums">{{ row.occurrence_count }}</span>
      </template>
      <template #last_seen-data="{ row }">
        <span class="font-mono text-xs text-muted-foreground">{{ new Date(String(row.last_seen)).toLocaleString() }}</span>
      </template>
      <template #status-data="{ row }">
        <Badge :color="statusColor(String(row.status))" size="xs">{{ row.status }}</Badge>
      </template>
      <template #actions-data="{ row }">
        <div v-if="row.status === 'OPEN'" class="flex items-center justify-end gap-1">
          <Button size="xs" variant="ghost" class="text-muted-foreground" aria-label="Resolve signal" :loading="acting === row.id" @click="resolve(String(row.id))">
            <Check class="size-3.5" />
          </Button>
          <Button size="xs" variant="ghost" class="text-muted-foreground" aria-label="Suppress signal" :loading="acting === row.id" @click="suppress(String(row.id))">
            <Ban class="size-3.5" />
          </Button>
        </div>
      </template>
    </DataTable>

    <div v-if="nextCursor" class="flex justify-center mt-3">
      <Button variant="ghost" @click="store.loadMore()">Load more</Button>
    </div>
  </div>
</template>
