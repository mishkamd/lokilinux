<script setup lang="ts">
const store = useVulnerabilitiesStore()
const {
  summary, summaryLoading, trend, trendLoading, trendRange,
  topResources, topResourcesLoading, patchable, patchableLoading,
  cves, cvesLoading,
} = storeToRefs(store)

onMounted(() => {
  store.fetchSummary()
  store.fetchTrend()
  store.fetchTopResources()
  store.fetchPatchable()
  store.fetchCves() // top-of-catalog, used for the "Top Vulnerabilities" table below
})

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'red', HIGH: 'orange', MEDIUM: 'amber', LOW: 'green',
}

function deltaLabel(pct: number | null): string | null {
  if (pct === null) return null
  const sign = pct > 0 ? '+' : ''
  return `${sign}${pct.toFixed(0)}%`
}
function deltaColor(pct: number | null): string {
  if (pct === null) return 'gray'
  return pct > 0 ? 'red' : pct < 0 ? 'green' : 'gray'
}

const resourceColumns = [
  { key: 'hostname', label: 'Resource' },
  { key: 'environment', label: 'Environment' },
  { key: 'critical', label: 'Critical' },
  { key: 'high', label: 'High' },
  { key: 'medium', label: 'Medium' },
  { key: 'total', label: 'Total' },
]

const patchableColumns = [
  { key: 'cve_id', label: 'CVE' },
  { key: 'cvss_v3_severity', label: 'Severity' },
  { key: 'package_name', label: 'Package' },
  { key: 'fixed_version', label: 'Fix' },
  { key: 'affected_count', label: 'Affected' },
]

const topVulnColumns = [
  { key: 'cve_id', label: 'CVE' },
  { key: 'cvss_v3_score', label: 'CVSS' },
  { key: 'cvss_v3_severity', label: 'Severity' },
  { key: 'affected_count', label: 'Affected' },
  { key: 'published_date', label: 'Published' },
]

