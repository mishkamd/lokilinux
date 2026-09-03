<script setup lang="ts">
import { Database, Download, Plus, RefreshCw } from 'lucide-vue-next'
import type { ReportFormat, ReportStatus, ReportType } from '~/stores/compliance'

const store = useComplianceStore()
const { format: fmtDateTime } = useDateTime()
const api = useApi()
const toast = useToast()
const { canEdit } = useCurrentUser()
const { reports, reportsTotal, reportsLoading, reportsNextCursor } = storeToRefs(store)

onMounted(() => {
  store.fetchReports()
  fetchPolicySetPicks()
  fetchFormatAvailability()
})

// Plan R10 — XLSX/PDF are gated by settings key reports.xlsx_pdf_enabled;
// JSON/CSV always report true. Fetched once, not stored globally: this
// page is the only consumer.
const formatAvailability = ref<Record<string, boolean>>({ JSON: true, CSV: true, XLSX: true, PDF: true })
async function fetchFormatAvailability() {
  formatAvailability.value = await api.get<Record<string, boolean>>('/compliance/reports/formats')
}

// local fetch, not store.fetchPolicySets() — this is a one-off picker for
// the create dialog, no reason to couple it to the Policy Sets page's own state.
const policySetPicks = ref<{ id: string; name: string }[]>([])
async function fetchPolicySetPicks() {
  const data = await api.get<{ items: { id: string; name: string }[] }>('/compliance/policy-sets?limit=100')
  policySetPicks.value = data.items
}
const policySetOptions = computed(() => [
  { value: '', label: 'Select policy set…' },
  ...policySetPicks.value.map((p) => ({ value: p.id, label: p.name })),
])

const STATUS_COLORS: Record<ReportStatus, string> = {
  PENDING: 'gray', GENERATING: 'amber', COMPLETED: 'green', FAILED: 'red',
}
const REPORT_TYPES: ReportType[] = [
  'FLEET_SUMMARY', 'POLICY_SET', 'DATACENTER', 'CUSTOM', 'FRAMEWORK', 'EXCEPTION', 'EXECUTIVE_SUMMARY',
]
const ALL_REPORT_FORMATS: ReportFormat[] = ['JSON', 'CSV', 'XLSX', 'PDF']

const columns = [
  { key: 'report_type', label: 'Type' },
  { key: 'format', label: 'Format' },
  { key: 'status', label: 'Status' },
  { key: 'created_at', label: 'Requested' },
  { key: 'download', label: '' },
]

const showCreate = ref(false)
const form = ref({ report_type: 'FLEET_SUMMARY' as ReportType, format: 'JSON' as ReportFormat, framework: '', policy_set_id: '' })
const creating = ref(false)
const createError = ref<string | null>(null)

async function submitCreate() {
  createError.value = null
  if (form.value.report_type === 'FRAMEWORK' && !form.value.framework) {
    createError.value = 'Framework key is required (e.g. cis, nist, stig).'
    return
  }
  if (form.value.report_type === 'POLICY_SET' && !form.value.policy_set_id) {
    createError.value = 'Policy set is required.'
    return
  }
  creating.value = true
  try {
    const params = form.value.report_type === 'FRAMEWORK' ? { framework: form.value.framework }
      : form.value.report_type === 'POLICY_SET' ? { policy_set_id: form.value.policy_set_id }
      : {}
    await store.createReport({ report_type: form.value.report_type, format: form.value.format, params })
    toast.add({ title: 'Report requested', description: 'Generating in the background — refresh to check status.' })
    showCreate.value = false
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to request report', color: 'red' })
  } finally {
    creating.value = false
  }
}

const availableReportFormats = computed(() => ALL_REPORT_FORMATS.filter((f) => formatAvailability.value[f]))

const downloading = ref<string | null>(null)
const storageMetaObjectId = ref<string | null>(null)

