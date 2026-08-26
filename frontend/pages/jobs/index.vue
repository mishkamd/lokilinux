<script setup lang="ts">
import { RefreshCw, Plus, Eye, Trash2, Check } from 'lucide-vue-next'
import { ACTIVE_STATUSES, type Job } from '~/stores/jobs'

const store = useJobsStore()
const serversStore = useServersStore()
const { jobs, total, loading, filters } = storeToRefs(store)
const { statusColor } = useJobs()
const toast = useToast()

const JOB_TYPES = ['', 'PACKAGE_UPDATE', 'SECURITY_PATCH', 'CVE_SCAN', 'CUSTOM_COMMAND', 'REMEDIATION']
const JOB_STATUSES = ['', 'QUEUED', 'SCHEDULED', 'PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'TIMEOUT', 'CANCELLED']

const { format: fmtDateTime } = useDateTime()

const columns = [
  { key: 'name', label: 'Name' },
  { key: 'job_type', label: 'Type' },
  { key: 'status', label: 'Status' },
  { key: 'created_at', label: 'Created' },
  { key: 'completed_at', label: 'Completed' },
  { key: 'actions', label: '', noSort: true },
]

const showNewJob = ref(false)
const newJobForm = ref({ name: '', job_type: 'PACKAGE_UPDATE', agent_ids: [] as string[] })
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
      target_servers: {
        agent_ids: newJobForm.value.agent_ids,
      },
      parameters: null,
    }
    await store.createJob(payload)
    showNewJob.value = false
    newJobForm.value = { name: '', job_type: 'PACKAGE_UPDATE', agent_ids: [] }
    toast.add({ title: 'Job created', color: 'green' })
  } catch {
    toast.add({ title: 'Failed to create job', color: 'red' })
  } finally {
    submitting.value = false
  }
}

const selectedJob = ref<(typeof jobs.value)[0] | null>(null)

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
  store.fetchJobs()
  agentOptions.value = await serversStore.fetchAgentsForSelect()
})

// Mirrors pages/plugins/index.vue's install-status poll — statuses don't
// move on their own client-side, so the list has to ask again.
const hasActive = computed(() => jobs.value.some((j) => ACTIVE_STATUSES.includes(j.status)))
let poll: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  poll = setInterval(() => { if (hasActive.value) store.fetchJobs() }, 5000)
})
onUnmounted(() => clearInterval(poll))
</script>

<template>
  <div>
    <PageHeader>
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
    </PageHeader>

    <DataTable
      :rows="jobs"
      :columns="columns"
      :loading="loading"
      sortable
      :page-size="25"
      empty-title="No jobs"
      empty-description="Create a job to run remediation on your servers."
    >
      <template #status-data="{ row }">
        <Badge :color="statusColor(String(row.status))" size="xs">{{ row.status }}</Badge>
      </template>
      <template #created_at-data="{ row }">
        <span class="font-mono">{{ fmtDateTime(String(row.created_at)) }}</span>
      </template>
      <template #completed_at-data="{ row }">
        <span class="font-mono">{{ row.completed_at ? fmtDateTime(String(row.completed_at)) : '—' }}</span>
      </template>
      <template #actions-data="{ row }">
        <div class="flex items-center justify-end gap-1">
          <Tooltip text="View job">
            <Button size="xs" variant="ghost" aria-label="View job" @click="selectedJob = row as Job">
              <Eye class="size-3.5" />
            </Button>
          </Tooltip>
          <Tooltip v-if="row.requires_approval && !row.approved_by" text="Approve job">
            <Button
              size="xs"
              variant="ghost"
              class="text-success"
              aria-label="Approve job"
              :loading="approving === String(row.id)"
              @click="approveJob(row as Job)"
            >
              <Check class="size-3.5" />
            </Button>
          </Tooltip>
          <Tooltip v-if="['QUEUED', 'SCHEDULED', 'PENDING'].includes(String(row.status))" text="Cancel job">
            <Button
              size="xs"
              variant="ghost"
              aria-label="Cancel job"
              @click="cancellingJob = row as Job"
            >
              <Trash2 class="size-3.5" />
            </Button>
          </Tooltip>
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
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showNewJob = false">Cancel</Button>
        <Button :loading="submitting" @click="submitJob">Create</Button>
      </template>
    </Dialog>

    <JobDetail :job="selectedJob" @close="selectedJob = null" />

    <ConfirmDeleteDialog
      :model-value="!!cancellingJob"
      :entity-name="cancellingJob?.name"
      :loading="cancelling"
      title="Cancel Job"
      confirm-label="Cancel Job"
      @update:model-value="cancellingJob = null"
      @confirm="confirmCancel"
    >
      <template #description>
        <p class="text-sm text-muted-foreground">
          Cancel <strong class="text-foreground">{{ cancellingJob?.name }}</strong>? This cannot be undone.
        </p>
      </template>
    </ConfirmDeleteDialog>
  </div>
</template>
