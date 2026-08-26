<script setup lang="ts">
import { ACTIVE_STATUSES, type Job, type JobResult } from '~/stores/jobs'

const props = defineProps<{ job: Job | null }>()
const emit = defineEmits<{ close: [] }>()

const { statusColor } = useJobs()
const jobsStore = useJobsStore()

const isOpen = computed({
  get: () => !!props.job,
  set: (v: boolean) => { if (!v) emit('close') },
})

// The prop is a reference into the jobs store array; fetchJobs() replaces
// that array wholesale, leaving the prop pointing at a detached, frozen
// object. Mirroring into a local ref — refreshed by id, not by the prop
// object — is what lets the panel poll its own updates.
const liveJob = ref<Job | null>(null)
const results = ref<JobResult[]>([])
const resultsLoading = ref(false)

let poll: ReturnType<typeof setInterval> | undefined
function stopPoll() {
  clearInterval(poll)
  poll = undefined
}

async function refresh(id: string) {
  const [freshJob, freshResults] = await Promise.all([
    jobsStore.fetchJob(id),
    jobsStore.fetchJobResults(id),
  ])
  liveJob.value = freshJob
  results.value = freshResults
  if (!ACTIVE_STATUSES.includes(freshJob.status)) stopPoll()
}

watch(() => props.job, async (job) => {
  stopPoll()
  liveJob.value = job
  results.value = []
  if (!job) return

  resultsLoading.value = true
  try {
    results.value = await jobsStore.fetchJobResults(String(job.id))
  } finally {
    resultsLoading.value = false
  }

  if (ACTIVE_STATUSES.includes(job.status)) {
    poll = setInterval(() => refresh(String(job.id)), 5000)
  }
})

onUnmounted(stopPoll)

const resultSummary = computed(() =>
  results.value.reduce((acc, r) => {
    acc[r.status] = (acc[r.status] ?? 0) + 1
    return acc
  }, {} as Record<string, number>),
)

const doneCount = computed(() => results.value.filter((r) => !['PENDING', 'RUNNING'].includes(r.status)).length)
const totalCount = computed(() => liveJob.value?.target_servers?.agent_ids?.length || results.value.length)

// Only resolved where a JobResult row already exists (agent has reported
// back at least once) — a QUEUED job's targets that haven't run yet have
// no such row, so those still show as raw UUIDs.
const hostnameByAgent = computed(() => {
  const map: Record<string, string> = {}
  for (const r of results.value) {
    if (r.hostname) map[r.agent_id] = r.hostname
  }
  return map
})

function fmtDate(v: string | null | undefined): string {
  return v ? new Date(v).toLocaleString() : '—'
}