async function downloadReport(id: string, format: ReportFormat) {
  downloading.value = id
  try {
    const blob = await api.get<Blob>(`/compliance/reports/${id}/download`, { responseType: 'blob' })
    downloadBlob(blob, `compliance-report-${id}.${format.toLowerCase()}`)
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Download failed', color: 'red' })
  } finally {
    downloading.value = null
  }
}
</script>

<template>
  <div>
    <PageHeader>
      <Button variant="outline" @click="store.fetchReports()">
        <RefreshCw class="size-4" /> Refresh
      </Button>
      <div class="flex items-center gap-3">
        <Badge color="gray">{{ reportsTotal }} reports</Badge>
        <Button v-if="canEdit" @click="showCreate = true">
          <Plus class="size-4" /> Generate report
        </Button>
      </div>
    </PageHeader>

    <DataTable
      :rows="reports"
      :columns="columns"
      :loading="reportsLoading"
      sortable
      :page-size="25"
      empty-title="No reports generated yet"
    >
      <template #report_type-data="{ row }">
        <Badge color="gray" size="xs">{{ row.report_type }}</Badge>
      </template>
      <template #format-data="{ row }">
        <span class="font-mono text-xs">{{ row.format }}</span>
      </template>
      <template #status-data="{ row }">
        <Badge :color="STATUS_COLORS[row.status as ReportStatus] ?? 'gray'" size="xs">{{ row.status }}</Badge>
      </template>
      <template #created_at-data="{ row }">
        <span class="font-mono text-xs">{{ fmtDateTime(String(row.created_at)) }}</span>
      </template>
      <template #download-data="{ row }">
        <div v-if="row.status === 'COMPLETED'" class="flex items-center gap-1">
          <Button size="xs" variant="outline"
                  :loading="downloading === row.id" @click="downloadReport(String(row.id), row.format)">
            <Download class="size-3.5" /> Download
          </Button>
          <Tooltip v-if="row.storage_object_id" text="Storage info">
            <Button size="xs" variant="ghost" aria-label="Storage info" @click="storageMetaObjectId = String(row.storage_object_id)">
              <Database class="size-3.5" />
            </Button>
          </Tooltip>
        </div>
        <span v-else-if="row.status === 'FAILED'" class="text-xs text-destructive">{{ row.error_message || 'Failed' }}</span>
      </template>
    </DataTable>

    <Dialog :model-value="!!storageMetaObjectId" title="Storage info" size="sm" @update:model-value="storageMetaObjectId = null">
      <template #body>
        <StorageObjectMeta v-if="storageMetaObjectId" :object-id="storageMetaObjectId" />
      </template>
    </Dialog>

    <div v-if="reportsNextCursor" class="mt-4 flex justify-center">
      <Button variant="outline" @click="store.fetchReports(reportsNextCursor!)">
        Load more
      </Button>
    </div>

    <Dialog v-model="showCreate" title="Generate report">
      <template #body>
        <div class="space-y-4">
          <FormField label="Report type" required>
            <Select v-model="form.report_type" :options="REPORT_TYPES" />
          </FormField>
          <FormField v-if="form.report_type === 'FRAMEWORK'" label="Framework" required help="e.g. cis, nist, stig">
            <Input v-model="form.framework" placeholder="cis" />
          </FormField>
          <FormField v-if="form.report_type === 'POLICY_SET'" label="Policy set" required>
            <Select v-model="form.policy_set_id" :options="policySetOptions" />
          </FormField>
          <FormField label="Format" required
                     :help="availableReportFormats.length < ALL_REPORT_FORMATS.length ? 'XLSX/PDF disabled by an administrator (Settings → Reporting)' : undefined">
            <Select v-model="form.format" :options="availableReportFormats" />
          </FormField>
          <Alert v-if="createError" color="red">{{ createError }}</Alert>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showCreate = false">Cancel</Button>
        <Button :loading="creating" @click="submitCreate">Generate</Button>
      </template>
    </Dialog>
  </div>
</template>
