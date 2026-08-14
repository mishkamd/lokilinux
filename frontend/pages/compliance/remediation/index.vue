<script setup lang="ts">
import { Plus, RefreshCw } from 'lucide-vue-next'
import type { RemediationPlanStatus } from '~/stores/compliance'
import { useServersStore } from '~/stores/servers'

const store = useComplianceStore()
const serversStore = useServersStore()
const { remediationPlans, remediationTotal, remediationLoading, remediationNextCursor, remediationError, remediationFilters, maintenanceWindows } = storeToRefs(store)
const { canEdit } = useCurrentUser()
const toast = useToast()

onMounted(() => {
  store.fetchRemediationPlans()
  store.fetchMaintenanceWindows()
  serversStore.fetchServers()
})

const STATUS_COLORS: Record<RemediationPlanStatus, string> = {
  DRAFT: 'gray', PENDING_APPROVAL: 'amber', APPROVED: 'amber',
  EXECUTING: 'amber', COMPLETED: 'green', FAILED: 'red', ROLLED_BACK: 'gray',
}
const STATUSES: RemediationPlanStatus[] = ['DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'EXECUTING', 'COMPLETED', 'FAILED', 'ROLLED_BACK']

const columns = [
  { key: 'name', label: 'Plan' },
  { key: 'status', label: 'Status' },
  { key: 'trigger_type', label: 'Trigger' },
  { key: 'is_emergency', label: 'Emergency' },
  { key: 'created_at', label: 'Created' },
]

// ── Create plan dialog ──────────────────────────────────────────────────────

const showCreate = ref(false)
const createForm = ref({
  name: '',
  is_emergency: false,
  maintenance_window_id: undefined as string | undefined,
  actions: [] as Array<{
    agent_id: string
    provider: 'ansible' | 'shell' | 'python'
    rendered_body: string
    rollback_body: string
  }>,
})
const PROVIDERS: string[] = ['shell', 'ansible', 'python']
const creating = ref(false)
const createError = ref<string | null>(null)

function addAction() {
  createForm.value.actions.push({ agent_id: '', provider: 'shell', rendered_body: '', rollback_body: '' })
}
function removeAction(idx: number) {
  createForm.value.actions.splice(idx, 1)
}


const canSubmitCreate = computed(() => {
  const f = createForm.value
  return f.name.trim() !== ''
    && f.actions.length > 0
    && f.actions.every(a => a.agent_id && a.rendered_body.trim())
})

async function submitCreate() {
  createError.value = null
  if (!canSubmitCreate.value) {
    createError.value = 'Name and at least one complete action (server + body) are required.'
    return
  }
  creating.value = true
  try {
    const plan = await store.createRemediationPlan({
      name: createForm.value.name,
      is_emergency: createForm.value.is_emergency,
      maintenance_window_id: createForm.value.maintenance_window_id || undefined,
      actions: createForm.value.actions.map(a => ({
        agent_id: a.agent_id,
        provider: a.provider,
        rendered_body: a.rendered_body,
        rollback_body: a.rollback_body || null,
      })),
    })
    toast.add({ title: 'Remediation plan created', description: plan.name })
    showCreate.value = false
    createForm.value = { name: '', is_emergency: false, maintenance_window_id: undefined, actions: [] }
    navigateTo(`/compliance/remediation/${plan.id}`)
  } catch (err) {
    createError.value = (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to create plan'
  } finally {
    creating.value = false
  }
}

// ── Maintenance window dialog ───────────────────────────────────────────────

const showWindow = ref(false)
const windowForm = ref({
  name: '',
  scope_type: 'GLOBAL',
  scope_selector: '{}',
  cron_expr: '0 2 * * 0',
  duration_minutes: 120,
  timezone: 'UTC',
  is_enabled: true,
})
const windowCreating = ref(false)
const windowError = ref<string | null>(null)

const SCOPE_TYPES = ['GLOBAL', 'OS', 'ROLE', 'ENVIRONMENT', 'DATACENTER', 'CLUSTER', 'APPLICATION']

async function submitWindow() {
  windowError.value = null
  let selector: Record<string, unknown>
  try {
    selector = JSON.parse(windowForm.value.scope_selector || '{}')
  } catch {
    windowError.value = 'Scope selector must be valid JSON.'
    return
  }
  windowCreating.value = true
  try {
    await store.createMaintenanceWindow({
      name: windowForm.value.name,
      scope_type: windowForm.value.scope_type,
      scope_selector: selector,
      cron_expr: windowForm.value.cron_expr,
      duration_minutes: windowForm.value.duration_minutes,
      timezone: windowForm.value.timezone,
      is_enabled: windowForm.value.is_enabled,
    })
    toast.add({ title: 'Maintenance window created' })
    showWindow.value = false
    windowForm.value = { name: '', scope_type: 'GLOBAL', scope_selector: '{}', cron_expr: '0 2 * * 0', duration_minutes: 120, timezone: 'UTC', is_enabled: true }
  } catch (err) {
    windowError.value = (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to create window'
  } finally {
    windowCreating.value = false
  }
}
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div class="flex flex-wrap items-center gap-3">
        <Select v-model="remediationFilters.status" :options="['', ...STATUSES]" placeholder="Status" class="w-48"
                @change="store.fetchRemediationPlans()" />
        <Button variant="outline" @click="store.fetchRemediationPlans()">
          <RefreshCw class="size-4" /> Refresh
        </Button>
      </div>
      <div class="flex items-center gap-3">
        <Badge color="gray">{{ remediationTotal }} plans</Badge>
        <Button v-if="canEdit" variant="outline" @click="showWindow = true">
          Maintenance windows
        </Button>
        <Button v-if="canEdit" @click="showCreate = true">
          <Plus class="size-4" /> New plan
        </Button>
      </div>
    </div>

    <Alert v-if="remediationError" color="red" class="mb-4">{{ remediationError }}</Alert>

    <DataTable :rows="remediationPlans" :columns="columns" :loading="remediationLoading" rows-clickable
               @row-click="(row) => navigateTo(`/compliance/remediation/${row.id}`)">
      <template #status-data="{ row }">
        <Badge :color="STATUS_COLORS[row.status as RemediationPlanStatus] ?? 'gray'" size="xs">{{ row.status }}</Badge>
      </template>
      <template #is_emergency-data="{ row }">
        <Badge v-if="row.is_emergency" color="red" size="xs">Emergency</Badge>
        <span v-else class="text-muted-foreground text-sm">—</span>
      </template>
      <template #created_at-data="{ row }">
        <span class="font-mono text-xs">{{ new Date(String(row.created_at)).toLocaleDateString() }}</span>
      </template>
    </DataTable>

    <div v-if="remediationNextCursor" class="mt-4 flex justify-center">
      <Button variant="outline" @click="store.fetchRemediationPlans(remediationNextCursor!)">
        Load more
      </Button>
    </div>

    <!-- Create plan dialog -->
    <Dialog v-model="showCreate" title="New remediation plan">
      <template #body>
        <div class="space-y-4">
          <FormField label="Plan name" required>
            <Input v-model="createForm.name" placeholder="Fix SSH config on web servers" />
          </FormField>
          <div class="flex items-center gap-3">
            <label class="flex items-center gap-2 text-sm">
              <input v-model="createForm.is_emergency" type="checkbox" class="rounded" />
              Emergency (bypass maintenance window)
            </label>
          </div>
          <FormField v-if="maintenanceWindows.length > 0" label="Maintenance window">
            <Select v-model="createForm.maintenance_window_id"
                    :options="[{ value: '', label: 'None (immediate)' }, ...maintenanceWindows.map(w => ({ value: w.id, label: w.name }))]"
                    value-key="value" label-key="label" />
          </FormField>

          <div class="border-t pt-3">
            <div class="flex items-center justify-between mb-2">
              <span class="text-sm font-semibold">Actions</span>
              <Button size="sm" variant="outline" @click="addAction">
                <Plus class="size-3" /> Add action
              </Button>
            </div>
            <div v-for="(action, idx) in createForm.actions" :key="idx" class="mb-3 rounded-lg border p-3 space-y-2">
              <div class="flex items-center gap-2">
                <span class="text-xs font-mono text-muted-foreground">#{{ idx }}</span>
                <Select v-model="action.provider" :options="PROVIDERS" class="w-32" />
                <Button size="sm" variant="ghost" color="red" @click="removeAction(idx)">Remove</Button>
              </div>
              <FormField label="Server" required>
                <Select v-model="action.agent_id"
                        :options="[{ value: '', label: 'Select server...' }, ...serversStore.servers.map(s => ({ value: s.id, label: s.hostname || s.id }))]"
                        value-key="value" label-key="label" />
              </FormField>
              <FormField label="Script body" required>
                <textarea v-model="action.rendered_body" rows="4" placeholder="#!/bin/bash&#10;systemctl restart sshd"
                          class="flex w-full rounded-lg border border-input bg-card px-2.5 py-1.5 text-[13px] font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-primary" />
              </FormField>
              <FormField label="Rollback body (optional)">
                <textarea v-model="action.rollback_body" rows="2" placeholder="#!/bin/bash&#10;systemctl start sshd"
                          class="flex w-full rounded-lg border border-input bg-card px-2.5 py-1.5 text-[13px] font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-primary" />
              </FormField>
            </div>
            <p v-if="createForm.actions.length === 0" class="text-sm text-muted-foreground">No actions yet. Click "Add action" to define what this plan will execute.</p>
          </div>

          <Alert v-if="createError" color="red">{{ createError }}</Alert>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showCreate = false">Cancel</Button>
        <Button :loading="creating" :disabled="!canSubmitCreate" @click="submitCreate">Create plan</Button>
      </template>
    </Dialog>

    <!-- Maintenance window dialog -->
    <Dialog v-model="showWindow" title="New maintenance window">
      <template #body>
        <div class="space-y-4">
          <FormField label="Name" required>
            <Input v-model="windowForm.name" placeholder="Sunday 2AM maintenance" />
          </FormField>
          <div class="grid grid-cols-2 gap-3">
            <FormField label="Scope type">
              <Select v-model="windowForm.scope_type" :options="SCOPE_TYPES" />
            </FormField>
            <FormField label="Timezone">
              <Input v-model="windowForm.timezone" placeholder="UTC" />
            </FormField>
          </div>
          <FormField label="Scope selector (JSON)">
            <textarea v-model="windowForm.scope_selector" rows="2"
                      class="flex w-full rounded-lg border border-input bg-card px-2.5 py-1.5 text-[13px] font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-primary" />
          </FormField>
          <div class="grid grid-cols-2 gap-3">
            <FormField label="Cron expression">
              <Input v-model="windowForm.cron_expr" placeholder="0 2 * * 0" />
            </FormField>
            <FormField label="Duration (minutes)">
              <Input v-model.number="windowForm.duration_minutes" type="number" :min="1" :max="1440" />
            </FormField>
          </div>
          <label class="flex items-center gap-2 text-sm">
            <input v-model="windowForm.is_enabled" type="checkbox" class="rounded" />
            Enabled
          </label>
          <Alert v-if="windowError" color="red">{{ windowError }}</Alert>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showWindow = false">Cancel</Button>
        <Button :loading="windowCreating" :disabled="!windowForm.name" @click="submitWindow">Create window</Button>
      </template>
    </Dialog>
  </div>
</template>
