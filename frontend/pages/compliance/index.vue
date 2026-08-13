<script setup lang="ts">
import { FileText, ShieldCheck, ShieldAlert, Gauge, BookCheck, ShieldOff } from 'lucide-vue-next'

const store = useComplianceStore()
const {
  baselines, baselinesLoading, topViolations, topViolationsLoading, topChangedFiles, topChangedFilesLoading,
  overview, overviewLoading, trend, trendLoading, trendRange,
  assessments, assessmentsLoading, policySets,
} = storeToRefs(store)
const { canEdit } = useCurrentUser()
const toast = useToast()

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

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'red', HIGH: 'red', MEDIUM: 'amber', LOW: 'gray',
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
  } catch {
    toast.add({ title: 'Failed to queue assessment', color: 'red' })
  } finally {
    runningAssessment.value = false
  }
}
</script>

<template>
  <div>
    <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
      <StatCard
        :icon="Gauge"
        label="Compliance"
        :value="overview ? `${overview.overall_compliance_pct.toFixed(1)}%` : (overviewLoading ? '…' : '—')"
        to="/compliance/rules"
        view-all-label="View"
      />
      <StatCard
        :icon="ShieldAlert"
        label="Critical violations"
        :value="overview?.critical_violations ?? (overviewLoading ? '…' : '—')"
        to="/compliance/drift"
        view-all-label="View"
      />
      <StatCard
        :icon="ShieldAlert"
        label="High violations"
        :value="overview?.high_violations ?? (overviewLoading ? '…' : '—')"
        to="/compliance/drift"
        view-all-label="View"
      />
      <StatCard
        :icon="ShieldCheck"
        label="Baselines"
        :value="overview?.active_baselines ?? (overviewLoading ? '…' : '—')"
        subtitle="active"
        to="/compliance/baselines"
        view-all-label="View"
      />
      <StatCard
        :icon="BookCheck"
        label="Policies"
        :value="overview?.enabled_policies ?? (overviewLoading ? '…' : '—')"
        subtitle="published + enabled"
        to="/compliance/policies"
        view-all-label="View"
      />
      <StatCard
        :icon="FileText"
        label="Open drift"
        :value="overview?.open_drift ?? (overviewLoading ? '…' : '—')"
        to="/compliance/drift"
        view-all-label="View"
      />
      <StatCard
        :icon="ShieldCheck"
        label="Servers evaluated"
        :value="overview?.servers_evaluated ?? (overviewLoading ? '…' : '—')"
        to="/servers"
        view-all-label="View"
      />
      <StatCard
        :icon="ShieldAlert"
        label="Non-compliant"
        :value="overview?.servers_non_compliant ?? (overviewLoading ? '…' : '—')"
        to="/servers"
        view-all-label="View"
      />
      <StatCard
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
        <div v-else-if="topViolations.top_rules.length === 0 && sortedDrift.length === 0"
             class="text-sm text-muted-foreground py-6 text-center">
          No violations yet — publish a baseline and import policy rules to start scoring.
        </div>
        <template v-else>
          <ul v-if="topViolations.top_rules.length" class="divide-y divide-border">
            <li v-for="r in topViolations.top_rules.slice(0, 5)" :key="r.rule_id" class="py-2 flex items-center justify-between gap-2">
              <div class="min-w-0">
                <p class="text-sm font-medium truncate" :title="r.title">{{ r.title }}</p>
                <p class="text-xs text-muted-foreground font-mono truncate">{{ r.rule_key }} · {{ r.domain }}</p>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <Badge :color="SEVERITY_COLORS[r.severity] ?? 'gray'" size="xs">{{ r.severity }}</Badge>
                <Badge color="gray" size="xs">{{ r.fail_count }}×</Badge>
              </div>
            </li>
          </ul>
          <ul v-if="sortedDrift.length" class="divide-y divide-border mt-2">
            <li v-for="d in sortedDrift.slice(0, 5)" :key="String(d.id)" class="py-2 flex items-center justify-between gap-2">
              <div class="min-w-0">
                <p class="text-sm font-medium truncate">{{ d.summary }}</p>
                <p class="text-xs text-muted-foreground font-mono truncate">
                  {{ new Date(String(d.time)).toLocaleString() }} · {{ d.domain }} · {{ d.compared_against }}
                </p>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <Badge :color="SEVERITY_COLORS[String(d.severity)] ?? 'gray'" size="xs">{{ d.severity }}</Badge>
                <Button variant="ghost" size="xs" @click="navigateTo(`/compliance/drift/${d.id}`)">View</Button>
              </div>
            </li>
          </ul>
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
        <p v-else-if="topChangedFiles.length === 0" class="text-sm text-muted-foreground py-6 text-center">
          No file changes tracked yet (7-day window).
        </p>
        <ul v-else class="divide-y divide-border">
          <li v-for="f in topChangedFiles.slice(0, 8)" :key="f.path" class="py-2 flex items-center justify-between gap-2">
            <NuxtLink
              :to="`/compliance/file-integrity?path=${encodeURIComponent(f.path)}`"
              class="text-sm font-mono truncate hover:underline hover:text-primary" :title="f.path"
            >
              {{ f.path }}
            </NuxtLink>
            <Badge color="gray" size="xs">{{ f.change_count }}×</Badge>
          </li>
        </ul>
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
        <p v-else-if="baselines.length === 0" class="text-sm text-muted-foreground py-4 text-center">
          No baselines yet. <NuxtLink to="/compliance/baselines" class="text-primary hover:underline">Create one</NuxtLink>.
        </p>
        <ul v-else class="divide-y divide-border">
          <li v-for="b in baselines.slice(0, 5)" :key="b.id" class="py-2.5 flex items-center justify-between">
            <div>
              <NuxtLink :to="`/compliance/baselines/${b.id}`" class="text-sm font-medium hover:underline">{{ b.name }}</NuxtLink>
              <p class="text-xs text-muted-foreground font-mono">{{ b.scope_type }}</p>
            </div>
            <Badge v-if="b.is_enabled" color="green" size="xs">Enabled</Badge>
            <Badge v-else color="gray" size="xs">Disabled</Badge>
          </li>
        </ul>
      </Card>

      <Card>
        <template #header>
          <div class="flex items-center justify-between">
            <p class="label-caps">Recent assessments</p>
            <Button v-if="canEdit" variant="outline" size="xs" @click="showRunAssessment = true">Run assessment</Button>
          </div>
        </template>
        <Skeleton v-if="assessmentsLoading" class="h-24 w-full" />
        <p v-else-if="assessments.length === 0" class="text-sm text-muted-foreground py-4 text-center">
          No assessments yet. Runs on-demand evaluation of the current fleet state against a policy set.
        </p>
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