const topVulnerabilities = computed(() => [...cves.value].slice(0, 10))
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-1">
      <div>
        <h1 class="page-title">Vulnerability Management</h1>
        <p class="text-sm text-muted-foreground">Security posture and vulnerability exposure across your Linux fleet</p>
      </div>
      <Button variant="outline" to="/vulnerabilities/list">Browse catalog</Button>
    </div>

    <!-- KPI cards -->
    <div class="grid grid-cols-2 sm:grid-cols-5 gap-3 my-4">
      <Card>
        <p class="label-caps">Resources scanned</p>
        <p class="data-value">{{ summaryLoading ? '…' : (summary?.resources_scanned ?? 0) }}<span class="text-sm text-muted-foreground font-normal"> / {{ summary?.resources_total ?? 0 }}</span></p>
      </Card>
      <Card>
        <p class="label-caps">Critical</p>
        <div class="flex items-baseline gap-2">
          <p class="data-value text-destructive">{{ summaryLoading ? '…' : (summary?.critical ?? 0) }}</p>
          <Badge v-if="deltaLabel(summary?.critical_delta_pct ?? null)" :color="deltaColor(summary?.critical_delta_pct ?? null)" size="xs">
            {{ deltaLabel(summary?.critical_delta_pct ?? null) }}
          </Badge>
        </div>
      </Card>
      <Card>
        <p class="label-caps">High</p>
        <div class="flex items-baseline gap-2">
          <p class="data-value" style="color: #f97316">{{ summaryLoading ? '…' : (summary?.high ?? 0) }}</p>
          <Badge v-if="deltaLabel(summary?.high_delta_pct ?? null)" :color="deltaColor(summary?.high_delta_pct ?? null)" size="xs">
            {{ deltaLabel(summary?.high_delta_pct ?? null) }}
          </Badge>
        </div>
      </Card>
      <Card>
        <p class="label-caps">Medium</p>
        <div class="flex items-baseline gap-2">
          <p class="data-value text-warning">{{ summaryLoading ? '…' : (summary?.medium ?? 0) }}</p>
          <Badge v-if="deltaLabel(summary?.medium_delta_pct ?? null)" :color="deltaColor(summary?.medium_delta_pct ?? null)" size="xs">
            {{ deltaLabel(summary?.medium_delta_pct ?? null) }}
          </Badge>
        </div>
      </Card>
      <Card>
        <p class="label-caps">Low</p>
        <p class="data-value text-success">{{ summaryLoading ? '…' : (summary?.low ?? 0) }}</p>
      </Card>
    </div>
    <p class="text-xs text-muted-foreground -mt-3 mb-4">
      Open exposure on your fleet right now — not the full
      <NuxtLink to="/vulnerabilities/list" class="text-primary hover:underline">CVE Catalog</NuxtLink>.
    </p>

    <!-- Trend -->
    <div class="mb-4">
      <VulnerabilityTrendChart
        :points="trend" :loading="trendLoading" :range="trendRange"
        @update:range="store.fetchTrend($event)"
      />
    </div>

    <!-- Top resources / patchable -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
      <Card>
        <template #header>
          <div class="flex items-center justify-between">
            <p class="label-caps">Top Vulnerable Resources</p>
            <Button variant="ghost" size="xs" to="/servers">View all</Button>
          </div>
        </template>
        <Skeleton v-if="topResourcesLoading" class="h-40 w-full" />
        <p v-else-if="topResources.length === 0" class="text-sm text-muted-foreground py-6 text-center">No open vulnerabilities on any scanned resource.</p>
        <DataTable v-else :rows="topResources" :columns="resourceColumns" row-key="agent_id" rows-clickable
                   @row-click="(row) => navigateTo(`/servers/${row.agent_id}`)">
          <template #hostname-data="{ row }">
            <span class="font-mono text-xs">{{ row.hostname || row.agent_id }}</span>
          </template>
          <template #environment-data="{ row }">
            <Badge v-if="row.environment" color="gray" size="xs">{{ row.environment }}</Badge>
            <span v-else class="text-muted-foreground text-xs">—</span>
          </template>
          <template #critical-data="{ row }"><span class="font-mono text-xs">{{ row.critical || '—' }}</span></template>
          <template #high-data="{ row }"><span class="font-mono text-xs">{{ row.high || '—' }}</span></template>
          <template #medium-data="{ row }"><span class="font-mono text-xs">{{ row.medium || '—' }}</span></template>
          <template #total-data="{ row }"><span class="font-mono text-xs font-semibold">{{ row.total }}</span></template>
        </DataTable>
      </Card>

      <Card>
        <template #header><p class="label-caps">Top Patchable Vulnerabilities</p></template>
        <Skeleton v-if="patchableLoading" class="h-40 w-full" />
        <p v-else-if="patchable.length === 0" class="text-sm text-muted-foreground py-6 text-center">No patchable vulnerabilities found.</p>
        <DataTable v-else :rows="patchable" :columns="patchableColumns" rows-clickable
                   @row-click="(row) => navigateTo(`/vulnerabilities/${row.cve_id}`)">
          <template #cve_id-data="{ row }"><span class="font-mono text-xs text-primary">{{ row.cve_id }}</span></template>
          <template #cvss_v3_severity-data="{ row }">
            <Badge v-if="row.cvss_v3_severity" :color="SEVERITY_COLORS[String(row.cvss_v3_severity)] ?? 'gray'" size="xs">{{ row.cvss_v3_severity }}</Badge>
            <span v-else class="text-muted-foreground text-xs">—</span>
          </template>
          <template #fixed_version-data="{ row }"><span class="font-mono text-xs">{{ row.fixed_version || '—' }}</span></template>
        </DataTable>
      </Card>
    </div>

    <!-- Top vulnerabilities -->
    <Card>
      <template #header>
        <div class="flex items-center justify-between">
          <p class="label-caps">Top Vulnerabilities</p>
          <Button variant="ghost" size="xs" to="/vulnerabilities/list">View all</Button>
        </div>
      </template>
      <Skeleton v-if="cvesLoading" class="h-48 w-full" />
      <p v-else-if="topVulnerabilities.length === 0" class="text-sm text-muted-foreground py-6 text-center">No CVEs recorded yet.</p>
      <DataTable v-else :rows="topVulnerabilities" :columns="topVulnColumns" rows-clickable
                 @row-click="(row) => navigateTo(`/vulnerabilities/${row.cve_id}`)">
        <template #cve_id-data="{ row }"><span class="font-mono text-xs text-primary">{{ row.cve_id }}</span></template>
        <template #cvss_v3_score-data="{ row }">{{ row.cvss_v3_score ?? '—' }}</template>
        <template #cvss_v3_severity-data="{ row }">
          <Badge v-if="row.cvss_v3_severity" :color="SEVERITY_COLORS[String(row.cvss_v3_severity)] ?? 'gray'" size="xs">{{ row.cvss_v3_severity }}</Badge>
          <span v-else class="text-muted-foreground text-xs">—</span>
        </template>
        <template #published_date-data="{ row }">
          <span class="font-mono text-xs">{{ row.published_date ? new Date(String(row.published_date)).toLocaleDateString() : '—' }}</span>
        </template>
      </DataTable>
    </Card>
  </div>
</template>
