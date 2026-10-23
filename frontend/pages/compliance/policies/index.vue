<script setup lang="ts">
import { Download, Plus, RefreshCw } from 'lucide-vue-next'
import type { PolicyTemplate, ScopeType } from '~/stores/compliance'

const store = useComplianceStore()
const { policySets, policySetsTotal, policySetsLoading, policySetsNextCursor, policyTemplates, policyTemplatesLoading } =
  storeToRefs(store)
const { canEdit, isAdmin } = useCurrentUser()
const toast = useToast()

onMounted(async () => {
  await Promise.all([store.fetchPolicySets(), store.fetchPolicyTemplates()])
})

const columns = [
  { key: 'name', label: 'Name' },
  { key: 'framework', label: 'Framework' },
  { key: 'version', label: 'Version' },
  { key: 'status', label: 'Status' },
  { key: 'created_at', label: 'Created' },
]

// ── Create ────────────────────────────────────────────────────────────────────
// One dialog, one path: pick a starting point, name it, optionally scope it.
// The "from a template" path creates the policy set AND its rules AND the
// scope assignment in a single request — a policy set never exists in a
// half-built state.
type Start = 'template' | 'empty'

const SCOPES: { value: ScopeType; label: string }[] = [
  { value: 'GLOBAL', label: 'Entire fleet' },
  { value: 'OS', label: 'By operating system' },
  { value: 'ENVIRONMENT', label: 'By environment' },
  { value: 'DATACENTER', label: 'By datacenter' },
  { value: 'CLUSTER', label: 'By cluster' },
  { value: 'APPLICATION', label: 'By application' },
  { value: 'ROLE', label: 'By role' },
]

const showCreate = ref(false)
const start = ref<Start>('template')
const templateKey = ref('')
const form = ref({ name: '', slug: '', description: '', scope_type: 'GLOBAL' })
const creating = ref(false)
const createErrors = reactive({ name: '', template: '' })

// Deep link from the command palette: /compliance/policies?action=new
const route = useRoute()
onMounted(() => {
  if (route.query.action === 'new') showCreate.value = true
})

const selectedTemplate = computed<PolicyTemplate | null>(
  () => policyTemplates.value.find((t) => t.key === templateKey.value) ?? null,
)

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 100)
}

// Picking a template prefills the name — the operator only overrides it
// when they want to. Same pattern as Wazuh's "CIS Distribution" policies
// and Tenable's baseline creation: the content has a name already.
function onTemplateChange(key: string) {
  templateKey.value = key
  const tpl = policyTemplates.value.find((t) => t.key === key)
  if (tpl) {
    form.value.name = tpl.name
    form.value.description = tpl.description
  }
}

function validateCreate(): boolean {
  createErrors.name = form.value.name.trim() ? '' : 'Name is required.'
  createErrors.template =
    start.value === 'template' && !templateKey.value ? 'Pick a template.' : ''
  return !createErrors.name && !createErrors.template
}

function resetForm() {
  start.value = 'template'
  templateKey.value = ''
  form.value = { name: '', slug: '', description: '', scope_type: 'GLOBAL' }
  createErrors.name = ''
  createErrors.template = ''
}

async function submitCreate() {
  if (!validateCreate()) return
  creating.value = true
  try {
    if (start.value === 'template') {
      const res = await store.createPolicySetFromTemplate({
        template_key: templateKey.value,
        name: form.value.name.trim(),
        slug: form.value.slug.trim() || undefined,
        description: form.value.description.trim() || undefined,
        scope_type: form.value.scope_type as ScopeType,
      })
      toast.add({
        title: 'Policy set created',
        description: `${res.rules_added} rules added from the template. Publish it to make it live.`,
      })
    } else {
      await store.createPolicySet({
        name: form.value.name.trim(),
        slug: form.value.slug.trim() || slugify(form.value.name),
        framework: 'INTERNAL',
        description: form.value.description.trim() || undefined,
      })
      toast.add({
        title: 'Policy set created',
        description: 'It has no rules yet — add rules from the catalog before publishing.',
      })
    }
    showCreate.value = false
    resetForm()
  } catch (err) {
    toast.add({
      title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to create policy set',
      color: 'red',
    })
  } finally {
    creating.value = false
  }
}

