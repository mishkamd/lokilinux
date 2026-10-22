<script setup lang="ts">
import { Ban, Check, RefreshCw } from 'lucide-vue-next'

const store = useSignalsStore()
const { signals, total, loading, nextCursor, filters } = storeToRefs(store)
const { severityColor } = useSeverity()
const { statusColor } = useStatusColor()
const { canEdit } = useCurrentUser()
const toast = useToast()
const { format: fmtDateTime } = useDateTime()

const STATUSES = ['', 'OPEN', 'RESOLVED', 'SUPPRESSED']
const SEVERITIES = ['', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW']

// Filter state lives in the URL: a signal list is shareable, bookmarkable
// and linkable from the command palette.
useUrlFilters(filters.value, { status: '', severity: '', type: '', host_id: '', search: '' })

const columns = [
  { key: 'severity', label: 'Severity' },
  { key: 'type', label: 'Type' },
  { key: 'hostname', label: 'Host' },
  { key: 'occurrence_count', label: 'Occurrences' },
  { key: 'last_seen', label: 'Last seen' },
  { key: 'status', label: 'Status' },
  { key: 'actions', label: '', noSort: true },
]

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

// Typing in the search box must not fire a request per keystroke; the
// select filters ride the same debounce.
let debounce: ReturnType<typeof setTimeout> | undefined
watch(
  filters,
  () => {
    clearTimeout(debounce)
    debounce = setTimeout(() => store.fetchSignals(), 300)
  },
  { deep: true },
)

onMounted(() => store.fetchSignals())
</script>

<template>
  <div>
    <PageHeader>
      <div class="flex flex-wrap items-center gap-3">
        <Select v-model="filters.status" :options="STATUSES" placeholder="Status" class="w-40" />
        <Select v-model="filters.severity" :options="SEVERITIES" placeholder="Severity" class="w-40" />
        <Input v-model="filters.search" placeholder="Search signal type..." class="w-56" aria-label="Search signals" />
        <Button variant="outline" @click="store.fetchSignals()">
          <RefreshCw class="size-4" />
          Refresh
        </Button>
      </div>
      <div class="flex items-center gap-3">
        <Badge color="gray">{{ total }} signals</Badge>
      </div>
    </PageHeader>

    <div class="mb-3">
      <SavedViews scope="signals" />
    </div>

    <DataTable
      :rows="signals"
      :columns="columns"
      :loading="loading"
      sortable
      :page-size="25"
      empty-title="No signals"
      empty-description="Signals appear here once agents report activity."
      caption="Signals"
      preferences-key="signals"
    >
      <template #severity-data="{ row }">
        <Badge :color="severityColor(String(row.severity))" size="xs">{{ row.severity }}</Badge>
      </template>
      <template #type-data="{ row }">
        <span class="font-mono text-xs">{{ row.type }}</span>
      </template>
      <template #hostname-data="{ row }">
        <span class="font-mono text-xs">{{ row.hostname ?? row.host_id ?? '—' }}</span>
      </template>
      <template #occurrence_count-data="{ row }">
        <span class="font-mono text-xs tabular-nums">{{ row.occurrence_count }}</span>
      </template>
      <template #last_seen-data="{ row }">
        <span class="font-mono text-xs text-muted-foreground">{{ fmtDateTime(String(row.last_seen)) }}</span>
      </template>
      <template #status-data="{ row }">
        <Badge :color="statusColor(String(row.status))" size="xs">{{ row.status }}</Badge>
      </template>
      <template #actions-data="{ row }">
        <div v-if="canEdit && row.status === 'OPEN'" class="flex items-center justify-end gap-1">
          <Tooltip text="Resolve signal">
            <Button
              size="xs"
              variant="ghost"
              aria-label="Resolve signal"
              :loading="acting === row.id"
              @click="resolve(String(row.id))"
            >
              <Check class="size-3.5" />
            </Button>
          </Tooltip>
          <Tooltip text="Suppress signal">
            <Button
              size="xs"
              variant="ghost"
              aria-label="Suppress signal"
              :loading="acting === row.id"
              @click="suppress(String(row.id))"
            >
              <Ban class="size-3.5" />
            </Button>
          </Tooltip>
        </div>
      </template>
    </DataTable>

    <div v-if="nextCursor" class="flex justify-center mt-3">
      <Button variant="ghost" @click="store.loadMore()">Load more</Button>
    </div>
  </div>
</template>
