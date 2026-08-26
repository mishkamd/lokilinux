<script setup lang="ts">
import { Download, Plus, RefreshCw } from 'lucide-vue-next'

const store = useComplianceStore()
const { policySets, policySetsTotal, policySetsLoading, policySetsNextCursor } = storeToRefs(store)
const { canEdit, isAdmin } = useCurrentUser()
const toast = useToast()

onMounted(() => store.fetchPolicySets())

const columns = [
  { key: 'name', label: 'Name' },
  { key: 'framework', label: 'Framework' },
  { key: 'version', label: 'Version' },
  { key: 'is_enabled', label: 'Status' },
  { key: 'created_at', label: 'Created' },
]

const showCreate = ref(false)
const form = ref({ name: '', slug: '', framework: 'INTERNAL', version: '', description: '' })
const creating = ref(false)
const FRAMEWORKS = ['CIS', 'NIST', 'PCI_DSS', 'ISO27001', 'STIG', 'INTERNAL']

async function submitCreate() {
  creating.value = true
  try {
    await store.createPolicySet({
      name: form.value.name, slug: form.value.slug, framework: form.value.framework,
      version: form.value.version || undefined, description: form.value.description || undefined,
    })
    toast.add({
      title: 'Policy set created',
      description: 'It has no rules yet and cannot be published — use "Import from ComplianceAsCode" to populate it.',
    })
    showCreate.value = false
    form.value = { name: '', slug: '', framework: 'INTERNAL', version: '', description: '' }
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to create policy set', color: 'red' })
  } finally {
    creating.value = false
  }
}

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
          <Download class="size-4" /> Import from ComplianceAsCode
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
      rows-clickable
      @row-click="(row) => navigateTo(`/compliance/policies/${row.id}`)"
    >
      <template #name-data="{ row }">
        <div>
          <p class="font-medium">{{ row.name }}</p>
          <p class="text-xs text-muted-foreground font-mono">{{ row.slug }}</p>
        </div>
      </template>
      <template #framework-data="{ row }">
        <Badge color="gray" size="xs">{{ row.framework }}</Badge>
      </template>
      <template #is_enabled-data="{ row }">
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

    <Dialog v-model="showCreate" title="New policy set">
      <template #body>
        <div class="space-y-4">
          <FormField label="Name" required><Input v-model="form.name" placeholder="Internal SSH Hardening" /></FormField>
          <FormField label="Slug" required help="Stable identifier, e.g. internal-ssh-hardening">
            <Input v-model="form.slug" placeholder="internal-ssh-hardening" />
          </FormField>
          <FormField label="Framework" required><Select v-model="form.framework" :options="FRAMEWORKS" /></FormField>
          <FormField label="Version"><Input v-model="form.version" placeholder="Optional" /></FormField>
          <FormField label="Description"><Input v-model="form.description" placeholder="Optional" /></FormField>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showCreate = false">Cancel</Button>
        <Button :loading="creating" :disabled="!form.name || !form.slug" @click="submitCreate">Create</Button>
      </template>
    </Dialog>

    <Dialog v-model="showImport" title="Import from ComplianceAsCode">
      <template #body>
        <div class="space-y-4">
          <FormField label="Datastream URL" required
                     help="URL to a standard XCCDF 1.2 datastream (e.g. an OS-packaged scap-security-guide file or your own mirror)">
            <Input v-model="importForm.datastream_url" placeholder="https://internal-mirror/ssg-rhel9-ds.xml" />
          </FormField>
          <FormField label="Content version" required help="Free-form tag tracked as compliance_rules.source_version">
            <Input v-model="importForm.content_version" placeholder="v0.1.81" />
          </FormField>
          <FormField label="Profile ID" help="Only import one profile's rule selection — leave blank to import every profile in the datastream">
            <Input v-model="importForm.profile_id" placeholder="xccdf_org.ssgproject.content_profile_cis" />
          </FormField>
          <Alert v-if="importError" color="red">{{ importError }}</Alert>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showImport = false">Cancel</Button>
        <Button :loading="importing" @click="submitImport">Start import</Button>
      </template>
    </Dialog>
  </div>
</template>