// duration_seconds exists on JobResult but is never written on the live
// path (see agent/backend wire — stdout/exit_code/completed_at only), so
// deriving it from started_at/completed_at (which *are* populated) is what
// actually produces a real number instead of a permanent "—".
function duration(startedAt?: string | null, completedAt?: string | null): string {
  if (!startedAt || !completedAt) return '—'
  const ms = new Date(completedAt).getTime() - new Date(startedAt).getTime()
  if (!Number.isFinite(ms) || ms < 0) return '—'
  const totalSec = Math.round(ms / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

// PACKAGE_UPDATE's parameters.package_names is the one thing that answers
// "what did this job actually do" for the most common job type, and wasn't
// rendered anywhere before this component existed.
const packageNames = computed<string[] | null>(() => {
  const names = (liveJob.value?.parameters as Record<string, unknown> | null)?.package_names
  return Array.isArray(names) ? names as string[] : null
})
</script>

<template>
  <Dialog v-model="isOpen" size="xl">
    <template #body>
      <div v-if="liveJob" class="space-y-4">
        <div class="flex items-center gap-3">
          <h2 class="text-lg font-bold flex-1">{{ liveJob.name }}</h2>
          <Badge :color="statusColor(String(liveJob.status))">{{ liveJob.status }}</Badge>
        </div>

        <dl class="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
          <div><dt class="text-muted-foreground">Type</dt><dd>{{ liveJob.job_type }}</dd></div>
          <div v-if="liveJob.description" class="col-span-2">
            <dt class="text-muted-foreground">Description</dt><dd>{{ liveJob.description }}</dd>
          </div>
          <div class="col-span-2">
            <dt class="text-muted-foreground">Targets</dt>
            <dd class="font-mono text-xs">
              {{ (liveJob.target_servers?.agent_ids || []).map((id) => hostnameByAgent[id] || id).join(', ') || '—' }}
            </dd>
          </div>
          <div v-if="liveJob.requires_approval">
            <dt class="text-muted-foreground">Approval</dt>
            <dd>{{ liveJob.approved_by ? `Approved ${fmtDate(liveJob.approved_at)}` : 'Pending' }}</dd>
          </div>
        </dl>

        <template v-if="ACTIVE_STATUSES.includes(liveJob.status)">
          <Separator />
          <div>
            <div class="flex items-center justify-between mb-1.5">
              <h3 class="text-sm font-medium">Progress</h3>
              <span class="text-xs text-muted-foreground font-mono">{{ doneCount }} / {{ totalCount }} servers</span>
            </div>
            <Progress :model-value="doneCount" :max="totalCount || 1" />
            <p v-if="liveJob.status === 'QUEUED' || liveJob.status === 'SCHEDULED'" class="text-xs text-muted-foreground mt-1.5">
              Waiting for the agent to pick this up — checks in about every 60s.
            </p>
          </div>
        </template>

        <Separator />

        <div>
          <h3 class="text-sm font-medium mb-2">Timeline</h3>
          <dl class="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
            <div><dt class="text-muted-foreground">Created</dt><dd>{{ fmtDate(liveJob.created_at) }}</dd></div>
            <div v-if="liveJob.scheduled_time"><dt class="text-muted-foreground">Scheduled</dt><dd>{{ fmtDate(liveJob.scheduled_time) }}</dd></div>
            <div><dt class="text-muted-foreground">Started</dt><dd>{{ fmtDate(liveJob.started_at) }}</dd></div>
            <div><dt class="text-muted-foreground">Completed</dt><dd>{{ fmtDate(liveJob.completed_at) }}</dd></div>
            <div><dt class="text-muted-foreground">Duration</dt><dd>{{ duration(liveJob.started_at, liveJob.completed_at) }}</dd></div>
          </dl>
        </div>

        <template v-if="packageNames">
          <Separator />
          <div>
            <h3 class="text-sm font-medium mb-2">{{ packageNames.length }} packages</h3>
            <div class="flex flex-wrap gap-1 max-h-32 overflow-y-auto">
              <Badge v-for="n in packageNames" :key="n" color="gray" size="xs">{{ n }}</Badge>
            </div>
          </div>
        </template>
        <template v-else-if="liveJob.parameters">
          <Separator />
          <div>
            <h3 class="text-sm font-medium mb-2">Parameters</h3>
            <pre class="text-xs bg-muted rounded p-2 overflow-auto max-h-40">{{ JSON.stringify(liveJob.parameters, null, 2) }}</pre>
          </div>
        </template>

        <Separator />

        <div>
          <div class="flex items-center justify-between mb-2 flex-wrap gap-2">
            <h3 class="text-sm font-medium">Results per server</h3>
            <div class="flex flex-wrap gap-2">
              <Badge v-for="(count, status) in resultSummary" :key="status" :color="statusColor(status)" size="xs">
                {{ count }} {{ status.toLowerCase() }}
              </Badge>
            </div>
          </div>
          <p v-if="resultsLoading" class="text-sm text-muted-foreground">Loading…</p>
          <p v-else-if="!results.length" class="text-sm text-muted-foreground">No results yet.</p>
          <div v-else class="space-y-1">
            <details v-for="r in results" :key="r.agent_id" class="rounded border border-border p-2 text-sm" open>
              <summary class="cursor-pointer flex items-center gap-2 flex-wrap">
                <Badge :color="statusColor(r.status)" size="xs">{{ r.status }}</Badge>
                <span class="font-mono flex-1">{{ r.hostname || r.agent_id }}</span>
                <span class="text-xs text-muted-foreground">exit {{ r.exit_code ?? '—' }}</span>
                <span class="text-xs text-muted-foreground">{{ duration(r.started_at, r.completed_at) }}</span>
              </summary>
              <div class="mt-2 space-y-2">
                <p v-if="r.error_message" class="text-xs text-destructive bg-destructive/10 rounded p-2">{{ r.error_message }}</p>
                <pre class="text-xs bg-muted rounded p-2 overflow-auto max-h-96">{{ r.stdout || '(empty)' }}</pre>
              </div>
            </details>
          </div>
        </div>
      </div>
    </template>
  </Dialog>
</template>
