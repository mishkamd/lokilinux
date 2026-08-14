<script setup lang="ts">
import { Server, ShieldAlert, ClipboardList, BellDot } from 'lucide-vue-next'
import type { ChartDataPoint } from '~/components/ui/chart/types'

const dashboard = useDashboardStore()
const vulnerabilities = useVulnerabilitiesStore()
const compliance = useComplianceStore()
const { hasRole } = useCurrentUser()

const TABS = [
  { label: 'Overview', slot: 'overview' },
  { label: 'Infrastructure', slot: 'infrastructure' },
  { label: 'Security', slot: 'security' },
  { label: 'Automation', slot: 'automation' },
  { label: 'Compliance', slot: 'compliance' },
  { label: 'Observability', slot: 'observability' },
] as const
type TabSlot = typeof TABS[number]['slot']
// AppTabs wants a plain mutable array — .map() gives one without losing
// each slot's literal type the way `satisfies` (which just widens to
// `string`) would.
const tabItems = TABS.map(t => ({ label: t.label, slot: t.slot }))

const activeTab = ref<TabSlot>('overview')
async function onTabChange(index: number) {
  const tab = TABS[index]
  if (!tab) return
  activeTab.value = tab.slot
  await dashboard.loadTab(tab.slot)
}

const RANGE_OPTIONS = [
  { label: 'Last 7 days', value: '7d' },
  { label: 'Last 30 days', value: '30d' },
  { label: 'Last 90 days', value: '90d' },
]

async function retry() {
  await dashboard.loadTab(activeTab.value, true)
}

onMounted(() => dashboard.loadTab('overview'))

const SEVERITY_COLOR: Record<string, string> = {
  CRITICAL: 'red', HIGH: 'red', MEDIUM: 'gray', LOW: 'gray', INFO: 'gray',
}

const severityBadges = (bySeverity: Record<string, number>) =>
  ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
    .filter(sev => (bySeverity[sev] ?? 0) > 0)
    .map(sev => ({ label: `${sev}: ${bySeverity[sev]}`, color: SEVERITY_COLOR[sev] }))

