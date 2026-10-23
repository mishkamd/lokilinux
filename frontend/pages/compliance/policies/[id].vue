<script setup lang="ts">
import { SEVERITY_COLORS } from '~/utils/complianceColors'
import type { ScopeType } from '~/stores/compliance'
import { Download } from 'lucide-vue-next'
const route = useRoute()
const policySetId = String(route.params.id)

const store = useComplianceStore()
const { selectedPolicySet, policySetRules, policySetCoverage, policyAssignments, catalogRules, policySetRemediation } =
  storeToRefs(store)
const { canEdit, isAdmin } = useCurrentUser()
const toast = useToast()

onMounted(async () => {
  await store.fetchPolicySet(policySetId)
  await Promise.all([
    store.fetchPolicySetRules(policySetId),
    store.fetchPolicySetCoverage(policySetId),
    store.fetchPolicyAssignments(policySetId),
    store.fetchPolicySetRemediation(policySetId),
  ])
})

const STATUS_COLORS: Record<string, string> = {
  DRAFT: 'gray', PUBLISHED: 'green', ARCHIVED: 'gray',
}

const busy = ref(false)
// Destructive actions go through the app's confirm dialog, never window.confirm().
const showArchiveConfirm = ref(false)

async function publish() {
  busy.value = true
  try {
    await store.publishPolicySet(policySetId)
    toast.add({ title: 'Policy set published' })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to publish', color: 'red' })
  } finally {
    busy.value = false
  }
}

async function archive() {
  // Destructive actions go through the app's confirm dialog, never window.confirm().
  showArchiveConfirm.value = true
}

async function doArchive() {
  showArchiveConfirm.value = false
  busy.value = true
  try {
    await store.archivePolicySet(policySetId)
    toast.add({ title: 'Policy set archived' })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to archive', color: 'red' })
  } finally {
    busy.value = false
  }
}

async function newVersion() {
  busy.value = true
  try {
    const clone = await store.newPolicySetVersion(policySetId)
    toast.add({ title: 'New draft version created' })
    await navigateTo(`/compliance/policies/${clone.id}`)
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to create new version', color: 'red' })
  } finally {
    busy.value = false
  }
}

const tabs = [
  { label: 'Rules', slot: 'rules' },
  { label: 'Scope', slot: 'scope' },
  { label: 'Coverage', slot: 'coverage' },
  { label: 'Remediation', slot: 'remediation' },
]

// ── Add rules from the catalog ────────────────────────────────────────────────
const catalogSearch = ref('')
const catalogDomain = ref('')
const catalogSeverity = ref('')
const addingRule = ref<string | null>(null)

// The catalog is fetched once per page — the add-rule panel filters it
// client-side. A policy set holds tens of rules, the catalog hundreds.
const catalogDomainOptions = computed(() => [
  { label: 'All domains', value: '' },
  ...[...new Set(catalogRules.value.map((r) => r.domain))].sort().map((d) => ({ label: d, value: d })),
])
const catalogRows = computed(() => {
  const term = catalogSearch.value.trim().toLowerCase()
  return catalogRules.value
    .filter((r) => !catalogDomain.value || r.domain === catalogDomain.value)
    .filter((r) => !catalogSeverity.value || r.severity === catalogSeverity.value)
    .filter((r) => !term || r.title.toLowerCase().includes(term) || r.rule_key.toLowerCase().includes(term))
    .slice(0, 50)
})
const inSet = computed(() => new Set(policySetRules.value.map((r) => r.id)))

onMounted(async () => {
  await store.fetchCatalogRules()
})

async function addRule(ruleId: string) {
  addingRule.value = ruleId
  try {
    await store.addPolicySetRule(policySetId, ruleId)
    await store.fetchPolicySetRules(policySetId)
    toast.add({ title: 'Rule added' })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to add rule', color: 'red' })
  } finally {
    addingRule.value = null
  }
}

const removingRule = ref<string | null>(null)
async function removeRule(ruleId: string, ruleKey: string) {
  removingRule.value = ruleId
  try {
    await store.removePolicySetRule(policySetId, ruleId)
    toast.add({ title: 'Rule removed', description: ruleKey })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to remove rule', color: 'red' })
  } finally {
    removingRule.value = null
  }
}

