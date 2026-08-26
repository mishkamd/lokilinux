<script setup lang="ts">
import {
  ArrowRightLeft, Check, CheckCheck, CirclePlus,
  FileText, PlayCircle, RadioTower, RotateCcw, StickyNote,
} from 'lucide-vue-next'
import type { IncidentDetail, IncidentEvidenceItem } from '~/stores/incidents'

interface RunbookOption {
  id: string
  name: string
  incident_type: string
  trigger_mode: 'MANUAL' | 'AUTO'
  min_severity: string
  enabled: boolean
}

const route = useRoute()
const store = useIncidentsStore()
const api = useApi()
const { severityColor } = useSeverity()
const toast = useToast()

const incidentId = computed(() => String(route.params.id))

const incident = ref<IncidentDetail | null>(null)
const loading = ref(true)
const acting = ref(false)

const evidence = ref<IncidentEvidenceItem[] | null>(null)
const evidenceLoading = ref(false)

const runbooks = ref<RunbookOption[]>([])
const executingRunbook = ref<string | null>(null)

async function load() {
  loading.value = true
  try {
    incident.value = await store.fetchIncident(incidentId.value)
  } catch {
    toast.add({ title: 'Error', description: 'Failed to load incident', color: 'red' })
  } finally {
    loading.value = false
  }
}

async function loadRunbooks() {
  try {
    runbooks.value = await api.get<RunbookOption[]>('/runbooks')
  } catch {
    // non-critical — panel just stays empty
  }
}

onMounted(() => {
  load()
  loadRunbooks()
})

const matchingRunbooks = computed(() =>
  runbooks.value.filter((r) => r.enabled && r.incident_type === incident.value?.type),
)

const rootCauseSignal = computed(() =>
  incident.value?.signals.find((s) => s.id === incident.value?.root_cause_signal_id) ?? null,
)

const statusColor = (s: string) =>
  ({
    OPEN: 'red', ACKNOWLEDGED: 'amber', IN_PROGRESS: 'blue', RESOLVED: 'green', CLOSED: 'gray',
  } as Record<string, string>)[s] ?? 'gray'

const timelineIcon = (kind: string) =>
  ({
    created: CirclePlus, signal: RadioTower, transition: ArrowRightLeft,
    runbook: PlayCircle, note: StickyNote,
  } as Record<string, typeof CirclePlus>)[kind] ?? FileText

function fmtDate(v: string | null | undefined): string {
  return v ? new Date(v).toLocaleString() : '—'
}

async function ack() {
  if (!incident.value) return
  acting.value = true
  try {
    incident.value = { ...incident.value, ...(await store.ackIncident(incident.value.id)) }
  } catch {
    toast.add({ title: 'Error', description: 'Failed to acknowledge', color: 'red' })
  } finally {
    acting.value = false
  }
}

async function resolve() {
  if (!incident.value) return
  acting.value = true
  try {
    incident.value = { ...incident.value, ...(await store.resolveIncident(incident.value.id)) }
  } catch {
    toast.add({ title: 'Error', description: 'Failed to resolve', color: 'red' })
  } finally {
    acting.value = false
  }
}

async function reopen() {
  if (!incident.value) return
  acting.value = true
  try {
    incident.value = { ...incident.value, ...(await store.reopenIncident(incident.value.id)) }
  } catch {
    toast.add({ title: 'Error', description: 'Failed to reopen', color: 'red' })
  } finally {
    acting.value = false
  }
}

// Fetch once, on first expand — <details> owns its own open/closed state
// natively; a reactive :open binding fights the browser's own toggle (it
// forces the DOM attribute back to match the ref on every re-render,
// which can undo the user's click before the fetch even starts).
async function loadEvidenceOnce() {
  if (evidence.value !== null) return
  evidenceLoading.value = true
  try {
    evidence.value = await store.fetchEvidence(incidentId.value)
  } catch {
    evidence.value = []
  } finally {
    evidenceLoading.value = false
  }
}

async function executeRunbook(runbookId: string) {
  executingRunbook.value = runbookId
  try {
    await api.post(`/runbooks/${runbookId}/execute`, { incident_id: incidentId.value })
    toast.add({ title: 'Runbook started', color: 'green' })
    await load() // pick up the new "runbook" timeline entry
  } catch {
    toast.add({ title: 'Error', description: 'Failed to execute runbook', color: 'red' })
  } finally {
    executingRunbook.value = null
  }
}
</script>

