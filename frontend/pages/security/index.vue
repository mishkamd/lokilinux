<script setup lang="ts">
import { ShieldAlert, Bug, RadioTower, ScanSearch } from 'lucide-vue-next'

const vulnerabilities = useVulnerabilitiesStore()
const signals = useSignalsStore()
const dashboard = useDashboardStore()

const {
  summary, summaryLoading,
  topResources, topResourcesLoading,
  patchable, patchableLoading,
} = storeToRefs(vulnerabilities)
const { signals: activeSignals } = storeToRefs(signals)
const { recentFailedJobs, recentFailedJobsLoading } = storeToRefs(dashboard)

onMounted(() => {
  dashboard.ensureSummary()
  vulnerabilities.fetchSummary()
  vulnerabilities.fetchTopResources()
  vulnerabilities.fetchPatchable()
  // Security-relevant slice only: unresolved HIGH/CRITICAL signals.
  signals.filters.status = 'OPEN'
  signals.fetchSignals().then(() => {
    const highish = new Set(['HIGH', 'CRITICAL'])
    // client-side narrow: the API has no multi-severity filter
    signals.signals = signals.signals.filter((s) => highish.has(s.severity))
  })
})

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'red', HIGH: 'red', MEDIUM: 'amber', LOW: 'gray',
}

const scannedPct = computed(() => {
  if (!summary.value || !summary.value.resources_total) return null
  return (summary.value.resources_scanned / summary.value.resources_total) * 100
})

const criticalSignals = computed(() =>
  activeSignals.value.filter((s) => s.severity === 'CRITICAL').length,
)
</script>

<template>
  <div>
    <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3 mb-4">
      <MetricCard
        :icon="Bug"
        label="Unresolved CVEs"
        :value="dashboard.summary?.vulnerabilities.unresolved_total ?? '—'"
        chart-color="red"
        to="/vulnerabilities"
      />
      <MetricCard
        :icon="ShieldAlert"
        label="Critical vulns"
        :value="summary?.critical ?? (summaryLoading ? '…' : '—')"
        subtitle="open findings"
        chart-color="red"
        to="/vulnerabilities?severity=CRITICAL"
      />
      <MetricCard
        :icon="RadioTower"
        label="Critical signals"
        :value="criticalSignals"
        subtitle="active HIGH/CRIT"
        chart-color="yellow"
        to="/signals"
      />
      <MetricCard
        :icon="ScanSearch"
        label="Scan coverage"
        :value="scannedPct != null ? `${Math.round(scannedPct)}%` : '—'"
        :subtitle="summary ? `${summary.resources_scanned}/${summary.resources_total} resources` : ''"
        to="/agents"
      />
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-3 mb-4 items-start">
      <VulnerabilitySeverityDonut :by-severity="dashboard.summary?.vulnerabilities.by_severity ?? {}" />

      <Card class="lg:col-span-2">
        <template #header>
          <div class="flex items-center justify-between">
            <p class="label-caps">Patchable now</p>
            <Button variant="ghost" size="xs" to="/vulnerabilities">View all</Button>
          </div>
        </template>
        <Skeleton v-if="patchableLoading" class="h-24 w-full" />
        <EmptyState v-else-if="patchable.length === 0">
          Nothing patchable right now — every open CVE with an available fix is already tracked.
        </EmptyState>
        <ul v-else class="divide-y divide-border">
          <li v-for="p in patchable.slice(0, 6)" :key="`${p.cve_id}-${p.package_name}`" class="py-2 flex items-center justify-between gap-2">
            <div class="min-w-0">
              <NuxtLink
                :to="`/vulnerabilities/${p.cve_id}`"
                class="text-sm font-mono font-medium hover:underline hover:text-primary"
              >{{ p.cve_id }}</NuxtLink>
              <p class="text-xs text-muted-foreground font-mono truncate">
                {{ p.package_name }} → {{ p.fixed_version ?? '?' }} · {{ p.affected_count }} hosts
              </p>
            </div>
            <Badge v-if="p.cvss_v3_severity" :color="SEVERITY_COLORS[p.cvss_v3_severity] ?? 'gray'" size="xs" class="tabular-nums">
              {{ p.cvss_v3_score ? p.cvss_v3_score.toFixed(1) : p.cvss_v3_severity }}
            </Badge>
          </li>
        </ul>
      </Card>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-3 items-start">
      <TopVulnerableServers
        :resources="topResources" :loading="topResourcesLoading"
        :error="false"
      />

      <Card>
        <template #header>
          <div class="flex items-center justify-between">
            <p class="label-caps">Active security signals</p>
            <Button variant="ghost" size="xs" to="/signals">View all</Button>
          </div>
        </template>
        <Skeleton v-if="signals.loading" class="h-24 w-full" />
        <EmptyState v-else-if="activeSignals.length === 0">
          No active HIGH/CRITICAL signals — the fleet is quiet.
        </EmptyState>
        <ul v-else class="divide-y divide-border">
          <li v-for="s in activeSignals.slice(0, 8)" :key="s.id" class="py-2 flex items-center justify-between gap-2">
            <div class="min-w-0">
              <p class="text-sm font-medium truncate">{{ s.type }}</p>
              <p class="text-xs text-muted-foreground font-mono truncate">
                {{ s.host_id ?? 'fleet-wide' }} · {{ s.occurrence_count }}× · last {{ new Date(s.last_seen).toLocaleString() }}
              </p>
            </div>
            <Badge :color="SEVERITY_COLORS[s.severity] ?? 'gray'" size="xs">{{ s.severity }}</Badge>
          </li>
        </ul>
      </Card>
    </div>

    <div class="grid grid-cols-1 gap-3 mt-4 items-start">
      <RecentFailedJobs
        :jobs="recentFailedJobs" :loading="recentFailedJobsLoading"
        :error="false"
      />
    </div>
  </div>
</template>
