<script setup lang="ts">
import { RefreshCw } from 'lucide-vue-next'

const store = useComplianceStore()
const { driftEvents, driftTotal, driftLoading, driftNextCursor, driftFilters } = storeToRefs(store)
const { canEdit } = useCurrentUser()

onMounted(() => store.fetchDriftEvents())

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'red', HIGH: 'red', MEDIUM: 'amber', LOW: 'gray',
}

const STATUS_COLORS: Record<string, string> = {
  OPEN: 'red', ACKNOWLEDGED: 'amber', IN_REMEDIATION: 'amber',
  RESOLVED: 'green', SUPPRESSED: 'gray', EXCEPTION: 'gray',
}

const columns = [
  { key: 'time', label: 'Detected' },
  { key: 'agent_id', label: 'Server' },
  { key: 'domain', label: 'Domain' },
  { key: 'severity', label: 'Severity' },
  { key: 'occurrences', label: 'Occurrences' },
  { key: 'status', label: 'Status' },
  { key: 'actions', label: '' },
]

async function onSuppress(id: string) {
  await store.suppressDrift(id)
}
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div class="flex flex-wrap items-center gap-3">
        <Select v-model="driftFilters.severity" :options="['', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW']"
                placeholder="Severity" class="w-36" @change="store.fetchDriftEvents()" />
        <Input v-model="driftFilters.domain" placeholder="Filter by domain" class="w-48"
               @keyup.enter="store.fetchDriftEvents()" />
        <Select v-model="driftFilters.status"
                :options="[{ label: 'All', value: '' }, { label: 'Open', value: 'OPEN' }, { label: 'Acknowledged', value: 'ACKNOWLEDGED' }, { label: 'Resolved', value: 'RESOLVED' }, { label: 'Suppressed', value: 'SUPPRESSED' }]"
                placeholder="Status" class="w-44" @change="store.fetchDriftEvents()" />
        <Button variant="outline" @click="store.fetchDriftEvents()">
          <RefreshCw class="size-4" /> Refresh
        </Button>
      </div>
      <Badge color="gray">{{ driftTotal }} drift events</Badge>
    </div>

    <DataTable :rows="driftEvents" :columns="columns" :loading="driftLoading" rows-clickable
               @row-click="(row) => navigateTo(`/compliance/drift/${row.id}`)">
      <template #time-data="{ row }">
        <span class="font-mono text-xs">{{ new Date(String(row.time)).toLocaleString() }}</span>
      </template>
      <template #domain-data="{ row }">
        <Badge color="gray" size="xs">{{ row.domain }}</Badge>
      </template>
      <template #severity-data="{ row }">
        <Badge :color="SEVERITY_COLORS[String(row.severity)] ?? 'gray'" size="xs">{{ row.severity }}</Badge>
      </template>
      <template #occurrences-data="{ row }">
        <span class="font-mono text-xs text-muted-foreground">{{ row.occurrences }}×</span>
      </template>
      <template #status-data="{ row }">
        <Badge :color="STATUS_COLORS[String(row.status)] ?? 'gray'" size="xs">{{ row.status }}</Badge>
      </template>
      <template #actions-data="{ row }">
        <div v-if="canEdit" class="flex items-center gap-1">
          <Button v-if="row.status === 'OPEN'" size="xs" variant="ghost" @click.stop="store.acknowledgeDrift(String(row.id))">
            Acknowledge
          </Button>
          <Button v-if="['OPEN', 'ACKNOWLEDGED'].includes(String(row.status))" size="xs" variant="ghost" @click.stop="store.resolveDrift(String(row.id))">
            Resolve
          </Button>
          <Button v-if="['OPEN', 'ACKNOWLEDGED'].includes(String(row.status))" size="xs" variant="ghost" @click.stop="onSuppress(String(row.id))">
            Suppress
          </Button>
        </div>
      </template>
    </DataTable>

    <div v-if="driftNextCursor" class="mt-4 flex justify-center">
      <Button variant="outline" @click="store.fetchDriftEvents(driftNextCursor!)">
        Load more
      </Button>
    </div>
  </div>
</template>
