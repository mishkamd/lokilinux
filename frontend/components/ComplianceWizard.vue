<script setup lang="ts">
// New-policy wizard (Enterprise Compliance plan U10 Task 3) — 8 steps over
// EXISTING APIs only (create policy_set → attach rules → assignment scope
// → schedule → remediation mode → publish → review); no new backend
// resource, this only sequences calls the plain "New policy set" dialog +
// Rule Catalog + Policy Assignments + U7's remediation endpoint already
// expose one at a time.
import type { ScopeType } from '~/stores/compliance'

const emit = defineEmits<{ close: []; saved: [] }>()

const store = useComplianceStore()
const { rules, rulesLoading, standards } = storeToRefs(store)
const api = useApi()
const toast = useToast()

const STEPS = ['Standard', 'Basic Info', 'Rules', 'Assignment', 'Schedule', 'Remediation', 'Publish', 'Review']
const FRAMEWORKS = ['CIS', 'NIST', 'PCI_DSS', 'ISO27001', 'STIG', 'INTERNAL']
const SCOPE_TYPES: ScopeType[] = ['GLOBAL', 'OS', 'ROLE', 'ENVIRONMENT', 'DATACENTER', 'CLUSTER', 'APPLICATION']

const form = ref({
  // Standard (optional — only pre-filters step 3's rule list, not stored)
  standardKey: '',

  // Basic Info
  name: '',
  slug: '',
  framework: 'INTERNAL',
  version: '',
  description: '',

  // Rules
  selectedRuleIds: [] as string[],
  ruleSeverityFilter: '',
  ruleDomainFilter: '',

  // Assignment (optional — skip if scopeType is left empty)
  scopeType: '' as '' | ScopeType,
  scopeSelector: '{}',

  // Schedule — Autopilot A1 setting (global, not per-policy; see
  // settings_schema.py's own ponytail note — config-only until A1 ships)
  autoAssessmentDays: 0,

  // Remediation
  remediationMode: 'ASSISTED' as 'MONITOR' | 'ASSISTED' | 'AUTOMATIC',
  remediationAllowed: [] as string[],
  remediationForbidden: [] as string[],

  // Publish
  publishNow: false,
})

onMounted(async () => {
  if (!standards.value.length) await store.fetchStandards()
  try {
    const settings = await api.get<{ compliance?: { auto_assessment_days?: number } }>('/admin/settings')
    form.value.autoAssessmentDays = settings.compliance?.auto_assessment_days ?? 0
  } catch {
    // settings read is a convenience default — the wizard still works without it
  }
})

const domainOptions = computed(() => [...new Set(rules.value.map((r) => r.domain))].sort())

async function loadRules() {
  store.ruleFilters.severity = form.value.ruleSeverityFilter
  store.ruleFilters.domain = form.value.ruleDomainFilter
  store.ruleFilters.framework = form.value.standardKey
  await store.fetchRules()
}

const submitting = ref(false)
const stepError = ref<string | null>(null)
const stepperRef = ref<any>(null)

function onContinue() {
  const idx = stepperRef.value.stepper.index.value
  const err = validateStep(idx)
  if (err) {
    stepError.value = err
    return
  }
  stepError.value = null
  if (STEPS[idx] === 'Standard' || STEPS[idx] === 'Rules') void loadRules()
  stepperRef.value.stepper.goToNext()
}

function validateStep(stepIndex: number): string | null {
  switch (STEPS[stepIndex]) {
    case 'Basic Info':
      if (!form.value.name.trim()) return 'Name is required'
      if (!form.value.slug.trim()) return 'Slug is required'
      return null
    case 'Rules':
      if (form.value.selectedRuleIds.length === 0) return 'Select at least one rule — a policy set with zero rules cannot be published'
      return null
    case 'Assignment':
      if (form.value.scopeType) {
        try {
          JSON.parse(form.value.scopeSelector || '{}')
        } catch {
          return 'Scope selector must be valid JSON'
        }
      }
      return null
    default:
      return null
  }
}

