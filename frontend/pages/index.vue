<script setup lang="ts">
import { Server, ShieldAlert, ClipboardList, BellDot } from 'lucide-vue-next'
import type { ChartDataPoint } from '~/components/ui/chart/types'

const dashboard = useDashboardStore()
const vulnerabilities = useVulnerabilitiesStore()
const compliance = useComplianceStore()
const { hasRole } = useCurrentUser()

const RANGE_OPTIONS = [
  { label: 'Last 7 days', value: '7d' },
  { label: 'Last 30 days', value: '30d' },
  { label: 'Last 90 days', value: '90d' },
]

async function retry() {
  await dashboard.loadOverview(true)
}

onMounted(() => dashboard.loadOverview())

// Mirrors VulnerabilitySeverityDonut.vue's severity scale as closely as
// Badge.vue's fixed palette allows — Badge has no blue/info variant, so LOW
// (Recon Blue on the donut) falls back to gray here rather than a mismatched hue.
const SEVERITY_COLOR: Record<string, string> = {
  CRITICAL: 'red', HIGH: 'orange', MEDIUM: 'amber', LOW: 'gray', INFO: 'gray',
}

function titleCase(word: string): string {
  return word.charAt(0) + word.slice(1).toLowerCase()
}

const severityBadges = (bySeverity: Record<string, number>) =>
  ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
    .filter(sev => (bySeverity[sev] ?? 0) > 0)
    .map(sev => ({ label: `${bySeverity[sev]} ${titleCase(sev)}`, color: SEVERITY_COLOR[sev] }))

// Appended to the Vulnerabilities KPI card specifically — real data
// (GET /vulnerabilities/patchable, already fetched by dashboard.loadTab)
// that answers "how many of these can I fix right now," not just how many
// exist. No equivalent existed anywhere on the dashboard before this pass.
const vulnerabilityBadges = computed(() => {
  const badges = dashboard.summary ? severityBadges(dashboard.summary.vulnerabilities.by_severity) : []
  if (vulnerabilities.patchable.length > 0) {
    badges.push({ label: `${vulnerabilities.patchable.length} Patchable`, color: 'green' })
  }
  return badges
})

const JOB_STATUS_COLOR: Record<string, string> = {
  COMPLETED: 'green', FAILED: 'red', CANCELLED: 'gray', TIMEOUT: 'amber', RUNNING: 'orange',
}

const statusBadges = (byStatus: Record<string, number>) =>
  Object.entries(byStatus)
    .filter(([, count]) => count > 0)
    .map(([status, count]) => ({ label: `${count} ${titleCase(status)}`, color: JOB_STATUS_COLOR[status] }))

// A few points of daily history turned into a MetricCard sparkline —
// derived here rather than duplicated per-widget since all four top cards
// read from the same /dashboard/trends payload.
function sparkline<T extends { day: string }>(points: T[] | undefined, value: (p: T) => number): ChartDataPoint[] {
  return (points ?? []).map(p => ({ date: p.day, value: value(p) }))
}

const serversSpark = computed(() => sparkline(dashboard.trends?.servers, (p) => p.total))
const vulnsSpark = computed(() => sparkline(dashboard.trends?.vulnerabilities, (p) => p.critical + p.high + p.medium + p.low))
const jobsSpark = computed(() => sparkline(dashboard.trends?.jobs, (p) => p.successful + p.failed + p.running))
const alertsSpark = computed(() => sparkline(dashboard.trends?.alerts, (p) => p.created))

function deltaLabel(points: ChartDataPoint[]): { trend: string; trendUp: boolean } | null {
  const first = points.at(0)
  const last = points.at(-1)
  if (points.length < 2 || !first || !last || first.value === 0) return null
  const delta = Math.round(((last.value - first.value) / first.value) * 100)
  return { trend: `${delta > 0 ? '+' : ''}${delta}%`, trendUp: delta >= 0 }
}
</script>

