<script setup lang="ts">
import { Play, Pencil } from 'lucide-vue-next'
import type { Job } from '~/stores/jobs'
import type { Policy, PolicyAuditRow } from '~/stores/policies'

const route = useRoute()
const api = useApi()
const store = usePoliciesStore()
const { canEdit } = useCurrentUser()
const { statusColor } = useJobs()
const toast = useToast()

const policy = ref<Policy | null>(null)
const loading = ref(true)

const tabs = [
  { label: 'Overview', slot: 'overview' },
  { label: 'Executions', slot: 'executions' },
  { label: 'Audit', slot: 'audit' },
]

const executions = ref<Job[]>([])
const executionsLoading = ref(false)
const executionsLoaded = ref(false)
async function loadExecutions() {
  if (executionsLoaded.value) return
  executionsLoading.value = true
  try {
    const data = await api.get<{ items: Job[] }>(`/jobs?policy_id=${route.params.id}&limit=50`)
    executions.value = data.items
    executionsLoaded.value = true
  } finally {
    executionsLoading.value = false
  }
}

const auditRows = ref<PolicyAuditRow[]>([])
const auditLoading = ref(false)
const auditLoaded = ref(false)
async function loadAudit() {
  if (auditLoaded.value) return
  auditLoading.value = true
  try {
    auditRows.value = await store.fetchAudit(String(route.params.id))
    auditLoaded.value = true
  } finally {
    auditLoading.value = false
  }
}

function onTabChange(index: number) {
  if (index === 1) loadExecutions()
  if (index === 2) loadAudit()
}

async function load() {
  loading.value = true
  try {
    policy.value = await store.fetchPolicy(String(route.params.id))
  } finally {
    loading.value = false
  }
}
onMounted(load)

const running = ref(false)
async function runNow() {
  if (!policy.value) return
  running.value = true
  try {
    const result = await store.runPolicy(policy.value.id)
    if (result.job_ids.length) {
      toast.add({ title: `Job creat pentru ${result.matched_agents} server(e)`, color: 'green' })
      executionsLoaded.value = false
      await loadExecutions()
    } else {
      toast.add({ title: result.matched_agents === 0 ? 'Nicio țintă potrivită' : 'Sărit — job identic deja activ', color: 'amber' })
    }
  } catch {
    toast.add({ title: 'Rularea politicii a eșuat', color: 'red' })
  } finally {
    running.value = false
  }
}

const showWizard = ref(false)
async function onWizardSaved() {
  showWizard.value = false
  await load()
}

const selectedJob = ref<Job | null>(null)

function targetSummary(t: Policy['target_servers']): string {
  if (!t) return '—'
  if (t.all) return 'Toate serverele'
  if (t.agent_ids?.length) return `${t.agent_ids.length} servere selectate`
  if (t.filters) return Object.entries(t.filters).map(([k, v]) => `${k}=${v}`).join(', ') || 'Filtru'
  return '—'
}
function fmtDate(v: string | null | undefined): string {
  return v ? new Date(v).toLocaleString() : '—'
}
</script>