async function submit() {
  const err = validateStep(2) // Rules — the last step with hard validation
  if (err) {
    stepError.value = err
    return
  }
  submitting.value = true
  try {
    const policySet = await store.createPolicySet({
      name: form.value.name,
      slug: form.value.slug,
      framework: form.value.framework,
      version: form.value.version || undefined,
      description: form.value.description || undefined,
    })

    for (const ruleId of form.value.selectedRuleIds) {
      await store.addPolicySetRule(policySet.id, ruleId)
    }

    if (form.value.scopeType) {
      await store.createPolicyAssignment({
        policy_set_id: policySet.id,
        scope_type: form.value.scopeType,
        scope_selector: JSON.parse(form.value.scopeSelector || '{}'),
      })
    }

    await api.put('/admin/settings', { compliance: { auto_assessment_days: form.value.autoAssessmentDays } })

    if (form.value.remediationMode !== 'ASSISTED' || form.value.remediationAllowed.length || form.value.remediationForbidden.length) {
      await store.setPolicySetRemediation(policySet.id, {
        mode: form.value.remediationMode,
        allowed: form.value.remediationAllowed,
        forbidden: form.value.remediationForbidden,
      })
    }

    if (form.value.publishNow) {
      await store.publishPolicySet(policySet.id)
    }

    toast.add({ title: 'Policy set created', description: `${form.value.selectedRuleIds.length} rule(s) attached` })
    emit('saved')
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to create policy set', color: 'red' })
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <Dialog
    :model-value="true"
    title="New policy set — guided setup"
    size="xl"
    @update:model-value="(open: boolean) => { if (!open) emit('close') }"
  >
    <template #body>
      <Stepper ref="stepperRef" :steps="STEPS" v-slot="{ stepper }">
        <div class="min-h-[320px]">
          <div v-if="stepError" class="mb-4">
            <Alert color="red" :description="stepError" />
          </div>

          <div v-if="stepper.current.value === 'Standard'" class="space-y-4">
            <p class="text-sm text-muted-foreground">
              Optional — pick a standard to pre-filter the Rules step to controls it maps. Skip to browse every rule instead.
            </p>
            <FormField label="Standard">
              <Select
                v-model="form.standardKey"
                :options="[{ label: 'All rules (no filter)', value: '' }, ...standards.map((s) => ({ label: `${s.name} ${s.version}`, value: s.key }))]"
              />
            </FormField>
          </div>

          <div v-else-if="stepper.current.value === 'Basic Info'" class="space-y-4">
            <FormField label="Name" required><Input v-model="form.name" placeholder="Internal SSH Hardening" /></FormField>
            <FormField label="Slug" required help="Stable identifier, e.g. internal-ssh-hardening">
              <Input v-model="form.slug" placeholder="internal-ssh-hardening" />
            </FormField>
            <FormField label="Framework" required><Select v-model="form.framework" :options="FRAMEWORKS" /></FormField>
            <FormField label="Version"><Input v-model="form.version" placeholder="Optional" /></FormField>
            <FormField label="Description"><Textarea v-model="form.description" placeholder="Optional" /></FormField>
          </div>

          <div v-else-if="stepper.current.value === 'Rules'" class="space-y-4">
            <div class="grid grid-cols-2 gap-4">
              <FormField label="Severity">
                <Select v-model="form.ruleSeverityFilter" :options="['', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW']" placeholder="Any" @change="loadRules" />
              </FormField>
              <FormField label="Domain">
                <Select v-model="form.ruleDomainFilter" :options="['', ...domainOptions]" placeholder="Any" @change="loadRules" />
              </FormField>
            </div>
            <p class="text-xs text-muted-foreground">{{ form.selectedRuleIds.length }} rule(s) selected</p>
            <DataTable
              :rows="rules"
              :columns="[{ key: 'title', label: 'Rule' }, { key: 'domain', label: 'Domain' }, { key: 'severity', label: 'Severity' }]"
              :loading="rulesLoading"
              :page-size="10"
              selectable
              :selected="form.selectedRuleIds"
              @update:selected="(ids) => form.selectedRuleIds = ids as string[]"
              empty-title="No rules match these filters"
            >
              <template #domain-data="{ row }"><Badge color="gray" size="xs">{{ row.domain }}</Badge></template>
              <template #severity-data="{ row }"><Badge color="gray" size="xs">{{ row.severity }}</Badge></template>
            </DataTable>
          </div>

          <div v-else-if="stepper.current.value === 'Assignment'" class="space-y-4">
            <p class="text-sm text-muted-foreground">Optional — assign this policy to a scope now, or skip and do it later from the policy set page.</p>
            <FormField label="Scope type">
              <Select v-model="form.scopeType" :options="['', ...SCOPE_TYPES]" placeholder="Skip — assign later" />
            </FormField>
            <FormField v-if="form.scopeType" label="Scope selector" help="JSON, e.g. {&quot;os_distro&quot;: &quot;rocky&quot;}">
              <Textarea v-model="form.scopeSelector" class="font-mono" :rows="3" />
            </FormField>
          </div>

          <div v-else-if="stepper.current.value === 'Schedule'" class="space-y-4">
            <FormField label="Assessment cadence (fleet-wide)" help="0 = manual assessments only. This is a platform-wide setting, not specific to this policy.">
              <Input v-model.number="form.autoAssessmentDays" type="number" min="0" />
            </FormField>
          </div>

          <div v-else-if="stepper.current.value === 'Remediation'" class="space-y-4">
            <FormField label="Mode">
              <Select
                v-model="form.remediationMode"
                :options="[
                  { label: 'MONITOR — findings only, no remediation ever', value: 'MONITOR' },
                  { label: 'ASSISTED — manual approve + dispatch (default)', value: 'ASSISTED' },
                  { label: 'AUTOMATIC — auto-fixes when every safety gate passes', value: 'AUTOMATIC' },
                ]"
              />
            </FormField>
            <template v-if="form.remediationMode === 'AUTOMATIC'">
              <FormField label="Allowed domains" help="Empty = every domain this policy covers">
                <MultiSelect v-model="form.remediationAllowed" :options="domainOptions" />
              </FormField>
              <FormField label="Forbidden domains">
                <MultiSelect v-model="form.remediationForbidden" :options="domainOptions" />
              </FormField>
              <Alert color="yellow">
                Also requires the platform kill-switch (Settings → Compliance) plus a rollback-capable template and an open maintenance window per agent.
              </Alert>
            </template>
          </div>

          <div v-else-if="stepper.current.value === 'Publish'" class="space-y-4">
            <div class="flex items-center gap-2">
              <Switch v-model="form.publishNow" />
              <span class="text-[13px]">Publish immediately (otherwise stays DRAFT)</span>
            </div>
          </div>

          <div v-else class="space-y-3 text-sm">
            <dl class="grid grid-cols-2 gap-x-6 gap-y-2">
              <div><dt class="text-muted-foreground">Name</dt><dd class="font-medium">{{ form.name }}</dd></div>
              <div><dt class="text-muted-foreground">Framework</dt><dd>{{ form.framework }}</dd></div>
              <div><dt class="text-muted-foreground">Rules</dt><dd>{{ form.selectedRuleIds.length }} attached</dd></div>
              <div><dt class="text-muted-foreground">Assignment</dt><dd>{{ form.scopeType || 'None — assign later' }}</dd></div>
              <div><dt class="text-muted-foreground">Remediation</dt><dd>{{ form.remediationMode }}</dd></div>
              <div><dt class="text-muted-foreground">Status</dt><dd>{{ form.publishNow ? 'PUBLISHED' : 'DRAFT' }}</dd></div>
            </dl>
          </div>
        </div>
      </Stepper>
    </template>
    <template #footer>
      <Button variant="ghost" :disabled="stepperRef?.stepper.isFirst.value" @click="stepperRef.stepper.goToPrevious()">Back</Button>
      <Button v-if="!stepperRef?.stepper.isLast.value" @click="onContinue">Continue</Button>
      <Button v-else :loading="submitting" @click="submit">Create policy set</Button>
    </template>
  </Dialog>
</template>
