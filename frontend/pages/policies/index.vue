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
  { key: 'is_enabled', label: 'Activă' },
  { key: 'name', label: 'Nume' },
  { key: 'policy_type', label: 'Categorie' },
  { key: 'trigger_type', label: 'Declanșator' },
  { key: 'target_servers', label: 'Ținte' },
  { key: 'last_run_at', label: 'Ultima rulare' },
  { key: 'next_run_at', label: 'Următoarea' },
  { key: 'priority', label: 'Prioritate' },
  { key: 'actions', label: '' },
]

function targetSummary(t: Policy['target_servers']): string {
  if (!t) return '—'
  if (t.all) return 'Toate serverele'
  if (t.agent_ids?.length) return `${t.agent_ids.length} servere`
  if (t.filters) return Object.entries(t.filters).map(([k, v]) => `${k}=${v}`).join(', ') || 'Filtru'
  return '—'
}

function fmtDate(v: string | null): string {
  return v ? new Date(v).toLocaleString() : '—'
}

async function toggleEnabled(policy: Policy) {
  try {
    await store.toggleEnabled(policy)
  } catch {
    toast.add({ title: 'Nu s-a putut schimba starea politicii', color: 'red' })
  }
}

const runningId = ref<string | null>(null)
async function runNow(policy: Policy) {
  runningId.value = policy.id
  try {
    const result = await store.runPolicy(policy.id)
    if (result.job_ids.length) {
      toast.add({ title: `Job creat pentru ${result.matched_agents} server(e)`, color: 'green' })
    } else if (result.matched_agents === 0) {
      toast.add({ title: 'Nicio țintă potrivită', color: 'amber' })
    } else {
      toast.add({ title: 'Sărit — un job identic e deja activ', color: 'amber' })
    }
  } catch {
    toast.add({ title: 'Rularea politicii a eșuat', color: 'red' })
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
    toast.add({ title: 'Politică ștearsă', color: 'green' })
    deletingPolicy.value = null
  } catch {
    toast.add({ title: 'Ștergerea a eșuat', color: 'red' })
  } finally {
    deleting.value = false
  }
}

onMounted(() => store.fetchPolicies())
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div class="flex flex-wrap items-center gap-3">
        <Select v-model="filters.policy_type" :options="POLICY_TYPES" placeholder="Categorie" class="w-44" @change="store.fetchPolicies()" />
        <Button variant="outline" @click="store.fetchPolicies()">
          <RefreshCw class="size-4" />
          Refresh
        </Button>
      </div>
      <div class="flex items-center gap-3">
        <Badge color="gray">{{ total }} politici</Badge>
        <Button v-if="canEdit" @click="openCreate">
          <Plus class="size-4" />
          Politică nouă
        </Button>
      </div>
    </div>

    <DataTable :rows="policies" :columns="columns" :loading="loading">
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

      <template #actions-data="{ row }">
        <div class="flex items-center justify-end gap-1">
          <Button size="xs" variant="ghost" class="text-muted-foreground" :loading="runningId === row.id" @click="runNow(row as unknown as Policy)">
            <Play class="size-3.5" />
          </Button>
          <NuxtLink :to="`/policies/${row.id}`">
            <Button size="xs" variant="ghost" class="text-muted-foreground">Detalii</Button>
          </NuxtLink>
          <Button v-if="canEdit" size="xs" variant="ghost" class="text-muted-foreground" @click="openEdit(row as unknown as Policy)">
            <Pencil class="size-3.5" />
          </Button>
          <Button v-if="canEdit" size="xs" variant="ghost" class="text-muted-foreground" @click="deletingPolicy = row as unknown as Policy">
            <Trash2 class="size-3.5" />
          </Button>
        </div>
      </template>
    </DataTable>

    <PolicyWizard v-if="showWizard" :policy="editingPolicy" @close="showWizard = false" @saved="onWizardSaved" />

    <Dialog :model-value="!!deletingPolicy" title="Șterge politica" @update:model-value="deletingPolicy = null">
      <template #body>
        <p class="text-sm text-muted-foreground">
          Ștergi <strong class="text-foreground">{{ deletingPolicy?.name }}</strong>? Acțiunea nu poate fi anulată.
        </p>
      </template>
      <template #footer>
        <Button variant="ghost" @click="deletingPolicy = null">Anulează</Button>
        <Button variant="destructive" :loading="deleting" @click="confirmDelete">Șterge</Button>
      </template>
    </Dialog>
  </div>
</template>