const statusBadges = (byStatus: Record<string, number>) =>
  Object.entries(byStatus).filter(([, count]) => count > 0).map(([status, count]) => ({ label: `${status}: ${count}` }))

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
  <div class="relative -m-3 sm:-m-4 min-h-full p-3 sm:p-4 space-y-3">
    <div class="flex items-center justify-between gap-2">
      <AppTabs :items="tabItems" @change="onTabChange" />
      <Select
        :model-value="dashboard.range"
        :options="RANGE_OPTIONS"
        class="w-40 shrink-0"
        @update:model-value="(v) => dashboard.setRange(v as '7d' | '30d' | '90d')"
      />
    </div>

    <DashboardError v-if="dashboard.summaryError" @retry="retry" />

    <template v-else>
      <!-- Overview: full grid, everything on one screen -->
      <div v-show="activeTab === 'overview'" class="space-y-3">
        <div class="grid grid-cols-2 xl:grid-cols-4 gap-3">
          <MetricCard
            :icon="Server" label="Servers" to="/servers"
            :value="dashboard.summary?.agents.total ?? 0" :subtitle="`${dashboard.summary?.agents.active ?? 0} active`"
            :badges="dashboard.summary ? statusBadges(dashboard.summary.agents.by_status) : []"
            :chart-data="serversSpark" chart-color="green"
            :loading="dashboard.summaryLoading && !dashboard.summary"
          />
          <MetricCard
            :icon="ShieldAlert" label="Vulnerabilities" to="/vulnerabilities"
            :value="dashboard.summary?.vulnerabilities.unresolved_total ?? 0"
            :badges="dashboard.summary ? severityBadges(dashboard.summary.vulnerabilities.by_severity) : []"
            empty-badges-text="no open vulnerabilities"
            :chart-data="vulnsSpark" chart-color="red"
            v-bind="deltaLabel(vulnsSpark) ?? {}"
            :loading="dashboard.summaryLoading && !dashboard.summary"
          />
          <MetricCard
            :icon="ClipboardList" label="Jobs" to="/jobs"
            :value="dashboard.summary?.jobs.total ?? 0" :subtitle="`${dashboard.summary?.jobs.running ?? 0} running`"
            :badges="dashboard.summary ? statusBadges(dashboard.summary.jobs.by_status) : []"
            :chart-data="jobsSpark" chart-color="blue"
            :loading="dashboard.summaryLoading && !dashboard.summary"
          />
          <MetricCard
            :icon="BellDot" label="Alerts" to="/alerts"
            :value="dashboard.summary?.alerts.active_total ?? 0"
            :badges="dashboard.summary ? severityBadges(dashboard.summary.alerts.by_severity) : []"
            empty-badges-text="no active alerts"
            :chart-data="alertsSpark" chart-color="yellow"
            :loading="dashboard.summaryLoading && !dashboard.summary"
          />
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
          <OsDistributionDonut :distribution="dashboard.summary?.agents.os_distribution ?? {}" />
          <VulnerabilitySeverityDonut :by-severity="dashboard.summary?.vulnerabilities.by_severity ?? {}" />
        </div>

        <JobsTrendChart :points="dashboard.trends?.jobs ?? []" :loading="dashboard.trendsLoading && !dashboard.trends" />

        <div class="grid grid-cols-1 xl:grid-cols-2 gap-3">
          <RecentActivityFeed v-if="hasRole('AUDITOR')" />
          <TopVulnerableServers
            :resources="vulnerabilities.topResources" :loading="vulnerabilities.topResourcesLoading"
            :class="{ 'xl:col-span-2': !hasRole('AUDITOR') }"
          />
        </div>

        <div class="grid grid-cols-2 xl:grid-cols-4 gap-3">
          <AgentStatusDonut :by-status="dashboard.summary?.agents.by_status ?? {}" />
          <InfrastructureHealth :health="dashboard.summary?.health ?? null" />
          <SecurityOverview :summary="vulnerabilities.summary" :trend="vulnerabilities.trend" />
          <ComplianceOverviewCard :overview="compliance.overview" :trend="compliance.trend" />
        </div>
      </div>

      <!-- Infrastructure: servers + agents + health -->
      <div v-show="activeTab === 'infrastructure'" class="space-y-3">
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <MetricCard
            :icon="Server" label="Servers" to="/servers"
            :value="dashboard.summary?.agents.total ?? 0" :subtitle="`${dashboard.summary?.agents.active ?? 0} active`"
            :chart-data="serversSpark" chart-color="green"
            :loading="dashboard.summaryLoading && !dashboard.summary"
          />
          <AgentStatusDonut :by-status="dashboard.summary?.agents.by_status ?? {}" />
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
          <OsDistributionDonut :distribution="dashboard.summary?.agents.os_distribution ?? {}" />
          <InfrastructureHealth :health="dashboard.summary?.health ?? null" />
        </div>
        <NuxtLink to="/servers" class="text-xs font-medium text-primary">View full server list →</NuxtLink>
      </div>

      <!-- Security: vulnerabilities + risk -->
      <div v-show="activeTab === 'security'" class="space-y-3">
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <MetricCard
            :icon="ShieldAlert" label="Vulnerabilities" to="/vulnerabilities"
            :value="dashboard.summary?.vulnerabilities.unresolved_total ?? 0"
            :badges="dashboard.summary ? severityBadges(dashboard.summary.vulnerabilities.by_severity) : []"
            empty-badges-text="no open vulnerabilities"
            :chart-data="vulnsSpark" chart-color="red"
            :loading="dashboard.summaryLoading && !dashboard.summary"
          />
          <SecurityOverview :summary="vulnerabilities.summary" :trend="vulnerabilities.trend" />
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
          <VulnerabilitySeverityDonut :by-severity="dashboard.summary?.vulnerabilities.by_severity ?? {}" />
          <TopVulnerableServers :resources="vulnerabilities.topResources" :loading="vulnerabilities.topResourcesLoading" />
        </div>
        <NuxtLink to="/vulnerabilities" class="text-xs font-medium text-primary">View full vulnerability report →</NuxtLink>
      </div>

      <!-- Automation: jobs -->
      <div v-show="activeTab === 'automation'" class="space-y-3">
        <MetricCard
          :icon="ClipboardList" label="Jobs" to="/jobs"
          :value="dashboard.summary?.jobs.total ?? 0" :subtitle="`${dashboard.summary?.jobs.running ?? 0} running`"
          :badges="dashboard.summary ? statusBadges(dashboard.summary.jobs.by_status) : []"
          :chart-data="jobsSpark" chart-color="blue"
          class="max-w-md"
          :loading="dashboard.summaryLoading && !dashboard.summary"
        />
        <JobsTrendChart :points="dashboard.trends?.jobs ?? []" :loading="dashboard.trendsLoading && !dashboard.trends" />
        <NuxtLink to="/jobs" class="text-xs font-medium text-primary">View full job history →</NuxtLink>
      </div>

      <!-- Compliance -->
      <div v-show="activeTab === 'compliance'" class="space-y-3">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
          <ComplianceOverviewCard :overview="compliance.overview" :trend="compliance.trend" />
          <ComplianceTrendChart
            :points="compliance.trend" :loading="compliance.trendLoading" :range="compliance.trendRange"
            @update:range="(r) => { compliance.trendRange = r as '7d' | '30d' | '90d' | '1y'; compliance.fetchTrend() }"
          />
        </div>
        <NuxtLink to="/compliance" class="text-xs font-medium text-primary">View full compliance report →</NuxtLink>
      </div>

      <!-- Observability: alerts + activity -->
      <div v-show="activeTab === 'observability'" class="space-y-3">
        <MetricCard
          :icon="BellDot" label="Alerts" to="/alerts"
          :value="dashboard.summary?.alerts.active_total ?? 0"
          :badges="dashboard.summary ? severityBadges(dashboard.summary.alerts.by_severity) : []"
          empty-badges-text="no active alerts"
          :chart-data="alertsSpark" chart-color="yellow"
          class="max-w-md"
          :loading="dashboard.summaryLoading && !dashboard.summary"
        />
        <RecentActivityFeed v-if="hasRole('AUDITOR')" />
        <NuxtLink to="/alerts" class="text-xs font-medium text-primary">View all alerts →</NuxtLink>
      </div>
    </template>
  </div>
</template>
