<script setup lang="ts">
import { RefreshCw } from 'lucide-vue-next'
import type { RemediationPlanStatus } from '~/stores/compliance'

const store = useComplianceStore()
const { remediationPlans, remediationTotal, remediationLoading, remediationFilters } = storeToRefs(store)

onMounted(() => store.fetchRemediationPlans())

const STATUS_COLORS: Record<RemediationPlanStatus, string> = {
  DRAFT: 'gray', PENDING_APPROVAL: 'amber', APPROVED: 'amber',
  EXECUTING: 'amber', COMPLETED: 'green', FAILED: 'red', ROLLED_BACK: 'gray',
}
const STATUSES: RemediationPlanStatus[] = ['DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'EXECUTING', 'COMPLETED', 'FAILED', 'ROLLED_BACK']

const columns = [
  { key: 'name', label: 'Plan' },
  { key: 'status', label: 'Status' },
  { key: 'trigger_type', label: 'Trigger' },
  { key: 'is_emergency', label: 'Emergency' },
  { key: 'created_at', label: 'Created' },
]
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div class="flex flex-wrap items-center gap-3">
        <Select v-model="remediationFilters.status" :options="['', ...STATUSES]" placeholder="Status" class="w-48"
                @change="store.fetchRemediationPlans()" />
        <Button variant="outline" @click="store.fetchRemediationPlans()">
          <RefreshCw class="size-4" /> Refresh
        </Button>
      </div>
      <Badge color="gray">{{ remediationTotal }} plans</Badge>
    </div>

    <DataTable :rows="remediationPlans" :columns="columns" :loading="remediationLoading" rows-clickable
               @row-click="(row) => navigateTo(`/compliance/remediation/${row.id}`)">
      <template #status-data="{ row }">
        <Badge :color="STATUS_COLORS[row.status as RemediationPlanStatus] ?? 'gray'" size="xs">{{ row.status }}</Badge>
      </template>
      <template #is_emergency-data="{ row }">
        <Badge v-if="row.is_emergency" color="red" size="xs">Emergency</Badge>
        <span v-else class="text-muted-foreground text-sm">—</span>
      </template>
      <template #created_at-data="{ row }">
        <span class="font-mono text-xs">{{ new Date(String(row.created_at)).toLocaleDateString() }}</span>
      </template>
    </DataTable>
  </div>
</template>
