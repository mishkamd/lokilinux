<script setup lang="ts">
import { Check, CheckCheck, RefreshCw } from 'lucide-vue-next'

const store = useIncidentsStore()
const router = useRouter()
const { incidents, total, loading, nextCursor, filters } = storeToRefs(store)
const { severityColor } = useSeverity()
const toast = useToast()
const { format: fmtDateTime } = useDateTime()

const STATUSES = ['', 'OPEN', 'ACKNOWLEDGED', 'IN_PROGRESS', 'RESOLVED', 'CLOSED']
const SEVERITIES = ['', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']

const columns = [
  { key: 'severity', label: 'Severity' },
  { key: 'title', label: 'Incident' },
  { key: 'type', label: 'Type' },
  { key: 'status', label: 'Status' },
  { key: 'started_at', label: 'Started' },
  { key: 'actions', label: '' },
]

const statusColor = (s: string) =>
  ({
    OPEN: 'red', ACKNOWLEDGED: 'amber', IN_PROGRESS: 'blue', RESOLVED: 'green', CLOSED: 'gray',
  } as Record<string, string>)[s] ?? 'gray'

const openCount = computed(() => incidents.value.filter((i) => i.status === 'OPEN').length)
const acting = ref<string | null>(null)

async function ack(id: string) {
  acting.value = id
  try {
    await store.ackIncident(id)
  } catch {
    toast.add({ title: 'Error', description: 'Failed to acknowledge incident', color: 'red' })
  } finally {
    acting.value = null
  }
}

async function resolve(id: string) {
  acting.value = id
  try {
    await store.resolveIncident(id)
  } catch {
    toast.add({ title: 'Error', description: 'Failed to resolve incident', color: 'red' })
  } finally {
    acting.value = null
  }
}

onMounted(() => store.fetchIncidents())
</script>

<template>
  <div>
    <PageHeader>
      <div class="flex flex-wrap items-center gap-3">
        <Select v-model="filters.status" :options="STATUSES" placeholder="Status" class="w-40" @change="store.fetchIncidents()" />
        <Select v-model="filters.severity" :options="SEVERITIES" placeholder="Severity" class="w-40" @change="store.fetchIncidents()" />
        <Button variant="outline" @click="store.fetchIncidents()">
          <RefreshCw class="size-4" />
          Refresh
        </Button>
      </div>
      <div class="flex items-center gap-3">
        <Badge color="red">{{ openCount }} open</Badge>
        <Badge color="gray">{{ total }} total</Badge>
      </div>
    </PageHeader>

    <DataTable
      :rows="incidents"
      :columns="columns"
      :loading="loading"
      sortable
      :page-size="25"
      empty-title="No incidents"
      empty-description="Incidents appear here when correlated signals cross their thresholds."
      rows-clickable
      @row-click="(row) => router.push(`/incidents/${row.id}`)"
    >
      <template #severity-data="{ row }">
        <Badge :color="severityColor(String(row.severity))" size="xs">{{ row.severity }}</Badge>
      </template>
      <template #title-data="{ row }">
        <p class="font-medium leading-tight">{{ row.title }}</p>
      </template>
      <template #type-data="{ row }">
        <span class="text-xs text-muted-foreground">{{ row.type }}</span>
      </template>
      <template #status-data="{ row }">
        <Badge :color="statusColor(String(row.status))" size="xs">{{ row.status }}</Badge>
      </template>
      <template #started_at-data="{ row }">
        <span class="font-mono text-xs text-muted-foreground">{{ fmtDateTime(String(row.started_at)) }}</span>
      </template>
      <template #actions-data="{ row }">
        <div class="flex items-center justify-end gap-1" @click.stop>
          <Tooltip v-if="row.status === 'OPEN'" text="Acknowledge incident">
            <Button
              size="xs"
              variant="ghost"
              aria-label="Acknowledge incident"
              :loading="acting === row.id"
              @click="ack(String(row.id))"
            >
              <Check class="size-3.5" />
            </Button>
          </Tooltip>
          <Tooltip v-if="!['RESOLVED', 'CLOSED'].includes(String(row.status))" text="Resolve incident">
            <Button
              size="xs"
              variant="ghost"
              aria-label="Resolve incident"
              :loading="acting === row.id"
              @click="resolve(String(row.id))"
            >
              <CheckCheck class="size-3.5" />
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
