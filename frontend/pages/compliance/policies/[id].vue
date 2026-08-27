<script setup lang="ts">
import { SEVERITY_COLORS } from '~/utils/complianceColors'
const route = useRoute()
const policySetId = String(route.params.id)

const store = useComplianceStore()
const { selectedPolicySet, policySetRules, policySetCoverage } = storeToRefs(store)
const { canEdit, isAdmin } = useCurrentUser()
const toast = useToast()

onMounted(async () => {
  await store.fetchPolicySet(policySetId)
  await Promise.all([store.fetchPolicySetRules(policySetId), store.fetchPolicySetCoverage(policySetId)])
})

const STATUS_COLORS: Record<string, string> = {
  DRAFT: 'gray', PUBLISHED: 'green', ARCHIVED: 'gray',
}

const busy = ref(false)

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
  if (!confirm('Archive this policy set? It will stop applying to any assigned scope.')) return
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
  { label: 'Coverage', slot: 'coverage' },
  { label: 'Remediation', slot: 'remediation' },
]

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
      <NuxtLink :to="`/compliance/policies/${selectedPolicySet.parent_policy_set_id}`" class="text-primary hover:underline">
        a previously published set
      </NuxtLink>
    </p>

    <AppTabs :items="tabs">
      <template #rules>
        <Alert v-if="policySetRules.length === 0" color="amber" class="mb-4">
          This policy set has no rules and cannot be published.
          <NuxtLink to="/compliance/policies" class="underline">Use "Import from ComplianceAsCode"</NuxtLink>
          on the Policy Sets list to populate it.
        </Alert>
        <DataTable
          :rows="policySetRules"
          :columns="columns"
          row-key="id"
          sortable
          :page-size="25"
          empty-title="No rules"
        >
          <template #domain-data="{ row }"><Badge color="gray" size="xs">{{ row.domain }}</Badge></template>
          <template #severity-data="{ row }">
            <Badge :color="SEVERITY_COLORS[String(row.severity)] ?? 'gray'" size="xs">{{ row.severity }}</Badge>
          </template>
          <template #check_source-data="{ row }">
            <Badge :color="row.check_source === 'CEL' ? 'green' : 'gray'" size="xs">{{ row.check_source }}</Badge>
          </template>
        </DataTable>
      </template>

      <template #coverage>
        <div v-if="policySetCoverage" class="grid grid-cols-3 gap-4">
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
      </template>
    </AppTabs>
  </div>
  <Skeleton v-else class="h-64 w-full" />
</template>
