<script setup lang="ts">
import { RefreshCw } from 'lucide-vue-next'

const store = useComplianceStore()
const { standards, standardsLoading } = storeToRefs(store)

onMounted(() => store.fetchStandards())

const columns = [
  { key: 'name', label: 'Standard' },
  { key: 'version', label: 'Version' },
  { key: 'rules_total', label: 'Rules' },
  { key: 'executable', label: 'Executable' },
  { key: 'reference_only', label: 'Reference-only' },
  { key: 'coverage_executable_pct', label: 'Coverage' },
]

function coverageColor(pct: number): string {
  if (pct >= 75) return 'green'
  if (pct >= 25) return 'amber'
  return 'red'
}
</script>

<template>
  <div>
    <PageHeader
      title="Standards"
      description="Every framework version this catalog knows about — honest executable-vs-reference coverage, not an assumed 100%."
    >
      <template #actions>
        <Button variant="outline" @click="store.fetchStandards()">
          <RefreshCw class="size-4" /> Refresh
        </Button>
      </template>
    </PageHeader>

    <DataTable
      :rows="standards"
      :columns="columns"
      :loading="standardsLoading"
      sortable
      :page-size="25"
      empty-title="No standards mapped yet"
      empty-description="Import ComplianceAsCode content or load curated rule packs to populate framework coverage."
      rows-clickable
      @row-click="(row) => navigateTo(`/compliance/standards/${row.key}/${row.version}`)"
    >
      <template #name-data="{ row }">
        <div>
          <p class="text-sm">{{ row.name }}</p>
          <p v-if="row.publisher" class="text-xs text-muted-foreground">{{ row.publisher }}</p>
        </div>
      </template>
      <template #version-data="{ row }">
        <span class="font-mono text-xs">{{ row.version }}</span>
      </template>
      <template #rules_total-data="{ row }">
        <span class="font-mono text-xs">{{ row.rules_total }}</span>
      </template>
      <template #executable-data="{ row }">
        <span class="font-mono text-xs">{{ row.executable }}</span>
      </template>
      <template #reference_only-data="{ row }">
        <span class="font-mono text-xs text-muted-foreground">{{ row.reference_only }}</span>
      </template>
      <template #coverage_executable_pct-data="{ row }">
        <Badge :color="coverageColor(row.coverage_executable_pct)" size="xs">{{ row.coverage_executable_pct }}%</Badge>
      </template>
    </DataTable>
  </div>
</template>