<template>
  <div>
    <p v-if="loading" class="text-sm text-muted-foreground">Loading…</p>
    <p v-else-if="!incident" class="text-sm text-muted-foreground">Incident not found.</p>

    <div v-else class="space-y-5">
      <PageHeader
        :title="incident.title"
        :description="`${incident.type} · started ${fmtDate(incident.started_at)}`"
        :back="{ to: '/incidents', label: 'Back to incidents' }"
      >
        <template #badges>
          <Badge :color="severityColor(incident.severity)">{{ incident.severity }}</Badge>
          <Badge :color="statusColor(incident.status)">{{ incident.status }}</Badge>
          <Badge v-if="incident.confidence !== null" color="gray">
            {{ Math.round(incident.confidence * 100) }}% confidence
          </Badge>
        </template>
        <template #actions>
          <Button v-if="incident.status === 'OPEN'" variant="outline" size="sm" :loading="acting" @click="ack">
            <Check class="size-3.5" />
            Acknowledge
          </Button>
          <Button v-if="!['RESOLVED', 'CLOSED'].includes(incident.status)" variant="outline" size="sm" :loading="acting" @click="resolve">
            <CheckCheck class="size-3.5" />
            Resolve
          </Button>
          <Button v-if="incident.status === 'RESOLVED'" variant="outline" size="sm" :loading="acting" @click="reopen">
            <RotateCcw class="size-3.5" />
            Reopen
          </Button>
        </template>
      </PageHeader>

      <Separator />

      <div v-if="rootCauseSignal" class="rounded-lg border border-border p-3">
        <h3 class="text-sm font-medium mb-1.5">Root cause</h3>
        <div class="flex items-center gap-2 flex-wrap text-sm">
          <Badge :color="severityColor(rootCauseSignal.severity)" size="xs">{{ rootCauseSignal.severity }}</Badge>
          <span class="font-mono">{{ rootCauseSignal.type }}</span>
          <span v-if="rootCauseSignal.host_id" class="text-xs text-muted-foreground">host {{ rootCauseSignal.host_id }}</span>
          <span class="font-mono text-xs text-muted-foreground">{{ rootCauseSignal.occurrence_count }} occurrences</span>
        </div>
      </div>

      <div>
        <h3 class="text-sm font-medium mb-2">Affected signals ({{ incident.signals.length }})</h3>
        <div class="flex flex-wrap gap-2">
          <div
            v-for="s in incident.signals"
            :key="s.id"
            class="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-xs"
          >
            <Badge :color="severityColor(s.severity)" size="xs">{{ s.severity }}</Badge>
            <span class="font-mono">{{ s.type }}</span>
            <span class="font-mono text-muted-foreground">×{{ s.occurrence_count }}</span>
          </div>
          <p v-if="!incident.signals.length" class="text-sm text-muted-foreground">No linked signals.</p>
        </div>
      </div>

      <Separator />

      <div>
        <h3 class="text-sm font-medium mb-2">Timeline</h3>
        <ol class="space-y-3">
          <li v-for="entry in incident.timeline" :key="entry.id" class="flex items-start gap-2.5">
            <component :is="timelineIcon(entry.kind)" class="size-4 text-muted-foreground shrink-0 mt-0.5" />
            <div class="text-sm">
              <p>{{ entry.message }}</p>
              <p class="text-xs text-muted-foreground font-mono">{{ fmtDate(entry.ts) }}</p>
            </div>
          </li>
          <p v-if="!incident.timeline.length" class="text-sm text-muted-foreground">No timeline entries.</p>
        </ol>
      </div>

      <Separator />

      <details>
        <summary class="cursor-pointer text-sm font-medium" @click="loadEvidenceOnce">Evidence</summary>
        <div class="mt-2">
          <p v-if="evidenceLoading" class="text-sm text-muted-foreground">Loading…</p>
          <p v-else-if="evidence && !evidence.length" class="text-sm text-muted-foreground">No evidence recorded.</p>
          <ul v-else-if="evidence" class="space-y-1.5">
            <li v-for="(e, i) in evidence" :key="i" class="text-xs font-mono bg-muted rounded p-2">
              <span class="text-muted-foreground">[{{ e.kind }}]</span> {{ e.summary }}
            </li>
          </ul>
        </div>
      </details>

      <Separator />

      <div v-if="matchingRunbooks.length">
        <h3 class="text-sm font-medium mb-2">Runbooks</h3>
        <div class="space-y-2">
          <div
            v-for="rb in matchingRunbooks"
            :key="rb.id"
            class="flex items-center justify-between gap-2 rounded-lg border border-border p-2.5"
          >
            <div class="text-sm">
              <p class="font-medium">{{ rb.name }}</p>
              <p class="text-xs text-muted-foreground">{{ rb.trigger_mode }} · min {{ rb.min_severity }}</p>
            </div>
            <Button
              v-if="rb.trigger_mode === 'MANUAL'"
              size="xs"
              variant="outline"
              :loading="executingRunbook === rb.id"
              @click="executeRunbook(rb.id)"
            >
              <PlayCircle class="size-3.5" />
              Execute
            </Button>
            <Badge v-else color="blue" size="xs">Auto</Badge>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
