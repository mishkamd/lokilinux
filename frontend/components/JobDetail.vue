<script setup lang="ts">
import type { Job, JobResult } from '~/stores/jobs'

const props = defineProps<{ job: Job | null }>()
const emit = defineEmits<{ close: [] }>()

const { statusColor } = useJobs()

const isOpen = computed({
  get: () => !!props.job,
  set: (v: boolean) => { if (!v) emit('close') },
})

const results = ref<JobResult[]>([])
const resultsLoading = ref(false)

watch(() => props.job, async (job) => {
  results.value = []
  if (!job) return
  resultsLoading.value = true
  try {
    results.value = await useJobsStore().fetchJobResults(String(job.id))
  } finally {
    resultsLoading.value = false
  }
})

const resultSummary = computed(() =>
  results.value.reduce((acc, r) => {
    acc[r.status] = (acc[r.status] ?? 0) + 1
    return acc
  }, {} as Record<string, number>),
)

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
  const names = (props.job?.parameters as Record<string, unknown> | null)?.package_names
  return Array.isArray(names) ? names as string[] : null
})
</script>

<template>
  <Dialog v-model="isOpen" size="xl">
    <template #body>
      <div v-if="job" class="space-y-4">
        <div class="flex items-center gap-3">
          <h2 class="text-lg font-bold flex-1">{{ job.name }}</h2>
          <Badge :color="statusColor(String(job.status))">{{ job.status }}</Badge>
        </div>

        <dl class="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
          <div><dt class="text-muted-foreground">Tip</dt><dd>{{ job.job_type }}</dd></div>
          <div v-if="job.description" class="col-span-2">
            <dt class="text-muted-foreground">Descriere</dt><dd>{{ job.description }}</dd>
          </div>
          <div class="col-span-2">
            <dt class="text-muted-foreground">Ținte</dt>
            <dd class="font-mono text-xs">
              {{ (job.target_servers?.agent_ids || []).map((id) => hostnameByAgent[id] || id).join(', ') || '—' }}
            </dd>
          </div>
          <div v-if="job.requires_approval">
            <dt class="text-muted-foreground">Aprobare</dt>
            <dd>{{ job.approved_by ? `Aprobat ${fmtDate(job.approved_at)}` : 'În așteptare' }}</dd>
          </div>
        </dl>

        <Separator />

        <div>
          <h3 class="text-sm font-medium mb-2">Cronologie</h3>
          <dl class="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
            <div><dt class="text-muted-foreground">Creat</dt><dd>{{ fmtDate(job.created_at) }}</dd></div>
            <div v-if="job.scheduled_time"><dt class="text-muted-foreground">Programat</dt><dd>{{ fmtDate(job.scheduled_time) }}</dd></div>
            <div><dt class="text-muted-foreground">Pornit</dt><dd>{{ fmtDate(job.started_at) }}</dd></div>
            <div><dt class="text-muted-foreground">Finalizat</dt><dd>{{ fmtDate(job.completed_at) }}</dd></div>
            <div><dt class="text-muted-foreground">Durată</dt><dd>{{ duration(job.started_at, job.completed_at) }}</dd></div>
          </dl>
        </div>

        <template v-if="packageNames">
          <Separator />
          <div>
            <h3 class="text-sm font-medium mb-2">{{ packageNames.length }} pachete</h3>
            <div class="flex flex-wrap gap-1 max-h-32 overflow-y-auto">
              <Badge v-for="n in packageNames" :key="n" color="gray" size="xs">{{ n }}</Badge>
            </div>
          </div>
        </template>
        <template v-else-if="job.parameters">
          <Separator />
          <div>
            <h3 class="text-sm font-medium mb-2">Parametri</h3>
            <pre class="text-xs bg-muted rounded p-2 overflow-auto max-h-40">{{ JSON.stringify(job.parameters, null, 2) }}</pre>
          </div>
        </template>

        <Separator />

        <div>
          <div class="flex items-center justify-between mb-2 flex-wrap gap-2">
            <h3 class="text-sm font-medium">Rezultate per server</h3>
            <div class="flex flex-wrap gap-2">
              <Badge v-for="(count, status) in resultSummary" :key="status" :color="statusColor(status)" size="xs">
                {{ count }} {{ status.toLowerCase() }}
              </Badge>
            </div>
          </div>
          <p v-if="resultsLoading" class="text-sm text-muted-foreground">Se încarcă…</p>
          <p v-else-if="!results.length" class="text-sm text-muted-foreground">Niciun rezultat încă.</p>
          <div v-else class="space-y-1">
            <details v-for="r in results" :key="r.agent_id" class="rounded border border-border p-2 text-sm" open>
              <summary class="cursor-pointer flex items-center gap-2 flex-wrap">
                <Badge :color="statusColor(r.status)" size="xs">{{ r.status }}</Badge>
                <span class="font-mono flex-1">{{ r.hostname || r.agent_id }}</span>
                <span class="text-xs text-muted-foreground">exit {{ r.exit_code ?? '—' }}</span>
                <span class="text-xs text-muted-foreground">{{ duration(r.started_at, r.completed_at) }}</span>
              </summary>
              <div class="mt-2 space-y-2">
                <p v-if="r.error_message" class="text-xs text-red-500 bg-red-500/10 rounded p-2">{{ r.error_message }}</p>
                <pre class="text-xs bg-muted rounded p-2 overflow-auto max-h-96">{{ r.stdout || '(gol)' }}</pre>
              </div>
            </details>
          </div>
        </div>
      </div>
    </template>
  </Dialog>
</template>
