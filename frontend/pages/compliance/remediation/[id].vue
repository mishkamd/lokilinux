<script setup lang="ts">
import { RefreshCw } from 'lucide-vue-next'
import type { RemediationPlanStatus } from '~/stores/compliance'

const route = useRoute()
const store = useComplianceStore()
const { selectedRemediationPlan, remediationActions, remediationExecution } = storeToRefs(store)
const { canEdit, isAdmin } = useCurrentUser()
const toast = useToast()

const loading = ref(true)
const loadError = ref<string | null>(null)

async function load(id?: string) {
  const planId = id ?? String(route.params.id)
  loading.value = true
  loadError.value = null
  try {
    await Promise.all([
      store.fetchRemediationPlan(planId),
      store.fetchRemediationActions(planId),
      store.fetchRemediationExecution(planId),
    ])
  } catch (err) {
    loadError.value = (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to load plan'
  } finally {
    loading.value = false
  }
}

// Watch route param changes for client-side navigation
watch(() => String(route.params.id), (newId) => {
  if (newId) load(newId)
}, { immediate: true })

const STATUS_COLORS: Record<RemediationPlanStatus, string> = {
  DRAFT: 'gray', PENDING_APPROVAL: 'amber', APPROVED: 'amber',
  EXECUTING: 'amber', VERIFYING: 'amber', COMPLETED: 'green', FAILED: 'red', ROLLED_BACK: 'gray',
}

const busy = ref(false)
const dryRunning = ref(false)

async function dryRun() {
  dryRunning.value = true
  try {
    await store.dryRunRemediationPlan(String(route.params.id))
    await refreshExecution()
    toast.add({ title: 'Dry run dispatched', description: 'Check mode only — nothing was applied.' })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to dry-run', color: 'red' })
  } finally {
    dryRunning.value = false
  }
}

async function submit() {
  busy.value = true
  try {
    await store.submitRemediationPlan(String(route.params.id))
    await load()
    toast.add({ title: 'Plan submitted for approval' })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to submit', color: 'red' })
  } finally {
    busy.value = false
  }
}

async function approve() {
  busy.value = true
  try {
    await store.approveRemediationPlan(String(route.params.id))
    await load()
    toast.add({ title: 'Plan approved — dispatching' })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to approve', color: 'red' })
  } finally {
    busy.value = false
  }
}

const hasRollbackBody = computed(() => remediationActions.value.some(a => a.rollback_body))
const canRollback = computed(() =>
  isAdmin.value
  && selectedRemediationPlan.value
  && (selectedRemediationPlan.value.status === 'COMPLETED' || selectedRemediationPlan.value.status === 'FAILED')
  && hasRollbackBody.value
)

async function rollback() {
  if (!confirm('Roll back this remediation plan? This will dispatch a new Job that reverses the completed actions.')) return
  busy.value = true
  try {
    await store.rollbackRemediationPlan(String(route.params.id))
    await load()
    toast.add({ title: 'Rollback dispatched' })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to rollback', color: 'red' })
  } finally {
    busy.value = false
  }
}

async function refreshExecution() {
  await store.fetchRemediationExecution(String(route.params.id))
}

const actionColumns = [
  { key: 'sequence', label: '#' },
  { key: 'agent_id', label: 'Server' },
  { key: 'provider', label: 'Provider' },
  { key: 'rendered_body', label: 'Action' },
  { key: 'rollback_body', label: 'Rollback' },
]
</script>

<template>
  <div>
    <!-- Loading skeleton -->
    <div v-if="loading" class="space-y-4">
      <Skeleton class="h-8 w-64" />
      <Skeleton class="h-4 w-48" />
      <Skeleton class="h-64 w-full" />
    </div>

    <!-- Error state -->
    <div v-else-if="loadError">
      <Alert color="red" class="mb-4">{{ loadError }}</Alert>
      <Button variant="outline" @click="load()">Retry</Button>
    </div>

    <!-- Plan detail -->
    <div v-else-if="selectedRemediationPlan">
      <div class="flex items-center justify-between mb-4">
        <div>
          <h2 class="text-lg font-semibold">{{ selectedRemediationPlan.name }}</h2>
          <p class="text-sm text-muted-foreground">Trigger: {{ selectedRemediationPlan.trigger_type }}</p>
        </div>
        <div class="flex items-center gap-2">
          <Badge v-if="selectedRemediationPlan.is_emergency" color="red">Emergency</Badge>
          <Badge :color="STATUS_COLORS[selectedRemediationPlan.status]">{{ selectedRemediationPlan.status }}</Badge>
          <Button
            v-if="canEdit && ['DRAFT', 'PENDING_APPROVAL', 'APPROVED'].includes(selectedRemediationPlan.status)"
            size="sm" variant="outline" :loading="dryRunning" @click="dryRun"
          >
            Dry run
          </Button>
          <Button v-if="canEdit && selectedRemediationPlan.status === 'DRAFT'" size="sm" :loading="busy" @click="submit">
            Submit for approval
          </Button>
          <Button v-if="canEdit && selectedRemediationPlan.status === 'PENDING_APPROVAL'" size="sm" :loading="busy" @click="approve">
            Approve &amp; dispatch
          </Button>
          <Button v-if="canRollback" size="sm" color="amber" :loading="busy" @click="rollback">
            Rollback
          </Button>
        </div>
      </div>

      <!-- Execution status -->
      <div v-if="remediationExecution?.job_id" class="mb-6 rounded-lg border p-4">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold">Execution</h3>
          <Button size="sm" variant="ghost" @click="refreshExecution">
            <RefreshCw class="size-3" /> Refresh
          </Button>
        </div>
        <div class="flex flex-wrap items-center gap-3 mb-3 text-sm">
          <Badge :color="remediationExecution.job_status === 'COMPLETED' ? 'green' : remediationExecution.job_status === 'FAILED' ? 'red' : 'amber'">
            {{ remediationExecution.job_status }}
          </Badge>
          <span v-if="remediationExecution.operation" class="text-muted-foreground">
            Operation: <span class="font-mono">{{ remediationExecution.operation }}</span>
          </span>
          <span class="text-muted-foreground font-mono text-xs">
            Job: {{ remediationExecution.job_id.slice(0, 8) }}…
          </span>
        </div>

        <div v-if="remediationExecution.results.length > 0" class="space-y-2">
          <div v-for="r in remediationExecution.results" :key="r.agent_id" class="rounded border p-2 text-sm">
            <div class="flex items-center gap-2 mb-1">
              <Badge :color="r.status === 'COMPLETED' ? 'green' : r.status === 'FAILED' ? 'red' : 'gray'" size="xs">{{ r.status }}</Badge>
              <span class="font-mono text-xs">{{ r.hostname || r.agent_id.slice(0, 8) + '…' }}</span>
              <span v-if="r.exit_code !== null" class="text-muted-foreground text-xs">exit {{ r.exit_code }}</span>
              <span v-if="r.duration_seconds !== null" class="text-muted-foreground text-xs">{{ r.duration_seconds }}s</span>
            </div>
            <pre v-if="r.stdout" class="font-mono text-xs whitespace-pre-wrap text-green-700 dark:text-green-400 max-h-32 overflow-auto">{{ r.stdout }}</pre>
            <pre v-if="r.stderr" class="font-mono text-xs whitespace-pre-wrap text-red-700 dark:text-red-400 max-h-32 overflow-auto">{{ r.stderr }}</pre>
            <p v-if="r.error_message" class="text-xs text-red-600">{{ r.error_message }}</p>
          </div>
        </div>
      </div>

      <!-- Actions table -->
      <h3 class="text-sm font-semibold mb-2">Actions</h3>
      <DataTable :rows="remediationActions" :columns="actionColumns">
        <template #agent_id-data="{ row }">
          <span class="font-mono text-xs">{{ row.hostname || row.agent_id }}</span>
        </template>
        <template #provider-data="{ row }"><Badge color="gray" size="xs">{{ row.provider }}</Badge></template>
        <template #rendered_body-data="{ row }">
          <pre class="font-mono text-xs whitespace-pre-wrap max-w-xl">{{ row.rendered_body }}</pre>
        </template>
        <template #rollback_body-data="{ row }">
          <pre v-if="row.rollback_body" class="font-mono text-xs whitespace-pre-wrap max-w-xl text-muted-foreground">{{ row.rollback_body }}</pre>
          <span v-else class="text-muted-foreground text-sm">—</span>
        </template>
      </DataTable>
    </div>
  </div>
</template>
