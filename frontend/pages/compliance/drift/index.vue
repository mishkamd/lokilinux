<script setup lang="ts">
import { RefreshCw } from 'lucide-vue-next'

const store = useComplianceStore()
const { driftEvents, driftTotal, driftLoading, driftFilters } = storeToRefs(store)
const { canEdit } = useCurrentUser()

onMounted(() => store.fetchDriftEvents())

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'red', HIGH: 'red', MEDIUM: 'amber', LOW: 'gray',
}

const columns = [
  { key: 'time', label: 'Detected' },
  { key: 'agent_id', label: 'Server' },
  { key: 'domain', label: 'Domain' },
  { key: 'severity', label: 'Severity' },
  { key: 'change_type', label: 'Change' },
  { key: 'acknowledged_at', label: 'Status' },
]
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div class="flex flex-wrap items-center gap-3">
        <Select v-model="driftFilters.severity" :options="['', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW']"
                placeholder="Severity" class="w-36" @change="store.fetchDriftEvents()" />
        <Input v-model="driftFilters.domain" placeholder="Filter by domain" class="w-48"
               @keyup.enter="store.fetchDriftEvents()" />
        <Select v-model="driftFilters.acknowledged" :options="[{ label: 'All', value: '' }, { label: 'Open', value: 'false' }, { label: 'Acknowledged', value: 'true' }]"
                placeholder="Status" class="w-40" @change="store.fetchDriftEvents()" />
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
      <template #acknowledged_at-data="{ row }">
        <Badge v-if="row.acknowledged_at" color="green" size="xs">Acknowledged</Badge>
        <Button v-else-if="canEdit" size="xs" variant="ghost" @click.stop="store.acknowledgeDrift(String(row.id))">
          Acknowledge
        </Button>
        <span v-else class="text-muted-foreground text-sm">Open</span>
      </template>
    </DataTable>
  </div>
</template>