// ── Export ────────────────────────────────────────────────────────────────────
const exporting = ref(false)
async function exportSet(format: 'json' | 'yaml') {
  exporting.value = true
  try {
    const blob = await store.exportPolicySet(policySetId, format)
    const url = URL.createObjectURL(blob as Blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${selectedPolicySet.value?.slug ?? 'policy-set'}.${format}`
    a.click()
    URL.revokeObjectURL(url)
    toast.add({ title: 'Policy set exported' })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Export failed', color: 'red' })
  } finally {
    exporting.value = false
  }
}

// ── Scope ─────────────────────────────────────────────────────────────────────
const SCOPE_OPTIONS: { label: string; value: ScopeType }[] = [
  { label: 'Entire fleet', value: 'GLOBAL' },
  { label: 'By operating system', value: 'OS' },
  { label: 'By role', value: 'ROLE' },
  { label: 'By environment', value: 'ENVIRONMENT' },
  { label: 'By datacenter', value: 'DATACENTER' },
  { label: 'By cluster', value: 'CLUSTER' },
  { label: 'By application', value: 'APPLICATION' },
]
const newScopeType = ref<ScopeType>('GLOBAL')
const addingScope = ref(false)

async function addScope() {
  addingScope.value = true
  try {
    await store.createPolicyAssignment({
      policy_set_id: policySetId,
      scope_type: newScopeType.value,
      scope_selector: {},
    })
    await store.fetchPolicyAssignments(policySetId)
    toast.add({ title: 'Policy set applied to scope' })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to apply', color: 'red' })
  } finally {
    addingScope.value = false
  }
}

// Remediation mode form (plan U7/KTD8) — a policy_set with remediation
// unset behaves as ASSISTED, so the form defaults there too rather than
// showing an empty/undefined mode.
const remediationMode = ref<'MONITOR' | 'ASSISTED' | 'AUTOMATIC'>(
  selectedPolicySet.value?.remediation?.mode ?? 'ASSISTED',
)
const remediationAllowed = ref<string[]>(selectedPolicySet.value?.remediation?.allowed ?? [])
const remediationForbidden = ref<string[]>(selectedPolicySet.value?.remediation?.forbidden ?? [])
watch(selectedPolicySet, (p) => {
  remediationMode.value = p?.remediation?.mode ?? 'ASSISTED'
  remediationAllowed.value = p?.remediation?.allowed ?? []
  remediationForbidden.value = p?.remediation?.forbidden ?? []
})

const domainOptions = computed(() => [...new Set(policySetRules.value.map((r) => String(r.domain)))].sort())

// The per-rule remediation list — one row per rule, whether or not it has a
// remediation, so an operator can see what's fixable and what isn't.
const remediationRows = computed(() => policySetRemediation.value)

const savingRemediation = ref(false)
async function saveRemediation() {
  savingRemediation.value = true
  try {
    await store.setPolicySetRemediation(policySetId, {
      mode: remediationMode.value,
      allowed: remediationAllowed.value,
      forbidden: remediationForbidden.value,
    })
    toast.add({ title: 'Remediation mode saved' })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to save', color: 'red' })
  } finally {
    savingRemediation.value = false
  }
}

const columns = [
  { key: 'title', label: 'Rule' },
  { key: 'domain', label: 'Domain' },
  { key: 'severity', label: 'Severity' },
  { key: 'check_source', label: 'Coverage' },
  { key: 'actions', label: '' },
]
</script>

<template>
  <div v-if="selectedPolicySet">
    <PageHeader
      :title="selectedPolicySet.name"
      :description="selectedPolicySet.description || 'No description'"
      :back="{ to: '/compliance/policies', label: 'Back to policy sets' }"
    >
      <template #badges>
        <Badge color="gray">{{ selectedPolicySet.framework }}</Badge>
        <Badge :color="STATUS_COLORS[selectedPolicySet.status] ?? 'gray'">
          {{ selectedPolicySet.status }} · v{{ selectedPolicySet.published_version }}
        </Badge>
      </template>
      <template #actions>
        <Button size="sm" variant="outline" :loading="exporting" @click="exportSet('json')">
          <Download class="size-4" /> Export
        </Button>
        <Button v-if="canEdit && selectedPolicySet.status === 'DRAFT'" size="sm" :loading="busy" @click="publish">
          Publish
        </Button>
        <Button v-if="canEdit && selectedPolicySet.status === 'PUBLISHED'" size="sm" variant="outline" :loading="busy" @click="newVersion">
          New version
        </Button>
        <Button v-if="isAdmin && selectedPolicySet.status === 'PUBLISHED'" size="sm" color="amber" :loading="busy" @click="archive">
          Archive
        </Button>
      </template>
    </PageHeader>
    <p v-if="selectedPolicySet.parent_policy_set_id" class="text-xs text-muted-foreground mb-4">
      New version of
      <NuxtLink :to="`/compliance/policies/${selectedPolicySet.parent_policy_set_id}`" class="focus-ring text-primary-text hover:underline">
        a previously published set
      </NuxtLink>
    </p>

    <AppTabs :items="tabs">
      <template #rules>
        <Alert v-if="policySetRules.length === 0" color="amber" class="mb-4">
          This policy set has no rules and cannot be published. Add rules from the catalog below,
          or start from a
          <NuxtLink to="/compliance/policies" class="focus-ring underline">template</NuxtLink>
          instead.
        </Alert>
        <DataTable
          :rows="policySetRules"
          :columns="columns"
          row-key="id"
          sortable
          :page-size="25"
          empty-title="No rules"
         caption="Policy set rules">
          <template #domain-data="{ row }"><Badge color="gray" size="xs">{{ row.domain }}</Badge></template>
          <template #severity-data="{ row }">
            <Badge :color="SEVERITY_COLORS[String(row.severity)] ?? 'gray'" size="xs">{{ row.severity }}</Badge>
          </template>
          <template #check_source-data="{ row }">
            <Badge :color="row.check_source === 'CEL' ? 'green' : 'gray'" size="xs">{{ row.check_source }}</Badge>
          </template>
          <template #actions-data="{ row }">
            <Button
              v-if="canEdit && selectedPolicySet.status === 'DRAFT'"
              size="xs"
              variant="ghost"
              :loading="removingRule === row.id"
              @click.stop="removeRule(String(row.id), String(row.rule_key))"
            >
              Remove
            </Button>
          </template>
        </DataTable>

        <!-- Add rules from the catalog. Only a DRAFT can change: a published
             set is immutable by design, editing it means creating a new
             version (the "New version" action above). -->
        <Card v-if="canEdit && selectedPolicySet.status === 'DRAFT'" class="mt-4">
          <template #header>
            <h2 class="text-sm font-semibold">Add rules from the catalog</h2>
          </template>
          <div class="space-y-3">
            <div class="flex flex-wrap items-center gap-3">
              <Input v-model="catalogSearch" placeholder="Search the rule catalog…" class="w-72"
                     aria-label="Search the rule catalog" />
              <Select v-model="catalogDomain" :options="catalogDomainOptions" placeholder="All domains" class="w-44" />
              <Select v-model="catalogSeverity" :options="['', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW']" placeholder="Severity" class="w-36" />
            </div>
            <p v-if="catalogRows.length === 0" class="text-sm text-muted-foreground">
              No catalog rules match. Clear the search to see everything.
            </p>
            <ul v-else class="divide-y divide-border max-h-72 overflow-y-auto">
              <li v-for="rule in catalogRows" :key="rule.id" class="flex items-center gap-3 py-2">
                <div class="min-w-0 flex-1">
                  <p class="truncate text-sm">{{ rule.title }}</p>
                  <p class="truncate text-xs text-muted-foreground font-mono">{{ rule.rule_key }}</p>
                </div>
                <Badge :color="SEVERITY_COLORS[String(rule.severity)] ?? 'gray'" size="xs">{{ rule.severity }}</Badge>
                <Button
                  size="xs"
                  variant="outline"
                  :disabled="inSet.has(rule.id)"
                  :loading="addingRule === rule.id"
                  @click="addRule(rule.id)"
                >
                  {{ inSet.has(rule.id) ? 'Added' : 'Add' }}
                </Button>
              </li>
            </ul>
          </div>
        </Card>
      </template>

      <template #scope>
        <Card>
          <template #header>
            <h2 class="text-sm font-semibold">Applied to</h2>
          </template>
          <p v-if="policyAssignments.length === 0" class="text-sm text-muted-foreground">
            This policy set is not applied to any scope yet — nothing is evaluated for it.
          </p>
          <ul v-else class="space-y-2">
            <li v-for="a in policyAssignments" :key="a.id" class="flex items-center gap-3">
              <Badge color="gray" size="xs">{{ a.scope_type }}</Badge>
              <span class="font-mono text-xs text-muted-foreground">
                {{ Object.keys(a.scope_selector).length ? JSON.stringify(a.scope_selector) : 'entire fleet' }}
              </span>
            </li>
          </ul>
          <div v-if="canEdit" class="mt-4 flex flex-wrap items-end gap-3 border-t border-border pt-4">
            <FormField label="Scope type">
              <Select v-model="newScopeType" :options="SCOPE_OPTIONS" class="w-56" />
            </FormField>
            <Button variant="outline" :loading="addingScope" @click="addScope">Apply to scope</Button>
          </div>
        </Card>
      </template>

      <template #coverage>
        <div v-if="policySetCoverage" class="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Card>
            <p class="label-caps mb-1">CEL-mapped (evaluable)</p>
            <p class="text-2xl font-mono font-semibold tabular-nums">{{ policySetCoverage.mapped }}</p>
          </Card>
          <Card>
            <p class="label-caps mb-1">Unmapped</p>
            <p class="text-2xl font-mono font-semibold tabular-nums">{{ policySetCoverage.unmapped }}</p>
          </Card>
          <Card>
            <p class="label-caps mb-1">Coverage</p>
            <p class="text-2xl font-mono font-semibold tabular-nums">{{ policySetCoverage.coverage_pct }}%</p>
          </Card>
        </div>
      </template>

      <template #remediation>
        <Card class="max-w-xl">
          <div class="space-y-4">
            <div>
              <p class="label-caps mb-1.5">Mode</p>
              <Select
                v-model="remediationMode"
                :options="[
                  { label: 'MONITOR — findings only, no remediation ever', value: 'MONITOR' },
                  { label: 'ASSISTED — manual approve + dispatch (default)', value: 'ASSISTED' },
                  { label: 'AUTOMATIC — auto-fixes when every safety gate passes', value: 'AUTOMATIC' },
                ]"
                class="w-full"
              />
            </div>

            <div v-if="remediationMode === 'AUTOMATIC'">
              <p class="label-caps mb-1.5">Allowed domains</p>
              <MultiSelect v-model="remediationAllowed" :options="domainOptions" placeholder="All domains this policy covers" />
              <p class="text-xs text-muted-foreground mt-1">Empty = every domain this policy covers is eligible.</p>
            </div>

            <div v-if="remediationMode === 'AUTOMATIC'">
              <p class="label-caps mb-1.5">Forbidden domains</p>
              <MultiSelect v-model="remediationForbidden" :options="domainOptions" placeholder="None" />
              <p class="text-xs text-muted-foreground mt-1">Always excluded, even if listed as allowed.</p>
            </div>

            <Alert v-if="remediationMode === 'AUTOMATIC'" color="amber">
              AUTOMATIC also requires the platform-wide kill-switch
              (Settings → Compliance → Auto-remediation) to be on, a matching
              remediation template with a rollback step, and an open
              maintenance window covering each agent — this list alone
              doesn't make anything run.
            </Alert>

            <Button v-if="canEdit" :loading="savingRemediation" @click="saveRemediation">
              Save
            </Button>
          </div>
        </Card>

        <!-- What would actually run. The operator picks AUTOMATIC; the exact
             commands are listed here, so the choice is reviewable before
             anything is dispatched to a host. -->
        <Card class="mt-4">
          <template #header>
            <div class="flex items-center justify-between">
              <p class="label-caps">Commands that would run</p>
              <Badge color="gray" size="xs">{{ remediationRows.length }} rules</Badge>
            </div>
          </template>
          <EmptyState v-if="remediationRows.length === 0">
            No rule in this policy set carries a remediation — findings are reported, not fixed.
          </EmptyState>
          <ul v-else class="divide-y divide-border">
            <li v-for="r in remediationRows" :key="r.rule_id" class="py-2">
              <div class="flex items-center gap-2">
                <span class="text-sm font-mono">{{ r.rule_key }}</span>
                <Badge :color="SEVERITY_COLORS[String(r.severity)] ?? 'gray'" size="xs">{{ r.severity }}</Badge>
                <Badge color="gray" size="xs">{{ r.domain }}</Badge>
              </div>
              <pre
                v-if="r.remediation"
                class="mt-1 font-mono text-xs whitespace-pre-wrap rounded-lg border p-2 bg-muted/30"
              >{{ r.remediation.body }}</pre>
              <p v-else class="mt-1 text-xs text-muted-foreground">
                {{ r.title }} — no remediation recorded, or your role cannot see it.
              </p>
            </li>
          </ul>
        </Card>
      </template>
    </AppTabs>

    <ConfirmDeleteDialog
      :model-value="showArchiveConfirm"
      title="Archive policy set"
      confirm-label="Archive"
      @update:model-value="showArchiveConfirm = false"
      @confirm="doArchive"
    >
      <p class="text-sm text-muted-foreground">
        Archive this policy set? It will stop applying to any assigned scope.
      </p>
    </ConfirmDeleteDialog>
  </div>
  <Skeleton v-else class="h-64 w-full" />
</template>
