<script setup lang="ts">
import { SEVERITY_COLORS } from '~/utils/complianceColors'
import { FileText, ShieldCheck, ShieldAlert, Gauge, BookCheck, ShieldOff, HelpCircle } from 'lucide-vue-next'

const store = useComplianceStore()
const {
  baselines, baselinesLoading, topViolations, topViolationsLoading, topChangedFiles, topChangedFilesLoading,
  overview, overviewLoading, trend, trendLoading, trendRange,
  assessments, assessmentsLoading, policySets,
} = storeToRefs(store)
const { canEdit } = useCurrentUser()
const toast = useToast()

// ── U10 aggregate ("how compliant are we?") — one cached endpoint ─────────────
interface OverviewCategory {
  category: string
  agents_scored: number
  score: number
  weighted_score: number
  unknown_total: number
}
interface StandardsCoverage {
  standard: string
  total_rules: number
  executable_rules: number
  coverage_pct: number
}
interface FleetOverview {
  generated_at: string
  overall: OverviewCategory | null
  categories: OverviewCategory[]
  findings_by_severity: Record<string, number>
  open_findings_total: number
  drift_by_severity: Record<string, number>
  open_drift_total: number
  standards: StandardsCoverage[]
  fleet: { active_agents: number; scored_agents_24h: number; unscored_agents: number }
  cached: boolean
}

const { data: agg, pending: aggPending, refresh: aggRefresh } = await useAsyncData(
  'compliance-overview-u10',
  () => useApi().get<FleetOverview>('/compliance/overview'),
  { lazy: true },
)

const aggOverall = computed(() => agg.value?.overall ?? null)
const aggUnscored = computed(() => agg.value?.fleet.unscored_agents ?? 0)

function sevTotal(sev: Record<string, number> | undefined, name: string): number {
  return sev?.[name] ?? 0
}

onMounted(() => {
  store.fetchBaselines()
  store.fetchTopViolations()
  store.fetchTopChangedFiles()
  store.fetchOverview()
  store.fetchTrend()
  store.fetchAssessments()
  store.fetchPolicySets()
})

function onRangeChange(range: string) {
  trendRange.value = range as typeof trendRange.value
  store.fetchTrend()
}


const SEVERITY_RANK: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }

const sortedDrift = computed(() =>
  [...topViolations.value.recent_drift].sort(
    (a, b) => (SEVERITY_RANK[String(a.severity)] ?? 9) - (SEVERITY_RANK[String(b.severity)] ?? 9),
  ),
)

const ASSESSMENT_STATUS_COLORS: Record<string, string> = {
  PENDING: 'gray', RUNNING: 'amber', COMPLETED: 'green', FAILED: 'red', CANCELLED: 'gray',
}

const ruleViolationColumns = [
  { key: 'title', label: 'Rule' },
  { key: 'severity', label: 'Severity' },
  { key: 'fail_count', label: 'Fails' },
]
const driftColumns = [
  { key: 'summary', label: 'Change' },
  { key: 'severity', label: 'Severity' },
]
const changedFilesColumns = [
  { key: 'path', label: 'Path' },
  { key: 'change_count', label: 'Changes' },
]
const baselineColumns = [
  { key: 'name', label: 'Name' },
  { key: 'scope_type', label: 'Scope' },
  { key: 'is_enabled', label: 'Status' },
]

const showRunAssessment = ref(false)
const runningAssessment = ref(false)
const assessmentFormError = ref<string | null>(null)
const assessmentForm = ref({ policy_set_id: '', scope_selector: '{}' })

const policySetOptions = computed(() =>
  policySets.value.map((p) => ({ label: p.name, value: p.id })),
)

async function submitRunAssessment() {
  assessmentFormError.value = null
  if (!assessmentForm.value.policy_set_id) {
    assessmentFormError.value = 'Select a policy set.'
    return
  }
  let scopeSelector: Record<string, unknown>
  try {
    scopeSelector = JSON.parse(assessmentForm.value.scope_selector || '{}')
  } catch {
    assessmentFormError.value = 'Scope selector must be valid JSON.'
    return
  }

  runningAssessment.value = true
  try {
    await store.createAssessment({ policy_set_id: assessmentForm.value.policy_set_id, scope_selector: scopeSelector })
    toast.add({ title: 'Assessment queued', description: 'The leader-elected worker will pick it up shortly.' })
    showRunAssessment.value = false
    assessmentForm.value = { policy_set_id: '', scope_selector: '{}' }
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to queue assessment', color: 'red' })
  } finally {
    runningAssessment.value = false
  }
}
</script>

