<script setup lang="ts">
import { Server, ShieldAlert, ClipboardList, BellDot, ShieldCheck, BookCheck, CheckCircle2, WifiOff } from 'lucide-vue-next'
import type { ChartDataPoint } from '~/components/ui/chart/types'

const dashboard = useDashboardStore()
const vulnerabilities = useVulnerabilitiesStore()
const compliance = useComplianceStore()
const { hasRole } = useCurrentUser()
const { severityColor, severityLabel } = useSeverity()
const { categories, fetchCategories } = useServers()

onMounted(() => fetchCategories())

const RANGE_OPTIONS = [
  { label: 'Last 7 days', value: '7d' },
  { label: 'Last 30 days', value: '30d' },
  { label: 'Last 90 days', value: '90d' },
]

async function retry() {
  await dashboard.loadOverview(true)
}

onMounted(() => dashboard.loadOverview())

function titleCase(word: string): string {
  return word.charAt(0) + word.slice(1).toLowerCase()
}

const severityBadges = (bySeverity: Record<string, number>) =>
  ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']
    .filter(sev => (bySeverity[sev] ?? 0) > 0)
    .map(sev => ({ label: `${bySeverity[sev]} ${severityLabel(sev)}`, color: severityColor(sev) }))

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
  COMPLETED: 'green', FAILED: 'red', CANCELLED: 'gray', TIMEOUT: 'amber',
  // 'blue' (--info), not 'orange' — orange is reserved for HIGH severity
  // on the vulnerability scale and would collide in meaning here.
  RUNNING: 'blue', QUEUED: 'gray', SCHEDULED: 'gray', PENDING: 'gray',
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
const complianceSpark = computed(() => sparkline(compliance.trend, (p) => p.compliance_pct))

function deltaLabel(points: ChartDataPoint[]): { trend: string; trendUp: boolean } | null {
  const first = points.at(0)
  const last = points.at(-1)
  if (points.length < 2 || !first || !last || first.value === 0) return null
  const delta = Math.round(((last.value - first.value) / first.value) * 100)
  return { trend: `${delta > 0 ? '+' : ''}${delta}%`, trendUp: delta >= 0 }
}

// Healthy/Critical-analog split — agents.by_status has no historical table,
// so these carry a share-of-fleet subtitle instead of a manufactured delta.
const inactiveAgents = computed(() => dashboard.summary?.agents.by_status.INACTIVE ?? 0)
function pctOfFleet(count: number): string {
  const total = dashboard.summary?.agents.total ?? 0
  return total > 0 ? `${Math.round((count / total) * 100)}% of fleet` : '—'
}
</script>