<template>
  <div class="relative -m-3 sm:-m-4 min-h-full p-3 sm:p-4 space-y-6">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <h1 class="text-xl font-semibold tracking-tight">Dashboard</h1>
      <Select
        :model-value="dashboard.range"
        :options="RANGE_OPTIONS"
        class="w-40 shrink-0"
        @update:model-value="(v) => dashboard.setRange(v as '7d' | '30d' | '90d')"
      />
    </div>

    <DashboardError v-if="dashboard.summaryError" @retry="retry" />

    <template v-else>
      <!-- Operational health: the KPI row. Four equal cells — each carries
           its own badge/subtitle row plus a trend sparkline, so none reads
           as thinner than its neighbors despite covering different data. -->
      <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        <MetricCard
          :icon="Server" label="Servers" to="/servers" decor
          :value="dashboard.summary?.agents.total ?? 0"
          :subtitle="`${dashboard.summary?.agents.active ?? 0} Active`" subtitle-dot="green"
          :chart-data="serversSpark" chart-color="green"
          :loading="dashboard.summaryLoading && !dashboard.summary"
        />
        <MetricCard
          :icon="ShieldAlert" label="Vulnerabilities" to="/vulnerabilities" decor
          :value="dashboard.summary?.vulnerabilities.unresolved_total ?? 0"
          :badges="vulnerabilityBadges"
          empty-badges-text="No open vulnerabilities"
          :chart-data="vulnsSpark" chart-color="red"
          v-bind="deltaLabel(vulnsSpark) ?? {}"
          :loading="dashboard.summaryLoading && !dashboard.summary"
        />
        <MetricCard
          :icon="ClipboardList" label="Jobs" to="/jobs" decor
          :value="dashboard.summary?.jobs.total ?? 0"
          :badges="dashboard.summary ? statusBadges(dashboard.summary.jobs.by_status) : []"
          :chart-data="jobsSpark" chart-color="blue"
          :loading="dashboard.summaryLoading && !dashboard.summary"
        />
        <MetricCard
          :icon="BellDot" label="Alerts" to="/alerts" decor
          :value="dashboard.summary?.alerts.active_total ?? 0"
          :badges="dashboard.summary ? severityBadges(dashboard.summary.alerts.by_severity) : []"
          empty-badges-text="No active alerts"
          :chart-data="alertsSpark" chart-color="yellow"
          :loading="dashboard.summaryLoading && !dashboard.summary"
        />
      </div>

      <!-- Attention required: the two actionable, ranked lists — who to fix
           and what broke. Both use real, previously-unsurfaced-on-dashboard
           data (RecentFailedJobs is new; TopVulnerableServers already existed). -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3 items-start">
        <TopVulnerableServers
          :resources="vulnerabilities.topResources" :loading="vulnerabilities.topResourcesLoading"
          :error="vulnerabilities.topResourcesError"
        />
        <RecentFailedJobs
          :jobs="dashboard.recentFailedJobs" :loading="dashboard.recentFailedJobsLoading"
          :error="dashboard.recentFailedJobsError"
        />
      </div>

      <!-- Fleet posture: four single-visualization facets of the same
           question ("what does the fleet look like right now") — OS mix,
           vuln severity mix, agent online/offline, compliance. -->
      <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        <OsDistributionDonut :distribution="dashboard.summary?.agents.os_distribution ?? {}" />
        <VulnerabilitySeverityDonut :by-severity="dashboard.summary?.vulnerabilities.by_severity ?? {}" />
        <AgentStatusDonut :by-status="dashboard.summary?.agents.by_status ?? {}" />
        <ComplianceOverviewCard :overview="compliance.overview" />
      </div>

      <!-- Trends: one chart, not a wall of them. -->
      <JobsTrendChart :points="dashboard.trends?.jobs ?? []" :loading="dashboard.trendsLoading && !dashboard.trends" />

      <!-- Recent activity: history, intentionally last — it's context, not
           something requiring action right now. -->
      <RecentActivityFeed v-if="hasRole('AUDITOR')" />
    </template>
  </div>
</template>
