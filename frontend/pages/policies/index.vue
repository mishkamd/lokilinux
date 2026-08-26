<script setup lang="ts">
import { RefreshCw, Play, Plus, Pencil, Trash2 } from 'lucide-vue-next'
import type { Policy } from '~/stores/policies'

const store = usePoliciesStore()
const { policies, total, loading, filters } = storeToRefs(store)
const { canEdit } = useCurrentUser()
const toast = useToast()

const POLICY_TYPES = ['', 'UPDATE', 'SECURITY', 'COMPLIANCE', 'MAINTENANCE', 'PLUGIN']
const POLICY_TYPE_COLORS: Record<string, string> = {
  UPDATE: 'gray', SECURITY: 'red', COMPLIANCE: 'gray', MAINTENANCE: 'gray', PLUGIN: 'gray',
}

const columns = [
  { key: 'is_enabled', label: 'Active' },
  { key: 'name', label: 'Name' },
  { key: 'policy_type', label: 'Category' },
  { key: 'trigger_type', label: 'Trigger' },
  { key: 'target_servers', label: 'Targets' },
  { key: 'last_run_at', label: 'Last run' },
  { key: 'next_run_at', label: 'Next run' },
  { key: 'priority', label: 'Priority' },
  { key: 'actions', label: '' },
]

function targetSummary(t: Policy['target_servers']): string {
  if (!t) return '—'
  if (t.all) return 'All servers'
  if (t.agent_ids?.length) return `${t.agent_ids.length} servers`
  if (t.filters) return Object.entries(t.filters).map(([k, v]) => `${k}=${v}`).join(', ') || 'Filter'
  return '—'
}

function fmtDate(v: string | null): string {
  return v ? new Date(v).toLocaleString() : '—'
}

async function toggleEnabled(policy: Policy) {
  try {
    await store.toggleEnabled(policy)
  } catch {
    toast.add({ title: 'Could not change policy state', color: 'red' })
  }
}

const runningId = ref<string | null>(null)
async function runNow(policy: Policy) {
  runningId.value = policy.id
  try {
    const result = await store.runPolicy(policy.id)
    if (result.job_ids.length) {
      toast.add({ title: `Job created for ${result.matched_agents} server(s)`, color: 'green' })
    } else if (result.matched_agents === 0) {
      toast.add({ title: 'No matching targets', color: 'amber' })
    } else {
      toast.add({ title: 'Skipped — identical job already active', color: 'amber' })
    }
  } catch {
    toast.add({ title: 'Policy run failed', color: 'red' })
  } finally {
    runningId.value = null
  }
}

const showWizard = ref(false)
const editingPolicy = ref<Policy | null>(null)

function openCreate() {
  editingPolicy.value = null
  showWizard.value = true
}
function openEdit(policy: Policy) {
  editingPolicy.value = policy
  showWizard.value = true
}
async function onWizardSaved() {
  showWizard.value = false
  await store.fetchPolicies()
}

const deletingPolicy = ref<Policy | null>(null)
const deleting = ref(false)
async function confirmDelete() {
  if (!deletingPolicy.value) return
  deleting.value = true
  try {
    await store.deletePolicy(deletingPolicy.value.id)
    toast.add({ title: 'Policy deleted', color: 'green' })
    deletingPolicy.value = null
  } catch {
    toast.add({ title: 'Delete failed', color: 'red' })
  } finally {
    deleting.value = false
  }
}

onMounted(() => store.fetchPolicies())
</script>

<template>
  <div>
    <PageHeader>
      <div class="flex flex-wrap items-center gap-3">
        <Select v-model="filters.policy_type" :options="POLICY_TYPES" placeholder="Category" class="w-44" @change="store.fetchPolicies()" />
        <Button variant="outline" @click="store.fetchPolicies()">
          <RefreshCw class="size-4" />
          Refresh
        </Button>
      </div>
      <div class="flex items-center gap-3">
        <Badge color="gray">{{ total }} policies</Badge>
        <Button v-if="canEdit" @click="openCreate">
          <Plus class="size-4" />
          New policy
        </Button>
      </div>
    </PageHeader>

    <DataTable
      :rows="policies"
      :columns="columns"
      :loading="loading"
      sortable
      :page-size="25"
      empty-title="No policies"
      empty-description="Create a policy to automate compliance checks."
    >
      <template #is_enabled-data="{ row }">
        <Switch :model-value="Boolean(row.is_enabled)" :disabled="!canEdit" @update:model-value="toggleEnabled(row as unknown as Policy)" />
      </template>

      <template #policy_type-data="{ row }">
        <Badge v-if="row.policy_type" :color="POLICY_TYPE_COLORS[String(row.policy_type)] ?? 'gray'" size="xs">{{ row.policy_type }}</Badge>
        <span v-else class="text-muted-foreground text-xs">—</span>
      </template>

      <template #trigger_type-data="{ row }">
        <Badge v-if="row.trigger_type === 'SCHEDULE'" color="gray" size="xs" class="font-mono">{{ (row as unknown as Policy).cron_expr }}</Badge>
        <span v-else class="text-muted-foreground text-xs">Manual</span>
      </template>

      <template #target_servers-data="{ row }">
        <span class="text-xs">{{ targetSummary((row as unknown as Policy).target_servers) }}</span>
      </template>

      <template #last_run_at-data="{ row }">
        <span class="font-mono text-xs text-muted-foreground">{{ fmtDate((row as unknown as Policy).last_run_at) }}</span>
      </template>
      <template #next_run_at-data="{ row }">
        <span class="font-mono text-xs text-muted-foreground">{{ fmtDate((row as unknown as Policy).next_run_at) }}</span>
      </template>

      <template #priority-data="{ row }">
        <span class="tabular-nums">{{ row.priority }}</span>
      </template>

      <template #actions-data="{ row }">
        <div class="flex items-center justify-end gap-1">
          <Tooltip text="Run now">
            <Button size="xs" variant="ghost" aria-label="Run now" :loading="runningId === row.id" @click="runNow(row as unknown as Policy)">
              <Play class="size-3.5" />
            </Button>
          </Tooltip>
          <NuxtLink :to="`/policies/${row.id}`">
            <Button size="xs" variant="ghost">Details</Button>
          </NuxtLink>
          <Tooltip v-if="canEdit" text="Edit policy">
            <Button v-if="canEdit" size="xs" variant="ghost" aria-label="Edit policy" @click="openEdit(row as unknown as Policy)">
              <Pencil class="size-3.5" />
            </Button>
          </Tooltip>
          <Tooltip v-if="canEdit" text="Delete policy">
            <Button v-if="canEdit" size="xs" variant="ghost" aria-label="Delete policy" @click="deletingPolicy = row as unknown as Policy">
              <Trash2 class="size-3.5" />
            </Button>
          </Tooltip>
        </div>
      </template>
    </DataTable>

    <PolicyWizard v-if="showWizard" :policy="editingPolicy" @close="showWizard = false" @saved="onWizardSaved" />

    <ConfirmDeleteDialog
      :model-value="!!deletingPolicy"
      :entity-name="deletingPolicy?.name"
      :loading="deleting"
      title="Delete policy"
      @update:model-value="deletingPolicy = null"
      @confirm="confirmDelete"
    />
  </div>
</template>
