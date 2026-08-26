<script setup lang="ts">
import { Download, RefreshCw, Search } from 'lucide-vue-next'

const store = useVulnerabilitiesStore()
const api = useApi()
const toast = useToast()
const { cves, cvesTotal, cvesLoading, cvesNextCursor, cveFilters, cveSummaryBySeverity } = storeToRefs(store)

onMounted(() => store.fetchCves())

const exporting = ref<'csv' | 'json' | null>(null)
async function exportCves(format: 'csv' | 'json') {
  exporting.value = format
  try {
    const params = new URLSearchParams({ format })
    if (cveFilters.value.severity) params.set('severity', cveFilters.value.severity)
    if (cveFilters.value.exploited_only) params.set('exploited_only', 'true')
    const blob = await api.get<Blob>(`/vulnerabilities/export?${params}`, { responseType: 'blob' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `vulnerabilities.${format}`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Export failed', color: 'red' })
  } finally {
    exporting.value = null
  }
}

const SEVERITIES = ['', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW']

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'red', HIGH: 'orange', MEDIUM: 'amber', LOW: 'green',
}

// Tailwind needs literal class strings at build time — a `text-${x}` runtime
// template gets purged. Static lookup instead, same set of colors.
const SEVERITY_TEXT_CLASS: Record<string, string> = {
  CRITICAL: 'text-destructive', HIGH: 'text-[var(--severity-high)]',
  MEDIUM: 'text-warning', LOW: 'text-success',
}

const columns = [
  { key: 'cve_id', label: 'CVE ID' },
  { key: 'cvss_v3_severity', label: 'Severity' },
  { key: 'cvss_v3_score', label: 'CVSS' },
  { key: 'affected_count', label: 'Servers Affected' },
  { key: 'is_actively_exploited', label: 'Exploited' },
  { key: 'published_date', label: 'Published' },
]

const summaryCards = computed(() => [
  { label: 'Critical', count: cveSummaryBySeverity.value.CRITICAL, color: 'CRITICAL' },
  { label: 'High',     count: cveSummaryBySeverity.value.HIGH,     color: 'HIGH' },
  { label: 'Medium',   count: cveSummaryBySeverity.value.MEDIUM,   color: 'MEDIUM' },
  { label: 'Low',      count: cveSummaryBySeverity.value.LOW,      color: 'LOW' },
])

function filterBySeverity(sev: string) {
  cveFilters.value.severity = sev
  store.fetchCves()
}
</script>

<template>
  <div>
    <div class="grid grid-cols-4 gap-3 mb-4">
      <Card
        v-for="card in summaryCards" :key="card.label"
        class="cursor-pointer hover:shadow-md transition-shadow"
        @click="filterBySeverity(card.color)"
      >
        <div class="text-center">
          <p class="text-xl font-bold font-mono" :class="SEVERITY_TEXT_CLASS[card.color] ?? 'text-foreground'">
            {{ card.count }}
          </p>
          <p class="text-sm text-muted-foreground mt-1">{{ card.label }}</p>
        </div>
      </Card>
    </div>

    <PageHeader>
      <div class="flex flex-wrap items-center gap-3">
        <div class="relative w-56">
          <Search class="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input v-model="cveFilters.search" placeholder="Search CVE ID..." class="pl-9" @keyup.enter="store.fetchCves()" />
        </div>
        <Select v-model="cveFilters.severity" :options="SEVERITIES" placeholder="Severity" class="w-36" @change="store.fetchCves()" />
        <Checkbox v-model="cveFilters.exploited_only" label="Actively exploited" @change="store.fetchCves()" />
        <Button variant="outline" @click="store.fetchCves()">
          <RefreshCw class="size-4" /> Refresh
        </Button>
        <Button variant="outline" size="sm" :loading="exporting === 'csv'" @click="exportCves('csv')">
          <Download class="size-3.5" /> CSV
        </Button>
        <Button variant="outline" size="sm" :loading="exporting === 'json'" @click="exportCves('json')">
          <Download class="size-3.5" /> JSON
        </Button>
      </div>
      <Badge color="gray">{{ cvesTotal }} CVEs</Badge>
    </PageHeader>

    <DataTable
      :rows="cves"
      :columns="columns"
      :loading="cvesLoading"
      sortable
      :page-size="25"
      empty-title="No CVEs recorded yet"
      rows-clickable
      @row-click="(row) => navigateTo(`/vulnerabilities/${row.cve_id}`)"
    >
      <template #cve_id-data="{ row }">
        <span class="font-mono text-sm text-primary">{{ row.cve_id }}</span>
      </template>
      <template #cvss_v3_severity-data="{ row }">
        <Badge v-if="row.cvss_v3_severity" :color="SEVERITY_COLORS[String(row.cvss_v3_severity)] ?? 'gray'" size="xs">{{ row.cvss_v3_severity }}</Badge>
        <span v-else class="text-muted-foreground">—</span>
      </template>
      <template #cvss_v3_score-data="{ row }"><span class="font-mono">{{ row.cvss_v3_score ?? '—' }}</span></template>
      <template #affected_count-data="{ row }"><span class="font-mono">{{ row.affected_count }}</span></template>
      <template #is_actively_exploited-data="{ row }">
        <Badge v-if="row.is_actively_exploited" color="red" size="xs">Yes</Badge>
        <span v-else class="text-muted-foreground text-sm">No</span>
      </template>
      <template #published_date-data="{ row }">
        <span class="font-mono">{{ row.published_date ? new Date(String(row.published_date)).toLocaleDateString() : '—' }}</span>
      </template>
    </DataTable>

    <div v-if="cvesNextCursor" class="mt-4 flex justify-center">
      <Button variant="outline" @click="store.fetchCves(cvesNextCursor!)">Load more</Button>
    </div>
  </div>
</template>
