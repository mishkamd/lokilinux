<script setup lang="ts">
import { Download, Plus, RefreshCw } from 'lucide-vue-next'
import type { ReportFormat, ReportStatus, ReportType } from '~/stores/compliance'

const store = useComplianceStore()
const api = useApi()
const toast = useToast()
const { canEdit } = useCurrentUser()
const { reports, reportsTotal, reportsLoading, reportsNextCursor } = storeToRefs(store)

onMounted(() => store.fetchReports())

const STATUS_COLORS: Record<ReportStatus, string> = {
  PENDING: 'gray', GENERATING: 'amber', COMPLETED: 'green', FAILED: 'red',
}
const REPORT_TYPES: ReportType[] = ['FLEET_SUMMARY', 'POLICY_SET', 'DATACENTER', 'CUSTOM']
const REPORT_FORMATS: ReportFormat[] = ['JSON', 'CSV', 'XLSX', 'PDF']

const columns = [
  { key: 'report_type', label: 'Type' },
  { key: 'format', label: 'Format' },
  { key: 'status', label: 'Status' },
  { key: 'created_at', label: 'Requested' },
  { key: 'download', label: '' },
]

const showCreate = ref(false)
const form = ref({ report_type: 'FLEET_SUMMARY' as ReportType, format: 'JSON' as ReportFormat })
const creating = ref(false)

async function submitCreate() {
  creating.value = true
  try {
    await store.createReport({ report_type: form.value.report_type, format: form.value.format })
    toast.add({ title: 'Report requested', description: 'Generating in the background — refresh to check status.' })
    showCreate.value = false
  } catch {
    toast.add({ title: 'Failed to request report', color: 'red' })
  } finally {
    creating.value = false
  }
}

const downloading = ref<string | null>(null)

async function downloadReport(id: string, format: ReportFormat) {
  downloading.value = id
  try {
    const blob = await api.get<Blob>(`/compliance/reports/${id}/download`, { responseType: 'blob' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `compliance-report-${id}.${format.toLowerCase()}`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } catch {
    toast.add({ title: 'Download failed', color: 'red' })
  } finally {
    downloading.value = null
  }
}
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <Button variant="outline" @click="store.fetchReports()">
        <RefreshCw class="size-4" /> Refresh
      </Button>
      <div class="flex items-center gap-3">
        <Badge color="gray">{{ reportsTotal }} reports</Badge>
        <Button v-if="canEdit" @click="showCreate = true">
          <Plus class="size-4" /> Generate report
        </Button>
      </div>
    </div>

    <DataTable :rows="reports" :columns="columns" :loading="reportsLoading">
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
        <span class="font-mono text-xs">{{ new Date(String(row.created_at)).toLocaleString() }}</span>
      </template>
      <template #download-data="{ row }">
        <Button v-if="row.status === 'COMPLETED'" size="xs" variant="outline"
                :loading="downloading === row.id" @click="downloadReport(String(row.id), row.format)">
          <Download class="size-3.5" /> Download
        </Button>
        <span v-else-if="row.status === 'FAILED'" class="text-xs text-destructive">{{ row.error_message || 'Failed' }}</span>
      </template>
    </DataTable>

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
          <FormField label="Format" required>
            <Select v-model="form.format" :options="REPORT_FORMATS" />
          </FormField>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showCreate = false">Cancel</Button>
        <Button :loading="creating" @click="submitCreate">Generate</Button>
      </template>
    </Dialog>
  </div>
</template>
