<script setup lang="ts">
import { Plus, RefreshCw } from 'lucide-vue-next'
import type { ScopeType } from '~/stores/compliance'

const store = useComplianceStore()
const { baselines, baselinesTotal, baselinesLoading, baselineFilters } = storeToRefs(store)
const { canEdit } = useCurrentUser()
const toast = useToast()

onMounted(() => store.fetchBaselines())

const SCOPE_TYPES: ScopeType[] = ['GLOBAL', 'OS', 'ROLE', 'ENVIRONMENT', 'DATACENTER', 'CLUSTER', 'APPLICATION']

const columns = [
  { key: 'name', label: 'Name' },
  { key: 'scope_type', label: 'Scope' },
  { key: 'scope_selector', label: 'Selector' },
  { key: 'is_enabled', label: 'Status' },
  { key: 'created_at', label: 'Created' },
]

const showCreate = ref(false)
const form = ref({
  name: '',
  description: '',
  scope_type: 'GLOBAL' as ScopeType,
  scope_selector: '{}',
  expected_state: '{}',
})
const creating = ref(false)
const formError = ref<string | null>(null)

async function submitCreate() {
  formError.value = null
  let scopeSelector: Record<string, unknown>
  let expectedState: Record<string, unknown>
  try {
    scopeSelector = JSON.parse(form.value.scope_selector || '{}')
    expectedState = JSON.parse(form.value.expected_state || '{}')
  } catch {
    formError.value = 'Scope selector and expected state must be valid JSON.'
    return
  }

  creating.value = true
  try {
    await store.createBaseline({
      name: form.value.name,
      description: form.value.description || undefined,
      scope_type: form.value.scope_type,
      scope_selector: scopeSelector,
      expected_state: expectedState,
    })
    toast.add({ title: 'Baseline created', description: `${form.value.name} — version 1 (DRAFT)` })
    showCreate.value = false
    form.value = { name: '', description: '', scope_type: 'GLOBAL', scope_selector: '{}', expected_state: '{}' }
  } catch {
    toast.add({ title: 'Failed to create baseline', color: 'red' })
  } finally {
    creating.value = false
  }
}
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div class="flex flex-wrap items-center gap-3">
        <Select
          v-model="baselineFilters.scope_type"
          :options="['', ...SCOPE_TYPES]"
          placeholder="Scope type"
          class="w-44"
          @change="store.fetchBaselines()"
        />
        <Button variant="outline" @click="store.fetchBaselines()">
          <RefreshCw class="size-4" /> Refresh
        </Button>
      </div>
      <div class="flex items-center gap-3">
        <Badge color="gray">{{ baselinesTotal }} baselines</Badge>
        <Button v-if="canEdit" @click="showCreate = true">
          <Plus class="size-4" /> New baseline
        </Button>
      </div>
    </div>

    <DataTable :rows="baselines" :columns="columns" :loading="baselinesLoading" rows-clickable
               @row-click="(row) => navigateTo(`/compliance/baselines/${row.id}`)">
      <template #name-data="{ row }">
        <span class="font-medium">{{ row.name }}</span>
      </template>
      <template #scope_type-data="{ row }">
        <Badge color="gray" size="xs">{{ row.scope_type }}</Badge>
      </template>
      <template #scope_selector-data="{ row }">
        <span class="font-mono text-xs text-muted-foreground">{{ JSON.stringify(row.scope_selector) }}</span>
      </template>
      <template #is_enabled-data="{ row }">
        <Badge :color="row.is_enabled ? 'green' : 'gray'" size="xs">{{ row.is_enabled ? 'Enabled' : 'Disabled' }}</Badge>
      </template>
      <template #created_at-data="{ row }">
        <span class="font-mono text-xs">{{ new Date(String(row.created_at)).toLocaleDateString() }}</span>
      </template>
    </DataTable>

    <Dialog v-model="showCreate" title="New baseline">
      <template #body>
        <div class="space-y-4">
          <FormField label="Name" required>
            <Input v-model="form.name" placeholder="OL9 Database Servers" />
          </FormField>
          <FormField label="Description">
            <Input v-model="form.description" placeholder="Optional" />
          </FormField>
          <FormField label="Scope type" required>
            <Select v-model="form.scope_type" :options="SCOPE_TYPES" />
          </FormField>
          <FormField label="Scope selector" help="JSON — e.g. {&quot;role&quot;: &quot;database&quot;}">
            <textarea
              v-model="form.scope_selector"
              rows="3"
              class="flex w-full rounded-lg border border-input bg-card px-2.5 py-1.5 text-[13px] font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-primary"
            />
          </FormField>
          <FormField label="Expected state (version 1)" help="JSON, keyed by domain — e.g. sshd, sysctl">
            <textarea
              v-model="form.expected_state"
              rows="6"
              class="flex w-full rounded-lg border border-input bg-card px-2.5 py-1.5 text-[13px] font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-primary"
            />
          </FormField>
          <Alert v-if="formError" color="red">{{ formError }}</Alert>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showCreate = false">Cancel</Button>
        <Button :loading="creating" :disabled="!form.name" @click="submitCreate">Create</Button>
      </template>
    </Dialog>
  </div>
</template>