<template>
  <div class="relative -m-3 sm:-m-4 min-h-full p-3 sm:p-4 space-y-3">
    <!-- The layout's topbar already shows the page title ("Dashboard") —
         no second copy here, just the page's one real control. -->
    <div class="flex justify-end">
      <Select
        :model-value="dashboard.range"
        :options="RANGE_OPTIONS"
        class="w-40 shrink-0"
        @update:model-value="(v) => dashboard.setRange(v as '7d' | '30d' | '90d')"
      />
    </div>

    <DashboardError v-if="dashboard.summaryError" @retry="retry" />

    <template v-else>
      <!-- Operational health: the KPI row. Eight equal cells — each carries
           its own badge/subtitle row plus a trend sparkline where history
           exists, so none reads as thinner than its neighbors. -->
      <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        <MetricCard
          :icon="Server" label="Servers" to="/servers"
          :value="dashboard.summary?.agents.total ?? 0"
          :subtitle="`${dashboard.summary?.agents.active ?? 0} Active`" subtitle-dot="green"
          :chart-data="serversSpark" chart-color="green"
          v-bind="deltaLabel(serversSpark) ?? {}"
          :loading="dashboard.summaryLoading && !dashboard.summary"
        />
        <MetricCard
          :icon="ShieldAlert" label="Vulnerabilities" to="/vulnerabilities"
          :value="dashboard.summary?.vulnerabilities.unresolved_total ?? 0"
          :badges="vulnerabilityBadges"
          empty-badges-text="No open vulnerabilities"
          :chart-data="vulnsSpark" chart-color="red"
          v-bind="deltaLabel(vulnsSpark) ?? {}"
          :loading="dashboard.summaryLoading && !dashboard.summary"
        />
        <MetricCard
          :icon="ClipboardList" label="Jobs" to="/jobs"
          :value="dashboard.summary?.jobs.total ?? 0"
          :badges="dashboard.summary ? statusBadges(dashboard.summary.jobs.by_status) : []"
          :chart-data="jobsSpark" chart-color="blue"
          v-bind="deltaLabel(jobsSpark) ?? {}"
          :loading="dashboard.summaryLoading && !dashboard.summary"
        />
        <MetricCard
          :icon="BellDot" label="Alerts" to="/alerts"
          :value="dashboard.summary?.alerts.active_total ?? 0"
          :badges="dashboard.summary ? severityBadges(dashboard.summary.alerts.by_severity) : []"
          empty-badges-text="No active alerts"
          :chart-data="alertsSpark" chart-color="yellow"
          v-bind="deltaLabel(alertsSpark) ?? {}"
          :loading="dashboard.summaryLoading && !dashboard.summary"
        />
        <MetricCard
          :icon="ShieldCheck" label="Compliance" to="/compliance"
          :value="compliance.overview ? `${compliance.overview.overall_compliance_pct.toFixed(1)}%` : '—'"
          :subtitle="`${compliance.overview?.servers_evaluated ?? 0} evaluated`"
          :chart-data="complianceSpark" chart-color="green"
          v-bind="deltaLabel(complianceSpark) ?? {}"
          :loading="compliance.overviewLoading && !compliance.overview"
        />
        <MetricCard
          :icon="BookCheck" label="Policies" to="/compliance/policies"
          :value="dashboard.summary?.policies.enabled ?? 0"
          :subtitle="`of ${dashboard.summary?.policies.total ?? 0} total`"
          :loading="dashboard.summaryLoading && !dashboard.summary"
        />
        <MetricCard
          :icon="CheckCircle2" label="Active Agents" to="/servers"
          :value="dashboard.summary?.agents.active ?? 0"
          :subtitle="pctOfFleet(dashboard.summary?.agents.active ?? 0)" subtitle-dot="green"
          :loading="dashboard.summaryLoading && !dashboard.summary"
        />
        <MetricCard
          :icon="WifiOff" label="Inactive Agents" to="/servers"
          :value="inactiveAgents"
          :subtitle="pctOfFleet(inactiveAgents)" subtitle-dot="red"
          :loading="dashboard.summaryLoading && !dashboard.summary"
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

      <!-- Active incidents: the one open, unresolved-right-now table, paired
           with what's running right now beside it. -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3 items-start">
        <ActiveIncidents
          :incidents="dashboard.activeIncidents" :inventory="dashboard.inventory"
          :loading="dashboard.activeIncidentsLoading" :error="dashboard.activeIncidentsError"
        />
        <RunningJobs
          :jobs="dashboard.runningJobs" :loading="dashboard.runningJobsLoading"
          :error="dashboard.runningJobsError"
        />
      </div>

      <!-- Attention required + operations: side by side only once there's
           room for InfrastructureInventory's columns (lg, 1024px+) — at md
           the table clips and its own header controls get truncated. -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-3 items-start">
        <TopVulnerableServers
          :resources="vulnerabilities.topResources" :loading="vulnerabilities.topResourcesLoading"
          :error="vulnerabilities.topResourcesError"
        />
        <InfrastructureInventory
          :servers="dashboard.inventory" :categories="categories"
          :loading="dashboard.inventoryLoading" :error="dashboard.inventoryError"
        />
      </div>

      <!-- Trends: one chart, not a wall of them. -->
      <JobsTrendChart :points="dashboard.trends?.jobs ?? []" :loading="dashboard.trendsLoading && !dashboard.trends" />

      <!-- Recent activity + what broke: history, intentionally last on the
           page, side by side. -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3 items-start">
        <RecentActivityFeed v-if="hasRole('AUDITOR')" />
        <RecentFailedJobs
          :jobs="dashboard.recentFailedJobs" :loading="dashboard.recentFailedJobsLoading"
          :error="dashboard.recentFailedJobsError"
        />
      </div>
    </template>
  </div>
</template>
