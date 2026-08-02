<script setup lang="ts">
const route = useRoute()
const policySetId = String(route.params.id)

const store = useComplianceStore()
const { selectedPolicySet, policySetRules, policySetCoverage } = storeToRefs(store)

onMounted(async () => {
  await store.fetchPolicySet(policySetId)
  await Promise.all([store.fetchPolicySetRules(policySetId), store.fetchPolicySetCoverage(policySetId)])
})

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'red', HIGH: 'red', MEDIUM: 'amber', LOW: 'gray',
}

const tabs = [
  { label: 'Rules', slot: 'rules' },
  { label: 'Coverage', slot: 'coverage' },
]

const columns = [
  { key: 'title', label: 'Rule' },
  { key: 'domain', label: 'Domain' },
  { key: 'severity', label: 'Severity' },
  { key: 'check_source', label: 'Coverage' },
]
</script>

<template>
  <div v-if="selectedPolicySet">
    <div class="flex items-center justify-between mb-4">
      <div>
        <h2 class="text-lg font-semibold">{{ selectedPolicySet.name }}</h2>
        <p class="text-sm text-muted-foreground">{{ selectedPolicySet.description || 'No description' }}</p>
      </div>
      <Badge color="gray">{{ selectedPolicySet.framework }}</Badge>
    </div>

    <AppTabs :items="tabs">
      <template #rules>
        <DataTable :rows="policySetRules" :columns="columns">
          <template #domain-data="{ row }"><Badge color="gray" size="xs">{{ row.domain }}</Badge></template>
          <template #severity-data="{ row }">
            <Badge :color="SEVERITY_COLORS[String(row.severity)] ?? 'gray'" size="xs">{{ row.severity }}</Badge>
          </template>
          <template #check_source-data="{ row }">
            <Badge :color="row.check_source === 'CEL' ? 'green' : 'gray'" size="xs">{{ row.check_source }}</Badge>
          </template>
        </DataTable>
      </template>

      <template #coverage>
        <div v-if="policySetCoverage" class="grid grid-cols-3 gap-4">
          <Card>
            <p class="text-xs text-muted-foreground">CEL-mapped (evaluable)</p>
            <p class="text-2xl font-semibold">{{ policySetCoverage.mapped }}</p>
          </Card>
          <Card>
            <p class="text-xs text-muted-foreground">Unmapped</p>
            <p class="text-2xl font-semibold">{{ policySetCoverage.unmapped }}</p>
          </Card>
          <Card>
            <p class="text-xs text-muted-foreground">Coverage</p>
            <p class="text-2xl font-semibold">{{ policySetCoverage.coverage_pct }}%</p>
          </Card>
        </div>
      </template>
    </AppTabs>
  </div>
  <Skeleton v-else class="h-64 w-full" />
</template>
