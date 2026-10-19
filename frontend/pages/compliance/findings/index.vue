<script setup lang="ts">
import { SEVERITY_COLORS } from '~/utils/complianceColors'
import { RefreshCw } from 'lucide-vue-next'

const store = useComplianceStore()
const { findings, findingsTotal, findingsLoading, findingsNextCursor, findingFilters } = storeToRefs(store)
const { canEdit } = useCurrentUser()
const { format: fmtDateTime } = useDateTime()

onMounted(() => store.fetchFindings())

const RESULT_COLORS: Record<string, string> = {
  FAIL: 'red',
  ERROR: 'red',
  UNKNOWN: 'amber',
  PASS: 'green',
  NOT_APPLICABLE: 'gray',
  NOT_EVALUATED: 'gray',
}

const columns = [
  { key: 'time', label: 'Last seen' },
  { key: 'agent_id', label: 'Server' },
  { key: 'title', label: 'Rule' },
  { key: 'domain', label: 'Domain' },
  { key: 'severity', label: 'Severity' },
  { key: 'result', label: 'Result' },
  { key: 'actions', label: '' },
]
</script>

<template>
  <div>
    <PageHeader>
      <div class="flex flex-wrap items-center gap-3">
        <Select v-model="findingFilters.severity" :options="['', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW']"
                placeholder="Severity" class="w-36" @change="store.fetchFindings()" />
        <Input v-model="findingFilters.domain" placeholder="Filter by domain" class="w-48"
               @keyup.enter="store.fetchFindings()" />
        <Select v-model="findingFilters.result"
                :options="[{ label: 'Failing (default)', value: 'FAIL' }, { label: 'Unknown', value: 'UNKNOWN' }, { label: 'All', value: '' }]"
                placeholder="Result" class="w-44" @change="store.fetchFindings()" />
        <Button variant="outline" @click="store.fetchFindings()">
          <RefreshCw class="size-4" /> Refresh
        </Button>
      </div>
      <Badge color="gray">{{ findingsTotal }} findings</Badge>
    </PageHeader>

    <DataTable
      :rows="findings"
      :columns="columns"
      :loading="findingsLoading"
      sortable
      :page-size="25"
      empty-title="No findings"
      empty-description="Nothing matches these filters — the fleet may simply be compliant."
      rows-clickable
      @row-click="(row) => navigateTo(`/compliance/findings/${row.id}`)"
    >
      <template #time-data="{ row }">
        <span class="font-mono text-xs">{{ fmtDateTime(String(row.time)) }}</span>
      </template>
      <template #agent_id-data="{ row }">
        <span class="font-mono text-xs">{{ row.hostname || row.agent_id }}</span>
      </template>
      <template #title-data="{ row }">
        <div>
          <p class="text-sm">{{ row.title }}</p>
          <p class="font-mono text-xs text-muted-foreground">{{ row.rule_key }}</p>
        </div>
      </template>
      <template #domain-data="{ row }">
        <Badge color="gray" size="xs">{{ row.domain }}</Badge>
      </template>
      <template #severity-data="{ row }">
        <Badge :color="SEVERITY_COLORS[String(row.severity)] ?? 'gray'" size="xs">{{ row.severity }}</Badge>
      </template>
      <template #result-data="{ row }">
        <Badge :color="RESULT_COLORS[String(row.result)] ?? 'gray'" size="xs">{{ row.result }}</Badge>
      </template>
      <template #actions-data="{ row }">
        <div v-if="canEdit" class="flex items-center gap-1">
          <Button v-if="!row.acknowledged_at" size="xs" variant="ghost" @click.stop="store.acknowledgeFinding(String(row.id))">
            Acknowledge
          </Button>
        </div>
      </template>
    </DataTable>

    <div v-if="findingsNextCursor" class="mt-4 flex justify-center">
      <Button variant="outline" @click="store.fetchFindings(findingsNextCursor!)">
        Load more
      </Button>
    </div>
  </div>
</template>