<template>
  <div>
    <!-- U10 hero: the weighted answer to "how compliant are we?" -->
    <Card class="mb-4">
      <template #header>
        <div class="flex items-center justify-between">
          <p class="label-caps">Fleet compliance (weighted)</p>
          <div class="flex items-center gap-2">
            <span v-if="agg?.cached" class="text-[10px] text-muted-foreground">cached 60s</span>
            <Button variant="ghost" size="xs" :loading="aggPending" @click="aggRefresh()">Refresh</Button>
          </div>
        </div>
      </template>
      <Skeleton v-if="aggPending && !agg" class="h-24 w-full" />
      <template v-else>
        <div class="grid grid-cols-2 md:grid-cols-5 gap-4 items-end">
          <div>
            <p class="text-4xl font-mono font-semibold tabular-nums">
              {{ aggOverall ? `${Number(aggOverall.weighted_score).toFixed(1)}` : '—' }}<span class="text-lg text-muted-foreground">%</span>
            </p>
            <p class="text-xs text-muted-foreground mt-1">weighted overall · {{ aggOverall?.agents_scored ?? 0 }} agents</p>
          </div>
          <div class="space-y-1">
            <p class="text-xs text-muted-foreground flex items-center gap-1">
              <ShieldAlert class="size-3.5" /> Open findings
            </p>
            <p class="text-2xl font-mono font-semibold tabular-nums">{{ agg?.open_findings_total ?? '—' }}</p>
            <div class="flex gap-1">
              <Badge :color="SEVERITY_COLORS.CRITICAL" size="xs">{{ sevTotal(agg?.findings_by_severity, 'CRITICAL') }} C</Badge>
              <Badge :color="SEVERITY_COLORS.HIGH" size="xs">{{ sevTotal(agg?.findings_by_severity, 'HIGH') }} H</Badge>
              <Badge :color="SEVERITY_COLORS.MEDIUM" size="xs">{{ sevTotal(agg?.findings_by_severity, 'MEDIUM') }} M</Badge>
              <Badge :color="SEVERITY_COLORS.LOW" size="xs">{{ sevTotal(agg?.findings_by_severity, 'LOW') }} L</Badge>
            </div>
          </div>
          <div class="space-y-1">
            <p class="text-xs text-muted-foreground flex items-center gap-1">
              <ShieldOff class="size-3.5" /> Open drift
            </p>
            <p class="text-2xl font-mono font-semibold tabular-nums">{{ agg?.open_drift_total ?? '—' }}</p>
          </div>
          <div class="space-y-1">
            <p class="text-xs text-muted-foreground flex items-center gap-1">
              <ShieldCheck class="size-3.5" /> Scored agents (24h)
            </p>
            <p class="text-2xl font-mono font-semibold tabular-nums">
              {{ agg?.fleet.scored_agents_24h ?? '—' }}<span class="text-sm text-muted-foreground">/{{ agg?.fleet.active_agents ?? '—' }}</span>
            </p>
          </div>
          <div class="space-y-1">
            <p class="text-xs text-muted-foreground flex items-center gap-1">
              <HelpCircle class="size-3.5" /> Unknown basis
            </p>
            <p class="text-2xl font-mono font-semibold tabular-nums" :class="aggUnscored > 0 ? 'text-amber-500' : ''">
              {{ agg?.fleet.unscored_agents ?? '—' }}
            </p>
            <p class="text-[11px] text-muted-foreground">
              {{ aggUnscored > 0 ? 'agents unreported — NOT counted as compliant' : 'full fleet reported' }}
            </p>
          </div>
        </div>

        <div v-if="agg?.categories?.length" class="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3">
          <div v-for="c in agg.categories" :key="c.category" class="rounded-lg border border-border p-2.5">
            <p class="label-caps mb-1">{{ c.category }}</p>
            <p class="text-xl font-mono font-semibold tabular-nums">{{ Number(c.weighted_score).toFixed(1) }}%</p>
            <div class="h-1 w-full rounded-full bg-muted overflow-hidden mt-1.5">
              <div class="h-full bg-primary transition-all" :style="{ width: `${Number(c.weighted_score)}%` }" />
            </div>
            <p class="text-[11px] text-muted-foreground mt-1">{{ c.agents_scored }} agents</p>
          </div>
        </div>

        <div v-if="agg?.standards?.length" class="mt-4">
          <p class="label-caps mb-2">Standards coverage (CEL-executable / total)</p>
          <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div v-for="s in agg.standards" :key="s.standard" class="rounded-lg border border-border p-2.5">
              <div class="flex items-center justify-between">
                <p class="text-sm font-medium truncate" :title="s.standard">{{ s.standard }}</p>
                <span class="text-xs font-mono tabular-nums">{{ s.coverage_pct }}%</span>
              </div>
              <div class="h-1 w-full rounded-full bg-muted overflow-hidden mt-1.5">
                <div class="h-full bg-primary transition-all" :style="{ width: `${s.coverage_pct}%` }" />
              </div>
              <p class="text-[11px] text-muted-foreground mt-1">{{ s.executable_rules }}/{{ s.total_rules }} rules executable</p>
            </div>
          </div>
        </div>
      </template>
    </Card>

    <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
      <MetricCard
        :icon="Gauge"
        label="Compliance"
        :value="overview ? `${overview.overall_compliance_pct.toFixed(1)}%` : (overviewLoading ? '…' : '—')"
        to="/compliance/rules"
        view-all-label="View"
      />
      <MetricCard
        :icon="ShieldAlert"
        label="Critical violations"
        :value="overview?.critical_violations ?? (overviewLoading ? '…' : '—')"
        to="/compliance/drift"
        view-all-label="View"
      />
      <MetricCard
        :icon="ShieldAlert"
        label="High violations"
        :value="overview?.high_violations ?? (overviewLoading ? '…' : '—')"
        to="/compliance/drift"
        view-all-label="View"
      />
      <MetricCard
        :icon="ShieldCheck"
        label="Baselines"
        :value="overview?.active_baselines ?? (overviewLoading ? '…' : '—')"
        subtitle="active"
        to="/compliance/baselines"
        view-all-label="View"
      />
      <MetricCard
        :icon="BookCheck"
        label="Policies"
        :value="overview?.enabled_policies ?? (overviewLoading ? '…' : '—')"
        subtitle="published + enabled"
        to="/compliance/policies"
        view-all-label="View"
      />
      <MetricCard
        :icon="FileText"
        label="Open drift"
        :value="overview?.open_drift ?? (overviewLoading ? '…' : '—')"
        to="/compliance/drift"
        view-all-label="View"
      />
      <MetricCard
        :icon="ShieldCheck"
        label="Servers evaluated"
        :value="overview?.servers_evaluated ?? (overviewLoading ? '…' : '—')"
        to="/servers"
        view-all-label="View"
      />
      <MetricCard
        :icon="ShieldAlert"
        label="Non-compliant"
        :value="overview?.servers_non_compliant ?? (overviewLoading ? '…' : '—')"
        to="/servers"
        view-all-label="View"
      />
      <MetricCard
        :icon="ShieldOff"
        label="Exceptions"
        :value="overview?.exceptions_active ?? (overviewLoading ? '…' : '—')"
        subtitle="active"
        to="/compliance/exceptions"
        view-all-label="View"
      />
    </div>

    <div class="mb-4">
      <ComplianceTrendChart
        :points="trend"
        :loading="trendLoading"
        :range="trendRange"
        @update:range="onRangeChange"
      />
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
      <Card>
        <template #header>
          <div class="flex items-center justify-between">
            <p class="label-caps">Top violations</p>
            <Button variant="ghost" size="xs" to="/compliance/drift">View all</Button>
          </div>
        </template>
        <Skeleton v-if="topViolationsLoading" class="h-24 w-full" />
        <EmptyState v-else-if="topViolations.top_rules.length === 0 && sortedDrift.length === 0">
          No violations yet — publish a baseline and import policy rules to start scoring.
        </EmptyState>
        <template v-else>
          <DataTable
            v-if="topViolations.top_rules.length"
            :rows="topViolations.top_rules.slice(0, 5)" :columns="ruleViolationColumns" row-key="rule_id"
          >
            <template #title-data="{ row }">
              <p class="text-sm font-medium truncate" :title="row.title">{{ row.title }}</p>
              <p class="text-xs text-muted-foreground font-mono truncate">{{ row.rule_key }} · {{ row.domain }}</p>
            </template>
            <template #severity-data="{ row }"><Badge :color="SEVERITY_COLORS[row.severity] ?? 'gray'" size="xs">{{ row.severity }}</Badge></template>
            <template #fail_count-data="{ row }"><Badge color="gray" size="xs">{{ row.fail_count }}×</Badge></template>
          </DataTable>
          <DataTable
            v-if="sortedDrift.length"
            class="mt-3"
            :rows="sortedDrift.slice(0, 5)" :columns="driftColumns" row-key="id" rows-clickable
            @row-click="(row) => navigateTo(`/compliance/drift/${row.id}`)"
          >
            <template #summary-data="{ row }">
              <p class="text-sm font-medium truncate">{{ row.summary }}</p>
              <p class="text-xs text-muted-foreground font-mono truncate">
                {{ new Date(String(row.time)).toLocaleString() }} · {{ row.domain }} · {{ row.compared_against }}
              </p>
            </template>
            <template #severity-data="{ row }"><Badge :color="SEVERITY_COLORS[String(row.severity)] ?? 'gray'" size="xs">{{ row.severity }}</Badge></template>
          </DataTable>
        </template>
      </Card>

      <Card>
        <template #header>
          <div class="flex items-center justify-between">
            <p class="label-caps">Top changed files</p>
            <Button variant="ghost" size="xs" to="/compliance/file-integrity">View all</Button>
          </div>
        </template>
        <Skeleton v-if="topChangedFilesLoading" class="h-24 w-full" />
        <EmptyState v-else-if="topChangedFiles.length === 0">
          No file changes tracked yet (7-day window).
        </EmptyState>
        <DataTable
          v-else
          :rows="topChangedFiles.slice(0, 8)" :columns="changedFilesColumns" row-key="path" rows-clickable
          @row-click="(row) => navigateTo(`/compliance/file-integrity?path=${encodeURIComponent(String(row.path))}`)"
        >
          <template #path-data="{ row }"><span class="font-mono text-xs truncate" :title="row.path">{{ row.path }}</span></template>
          <template #change_count-data="{ row }"><Badge color="gray" size="xs">{{ row.change_count }}×</Badge></template>
        </DataTable>
      </Card>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Card>
        <template #header>
          <div class="flex items-center justify-between">
            <p class="label-caps">Recent baselines</p>
            <Button variant="ghost" size="xs" to="/compliance/baselines">View all</Button>
          </div>
        </template>
        <Skeleton v-if="baselinesLoading" class="h-24 w-full" />
        <EmptyState v-else-if="baselines.length === 0">
          No baselines yet. <NuxtLink to="/compliance/baselines" class="text-primary hover:underline">Create one</NuxtLink>.
        </EmptyState>
        <DataTable
          v-else
          :rows="baselines.slice(0, 5)" :columns="baselineColumns" row-key="id" rows-clickable
          @row-click="(row) => navigateTo(`/compliance/baselines/${row.id}`)"
        >
          <template #name-data="{ row }"><p class="text-sm font-medium">{{ row.name }}</p></template>
          <template #scope_type-data="{ row }"><span class="text-xs text-muted-foreground font-mono">{{ row.scope_type }}</span></template>
          <template #is_enabled-data="{ row }">
            <Badge v-if="row.is_enabled" color="green" size="xs">Enabled</Badge>
            <Badge v-else color="gray" size="xs">Disabled</Badge>
          </template>
        </DataTable>
      </Card>

      <Card>
        <template #header>
          <div class="flex items-center justify-between">
            <p class="label-caps">Recent assessments</p>
            <Button v-if="canEdit" variant="outline" size="xs" @click="showRunAssessment = true">Run assessment</Button>
          </div>
        </template>
        <Skeleton v-if="assessmentsLoading" class="h-24 w-full" />
        <EmptyState v-else-if="assessments.length === 0">
          No assessments yet. Runs on-demand evaluation of the current fleet state against a policy set.
        </EmptyState>
        <ul v-else class="divide-y divide-border">
          <li v-for="a in assessments" :key="a.id" class="py-2.5">
            <div class="flex items-center justify-between mb-1">
              <span class="text-xs font-mono text-muted-foreground">{{ new Date(a.created_at).toLocaleString() }}</span>
              <Badge :color="ASSESSMENT_STATUS_COLORS[a.status] ?? 'gray'" size="xs">{{ a.status }}</Badge>
            </div>
            <div v-if="a.status === 'RUNNING' || a.status === 'COMPLETED'" class="space-y-1">
              <div class="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                <div
                  class="h-full bg-primary transition-all"
                  :style="{ width: `${a.servers_total > 0 ? Math.round((a.servers_done / a.servers_total) * 100) : 0}%` }"
                />
              </div>
              <p class="text-[11px] text-muted-foreground font-mono">
                {{ a.servers_done }}/{{ a.servers_total }} servers · {{ a.rules_done }}/{{ a.rules_total }} rules
              </p>
            </div>
          </li>
        </ul>
      </Card>
    </div>

    <Dialog v-model="showRunAssessment" title="Run assessment">
      <template #body>
        <div class="space-y-4">
          <FormField label="Policy set" required help="Evaluates the fleet's already-collected state against this policy set">
            <Select v-model="assessmentForm.policy_set_id" :options="policySetOptions" placeholder="Select a policy set" />
          </FormField>
          <FormField label="Scope selector" help="JSON — leave empty to target the whole fleet">
            <textarea
              v-model="assessmentForm.scope_selector"
              rows="3"
              class="flex w-full rounded-lg border border-input bg-card px-2.5 py-1.5 text-[13px] font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-primary"
            />
          </FormField>
          <Alert v-if="assessmentFormError" color="red">{{ assessmentFormError }}</Alert>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showRunAssessment = false">Cancel</Button>
        <Button :loading="runningAssessment" @click="submitRunAssessment">Run</Button>
      </template>
    </Dialog>
  </div>
</template>