// ── Import from ComplianceAsCode ──────────────────────────────────────────────
// Admin-only. Importing content is a separate concern from building a
// profile: content goes into the catalog, a profile selects from it.
const showImport = ref(false)
const importForm = ref({ profile_id: '', content_version: '', datastream_url: '' })
const importing = ref(false)
const importError = ref<string | null>(null)

async function submitImport() {
  importError.value = null
  if (!importForm.value.content_version || !importForm.value.datastream_url) {
    importError.value = 'Content version and datastream URL are required.'
    return
  }
  importing.value = true
  try {
    const res = await store.importPolicySet({
      source: 'complianceascode',
      profile_id: importForm.value.profile_id || undefined,
      content_version: importForm.value.content_version,
      datastream_url: importForm.value.datastream_url,
    })
    toast.add({ title: 'Import started', description: `Job ${res.job_id} — running in the background` })
    showImport.value = false
    importForm.value = { profile_id: '', content_version: '', datastream_url: '' }
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to start import', color: 'red' })
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <div>
    <PageHeader>
      <Button variant="outline" @click="store.fetchPolicySets()">
        <RefreshCw class="size-4" /> Refresh
      </Button>
      <div class="flex items-center gap-3">
        <Badge color="gray">{{ policySetsTotal }} policy sets</Badge>
        <Button v-if="isAdmin" variant="outline" @click="showImport = true">
          <Download class="size-4" /> Import content
        </Button>
        <Button v-if="canEdit" @click="showCreate = true">
          <Plus class="size-4" /> New policy set
        </Button>
      </div>
    </PageHeader>

    <DataTable
      :rows="policySets"
      :columns="columns"
      :loading="policySetsLoading"
      sortable
      :page-size="25"
      empty-title="No policy sets"
      empty-description="Start from a template to get a ready-to-use policy set in one step."
      rows-clickable
      @row-click="(row) => navigateTo(`/compliance/policies/${row.id}`)"
     caption="Policy sets" preferences-key="compliance-policy-sets">
      <template #name-data="{ row }">
        <div>
          <p class="font-medium">{{ row.name }}</p>
          <p class="text-xs text-muted-foreground font-mono">{{ row.slug }}</p>
        </div>
      </template>
      <template #framework-data="{ row }">
        <Badge color="gray" size="xs">{{ row.framework }}</Badge>
      </template>
      <template #status-data="{ row }">
        <Badge :color="row.status === 'PUBLISHED' ? 'green' : 'gray'" size="xs">{{ row.status }}</Badge>
      </template>
      <template #created_at-data="{ row }">
        <span class="font-mono text-xs">{{ new Date(String(row.created_at)).toLocaleDateString() }}</span>
      </template>
    </DataTable>

    <div v-if="policySetsNextCursor" class="mt-4 flex justify-center">
      <Button variant="outline" @click="store.fetchPolicySets(policySetsNextCursor!)">
        Load more
      </Button>
    </div>

    <!-- Create -->
    <Dialog v-model="showCreate" title="New policy set" size="xl">
      <template #body>
        <div class="space-y-5">
          <!-- Starting point -->
          <div class="flex gap-2">
            <button
              type="button"
              class="focus-ring flex-1 rounded-[var(--radius-lg)] border px-4 py-3 text-left transition-colors"
              :class="start === 'template'
                ? 'border-primary bg-primary/5'
                : 'border-border hover:border-muted-foreground/40'"
              @click="start = 'template'"
            >
              <p class="text-sm font-medium">From a template</p>
              <p class="text-xs text-muted-foreground">Ready-made profile, rules included</p>
            </button>
            <button
              type="button"
              class="focus-ring flex-1 rounded-[var(--radius-lg)] border px-4 py-3 text-left transition-colors"
              :class="start === 'empty'
                ? 'border-primary bg-primary/5'
                : 'border-border hover:border-muted-foreground/40'"
              @click="start = 'empty'"
            >
              <p class="text-sm font-medium">Start empty</p>
              <p class="text-xs text-muted-foreground">Pick rules yourself from the catalog</p>
            </button>
          </div>

          <!-- Template picker -->
          <div v-if="start === 'template'" class="space-y-2">
            <FormField label="Template" required :error="createErrors.template">
              <div class="space-y-2 max-h-64 overflow-y-auto pr-1">
                <button
                  v-for="tpl in policyTemplates"
                  :key="tpl.key"
                  type="button"
                  class="focus-ring w-full rounded-[var(--radius-lg)] border px-4 py-3 text-left transition-colors"
                  :class="templateKey === tpl.key
                    ? 'border-primary bg-primary/5'
                    : 'border-border hover:border-muted-foreground/40'"
                  @click="onTemplateChange(tpl.key)"
                >
                  <div class="flex items-baseline justify-between gap-3">
                    <p class="text-sm font-medium">{{ tpl.name }}</p>
                    <Badge color="gray" size="xs">{{ tpl.rule_count }} rules</Badge>
                  </div>
                  <p class="mt-1 text-xs text-muted-foreground">{{ tpl.description }}</p>
                  <p v-if="tpl.rule_count === 0" class="mt-1 text-xs text-warning">
                    No rules in the catalog match this template yet — import content first.
                  </p>
                </button>
                <p v-if="!policyTemplatesLoading && policyTemplates.length === 0" class="text-sm text-muted-foreground">
                  No templates available.
                </p>
              </div>
            </FormField>
          </div>

          <!-- Details -->
          <FormField label="Name" required :error="createErrors.name">
            <Input v-model="form.name" placeholder="e.g. CIS-mapped rules — production" />
          </FormField>

          <FormField
            label="Slug"
            help="Optional. Lowercase letters, digits and dashes. Left empty, it is generated from the name."
          >
            <Input v-model="form.slug" :placeholder="slugify(form.name) || 'cis-production'" />
          </FormField>

          <FormField label="Description">
            <Textarea v-model="form.description" :rows="2" placeholder="What this policy set is for" />
          </FormField>

          <FormField
            v-if="start === 'template'"
            label="Apply to"
            help="The fleet scope this policy set is evaluated against."
          >
            <Select v-model="form.scope_type" :options="SCOPES" />
          </FormField>
        </div>
      </template>

      <template #footer>
        <Button variant="ghost" @click="showCreate = false">Cancel</Button>
        <Button :loading="creating" @click="submitCreate">Create policy set</Button>
      </template>
    </Dialog>

    <!-- Import -->
    <Dialog v-model="showImport" title="Import compliance content" size="lg">
      <template #body>
        <div class="space-y-4">
          <Alert color="blue">
            Importing pulls a profile from ComplianceAsCode into the rule catalog. Then build a
            policy set from it using a template.
          </Alert>
          <FormField
            label="Profile ID"
            help="Optional — e.g. xccdf_org.ssgproject.content_profile_cis_level1_server"
          >
            <Input v-model="importForm.profile_id" placeholder="Profile ID" />
          </FormField>
          <FormField label="Content version" required>
            <Input v-model="importForm.content_version" placeholder="e.g. 0.1.72" />
          </FormField>
          <FormField label="Datastream URL" required :error="importError ?? undefined">
            <Input v-model="importForm.datastream_url" placeholder="https://.../datastream.xml" />
          </FormField>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showImport = false">Cancel</Button>
        <Button :loading="importing" @click="submitImport">Start import</Button>
      </template>
    </Dialog>
  </div>
</template>