<template>
  <div>
    <Skeleton v-if="loading" class="h-64 w-full rounded-xl" />
    <div v-else-if="!policy" class="text-sm text-muted-foreground">Politica nu a fost găsită.</div>

    <div v-else class="space-y-4">
      <div class="flex items-center gap-3">
        <h1 class="text-lg font-bold flex-1">{{ policy.name }}</h1>
        <Badge :color="policy.is_enabled ? 'green' : 'gray'">{{ policy.is_enabled ? 'Activă' : 'Inactivă' }}</Badge>
        <Button size="xs" variant="outline" :loading="running" @click="runNow">
          <Play class="size-3.5" />
          Run now
        </Button>
        <Button v-if="canEdit" size="xs" variant="outline" @click="showWizard = true">
          <Pencil class="size-3.5" />
          Editează
        </Button>
      </div>

      <AppTabs :items="tabs" @change="onTabChange">
        <template #overview>
          <div class="space-y-4">
            <dl class="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
              <div><dt class="text-muted-foreground">Categorie</dt><dd>{{ policy.policy_type || '—' }}</dd></div>
              <div><dt class="text-muted-foreground">Severitate</dt><dd>{{ policy.severity || '—' }}</dd></div>
              <div><dt class="text-muted-foreground">Prioritate</dt><dd>{{ policy.priority }}</dd></div>
              <div><dt class="text-muted-foreground">Declanșator</dt><dd>{{ policy.trigger_type === 'SCHEDULE' ? `cron: ${policy.cron_expr}` : 'Manual' }}</dd></div>
              <div><dt class="text-muted-foreground">Ținte</dt><dd>{{ targetSummary(policy.target_servers) }}</dd></div>
              <div><dt class="text-muted-foreground">Versiune</dt><dd>v{{ policy.version }}</dd></div>
              <div><dt class="text-muted-foreground">Ultima rulare</dt><dd>{{ fmtDate(policy.last_run_at) }}</dd></div>
              <div><dt class="text-muted-foreground">Următoarea rulare</dt><dd>{{ fmtDate(policy.next_run_at) }}</dd></div>
              <div v-if="policy.tags.length" class="col-span-2 sm:col-span-3">
                <dt class="text-muted-foreground mb-1">Etichete</dt>
                <dd class="flex flex-wrap gap-1"><Badge v-for="t in policy.tags" :key="t" color="gray" size="xs">{{ t }}</Badge></dd>
              </div>
            </dl>
            <p v-if="policy.description" class="text-sm text-muted-foreground">{{ policy.description }}</p>

            <Separator />

            <div>
              <h3 class="text-sm font-medium mb-2">Acțiune</h3>
              <pre class="text-xs bg-muted rounded p-2 overflow-auto max-h-40">{{ JSON.stringify(policy.actions, null, 2) }}</pre>
            </div>
          </div>
        </template>

        <template #executions>
          <div v-if="executionsLoading" class="text-sm text-muted-foreground">Se încarcă…</div>
          <div v-else-if="!executions.length" class="text-sm text-muted-foreground py-8 text-center">
            Nicio execuție încă — apasă „Run now" sau așteaptă următorul declanșator programat.
          </div>
          <div v-else class="space-y-1">
            <button
              v-for="job in executions"
              :key="job.id"
              type="button"
              class="w-full flex items-center gap-3 rounded-lg border border-border p-2.5 text-left text-sm hover:border-primary-active/40"
              @click="selectedJob = job"
            >
              <Badge :color="statusColor(String(job.status))" size="xs">{{ job.status }}</Badge>
              <span class="flex-1 truncate">{{ job.name }}</span>
              <span class="font-mono text-xs text-muted-foreground">{{ fmtDate(job.created_at) }}</span>
            </button>
          </div>
        </template>

        <template #audit>
          <div v-if="auditLoading" class="text-sm text-muted-foreground">Se încarcă…</div>
          <div v-else-if="!auditRows.length" class="text-sm text-muted-foreground py-8 text-center">Niciun istoric.</div>
          <div v-else class="space-y-1">
            <div v-for="row in auditRows" :key="row.id" class="rounded-lg border border-border p-2.5 text-sm">
              <div class="flex items-center gap-2">
                <Badge color="gray" size="xs">{{ row.change_type }}</Badge>
                <span class="font-mono text-xs text-muted-foreground flex-1">{{ fmtDate(row.changed_at) }}</span>
              </div>
              <p v-if="row.change_type === 'TRIGGERED'" class="text-xs text-muted-foreground mt-1">
                {{ row.new_value?.matched_agents }} agenți potriviți, {{ (row.new_value?.job_ids as unknown[])?.length ?? 0 }} job(uri)
              </p>
            </div>
          </div>
        </template>
      </AppTabs>
    </div>

    <PolicyWizard v-if="showWizard" :policy="policy" @close="showWizard = false" @saved="onWizardSaved" />
    <JobDetail :job="selectedJob" @close="selectedJob = null" />
  </div>
</template>
