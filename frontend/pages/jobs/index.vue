<script setup lang="ts">
import { RefreshCw, Plus, Eye, Trash2, Check } from 'lucide-vue-next'
import type { JobResult } from '~/stores/jobs'

const store = useJobsStore()
const serversStore = useServersStore()
const { jobs, total, loading, filters } = storeToRefs(store)
const { statusColor } = useJobs()
const toast = useToast()

const JOB_TYPES = ['', 'PACKAGE_UPDATE', 'SECURITY_PATCH', 'CVE_SCAN', 'CUSTOM_COMMAND', 'REMEDIATION']
const JOB_STATUSES = ['', 'QUEUED', 'SCHEDULED', 'PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'TIMEOUT', 'CANCELLED']

const columns = [
  { key: 'name', label: 'Name' },
  { key: 'job_type', label: 'Type' },
  { key: 'status', label: 'Status' },
  { key: 'created_at', label: 'Created' },
  { key: 'completed_at', label: 'Completed' },
  { key: 'actions', label: '' },
]

const showNewJob = ref(false)
const newJobForm = ref({ name: '', job_type: 'PACKAGE_UPDATE', agent_ids: [], priority: 50 })
const agentOptions = ref<Array<{ label: string; value: string }>>([])
const submitting = ref(false)

function validateJob(): string | null {
  if (!newJobForm.value.name.trim()) return 'Job name is required'
  if (!JOB_TYPES.slice(1).includes(newJobForm.value.job_type)) return 'Select a valid job type'
  return null
}

async function submitJob() {
  const err = validateJob()
  if (err) {
    toast.add({ title: 'Invalid job', description: err, color: 'red' })
    return
  }
  submitting.value = true
  try {
    const payload = {
      name: newJobForm.value.name,
      job_type: newJobForm.value.job_type,
      priority: newJobForm.value.priority,
      target_servers: {
        agent_ids: newJobForm.value.agent_ids,
      },
      parameters: null,
    }
    await store.createJob(payload)
    showNewJob.value = false
    newJobForm.value = { name: '', job_type: 'PACKAGE_UPDATE', agent_ids: [], priority: 50 }
    toast.add({ title: 'Job created', color: 'green' })
  } catch {
    toast.add({ title: 'Failed to create job', color: 'red' })
  } finally {
    submitting.value = false
  }
}

const selectedJob = ref<(typeof jobs.value)[0] | null>(null)
const showJobDetail = computed({
  get: () => !!selectedJob.value,
  set: (v) => { if (!v) selectedJob.value = null },
})

const jobResults = ref<JobResult[]>([])
const jobResultsLoading = ref(false)

watch(selectedJob, async (job) => {
  jobResults.value = []
  if (!job) return
  jobResultsLoading.value = true
  try {
    jobResults.value = await store.fetchJobResults(String(job.id))
  } finally {
    jobResultsLoading.value = false
  }
})

const resultSummary = computed(() =>
  jobResults.value.reduce((acc, r) => {
    acc[r.status] = (acc[r.status] ?? 0) + 1
    return acc
  }, {} as Record<string, number>),
)

const cancellingJob = ref<(typeof jobs.value)[0] | null>(null)
const cancelling = ref(false)
const approving = ref<string | null>(null)

async function approveJob(job: (typeof jobs.value)[0]) {
  approving.value = String(job.id)
  try {
    await store.approveJob(String(job.id))
    toast.add({ title: 'Job approved', color: 'green' })
  } catch {
    toast.add({ title: 'Failed to approve job', color: 'red' })
  } finally {
    approving.value = null
  }
}

async function confirmCancel() {
  if (!cancellingJob.value) return
  cancelling.value = true
  try {
    await store.cancelJob(String(cancellingJob.value.id))
    toast.add({ title: 'Job cancelled', color: 'green' })
    cancellingJob.value = null
  } catch {
    toast.add({ title: 'Failed to cancel job', color: 'red' })
  } finally {
    cancelling.value = false
  }
}

onMounted(async () => {
  agentOptions.value = await serversStore.fetchAgentsForSelect()
})
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div class="flex flex-wrap items-center gap-3">
        <Select
          v-model="filters.status"
          :options="JOB_STATUSES"
          placeholder="Status"
          class="w-40"
          @change="store.fetchJobs()"
        />
        <Select
          v-model="filters.job_type"
          :options="JOB_TYPES"
          placeholder="Type"
          class="w-44"
          @change="store.fetchJobs()"
        />
        <Input
          v-model="filters.agent_id"
          placeholder="Agent ID..."
          class="w-64"
          @keyup.enter="store.fetchJobs()"
        />
        <Button variant="outline" @click="store.fetchJobs()">
          <RefreshCw class="size-4" />
          Refresh
        </Button>
      </div>
      <div class="flex items-center gap-3">
        <Badge color="gray">{{ total }} jobs</Badge>
        <Button @click="showNewJob = true">
          <Plus class="size-4" />
          New Job
        </Button>
      </div>
    </div>

    <DataTable :rows="jobs" :columns="columns" :loading="loading">
      <template #status-data="{ row }">
        <Badge :color="statusColor(String(row.status))" size="xs">{{ row.status }}</Badge>
      </template>
      <template #created_at-data="{ row }">
        <span class="font-mono">{{ new Date(String(row.created_at)).toLocaleString() }}</span>
      </template>
      <template #completed_at-data="{ row }">
        <span class="font-mono">{{ row.completed_at ? new Date(String(row.completed_at)).toLocaleString() : '—' }}</span>
      </template>
      <template #actions-data="{ row }">
        <div class="flex items-center justify-end gap-1">
          <Button size="xs" variant="ghost" class="text-muted-foreground" @click="selectedJob = row as typeof jobs.value[0]">
            <Eye class="size-3.5" />
          </Button>
          <Button
            v-if="row.requires_approval && !row.approved_by"
            size="xs"
            variant="ghost"
            class="text-green-600"
            :loading="approving === String(row.id)"
            @click="approveJob(row as typeof jobs.value[0])"
          >
            <Check class="size-3.5" />
          </Button>
          <Button
            v-if="['QUEUED', 'SCHEDULED', 'PENDING'].includes(String(row.status))"
            size="xs"
            variant="ghost"
            class="text-muted-foreground"
            @click="cancellingJob = row as typeof jobs.value[0]"
          >
            <Trash2 class="size-3.5" />
          </Button>
        </div>
      </template>
    </DataTable>

    <!-- New Job Dialog -->
    <Dialog v-model="showNewJob" title="New Job">
      <template #body>
        <div class="space-y-4">
          <FormField label="Name" required>
            <Input v-model="newJobForm.name" placeholder="Job name..." />
          </FormField>
          <FormField label="Type" required>
            <Select v-model="newJobForm.job_type" :options="JOB_TYPES.slice(1)" />
          </FormField>
          <FormField label="Target Agents" required>
            <MultiSelect
              v-model="newJobForm.agent_ids"
              :options="agentOptions"
              placeholder="Select agents to target..."
            />
          </FormField>
          <FormField label="Priority (1–100)">
            <Input v-model.number="newJobForm.priority" type="number" :min="1" :max="100" />
          </FormField>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showNewJob = false">Cancel</Button>
        <Button :loading="submitting" @click="submitJob">Create</Button>
      </template>
    </Dialog>

    <!-- Job Detail Sheet -->
    <Sheet v-model="showJobDetail">
      <div v-if="selectedJob" class="p-6 space-y-4 pt-12">
        <div class="flex items-center gap-3">
          <h2 class="text-lg font-bold flex-1">{{ selectedJob.name }}</h2>
          <Badge :color="statusColor(String(selectedJob.status))">{{ selectedJob.status }}</Badge>
        </div>
        <dl class="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
          <div><dt class="text-muted-foreground">Type</dt><dd>{{ selectedJob.job_type }}</dd></div>
          <div><dt class="text-muted-foreground">Priority</dt><dd>{{ selectedJob.priority }}</dd></div>
          <div><dt class="text-muted-foreground">Agents</dt><dd class="font-mono text-xs">{{ selectedJob.target_servers?.agent_ids?.join(', ') || '—' }}</dd></div>
          <div><dt class="text-muted-foreground">Created</dt><dd>{{ new Date(String(selectedJob.created_at)).toLocaleString() }}</dd></div>
        </dl>
        <template v-if="jobResults.length">
          <Separator />
          <div class="flex flex-wrap gap-2">
            <Badge v-for="(count, status) in resultSummary" :key="status" :color="statusColor(status)" size="xs">
              {{ count }} {{ status.toLowerCase() }}
            </Badge>
          </div>
          <div class="space-y-1">
            <details v-for="r in jobResults" :key="r.agent_id" class="rounded border border-border p-2 text-sm">
              <summary class="cursor-pointer flex items-center gap-2">
                <Badge :color="statusColor(r.status)" size="xs">{{ r.status }}</Badge>
                <span class="font-mono flex-1">{{ r.hostname || r.agent_id }}</span>
                <span class="text-xs text-muted-foreground">exit {{ r.exit_code ?? '—' }}</span>
                <span class="text-xs text-muted-foreground">{{ r.duration_seconds != null ? r.duration_seconds + 's' : '—' }}</span>
              </summary>
              <pre class="text-xs bg-muted rounded p-2 mt-2 overflow-auto max-h-40">{{ r.stdout || '(empty)' }}</pre>
              <pre v-if="r.stderr" class="text-xs bg-muted rounded p-2 mt-1 overflow-auto max-h-40 text-red-500">{{ r.stderr }}</pre>
            </details>
          </div>
        </template>
        <p v-else-if="jobResultsLoading" class="text-sm text-muted-foreground">Loading results…</p>
      </div>
    </Sheet>

    <Dialog :model-value="!!cancellingJob" title="Cancel Job" @update:model-value="cancellingJob = null">
      <template #body>
        <p class="text-sm text-muted-foreground">
          Cancel <strong class="text-foreground">{{ cancellingJob?.name }}</strong>? This cannot be undone.
        </p>
      </template>
      <template #footer>
        <Button variant="ghost" @click="cancellingJob = null">Cancel</Button>
        <Button variant="destructive" :loading="cancelling" @click="confirmCancel">Cancel Job</Button>
      </template>
    </Dialog>
  </div>
</template>
