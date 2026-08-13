<script setup lang="ts">
import { Plus, RefreshCw } from 'lucide-vue-next'

const store = useComplianceStore()
const { exceptions, exceptionsTotal, exceptionsLoading, exceptionsNextCursor, exceptionFilters } = storeToRefs(store)
const { canEdit, isAdmin } = useCurrentUser()
const toast = useToast()

onMounted(() => store.fetchExceptions())

const STATUS_COLORS: Record<string, string> = {
  PENDING: 'amber', ACTIVE: 'green', EXPIRED: 'gray', REVOKED: 'gray',
}

const columns = [
  { key: 'rule_id', label: 'Rule' },
  { key: 'owner', label: 'Owner' },
  { key: 'reason', label: 'Reason' },
  { key: 'status', label: 'Status' },
  { key: 'expires_at', label: 'Expires' },
  { key: 'actions', label: '' },
]

const showCreate = ref(false)
const form = ref({ rule_id: '', reason: '', owner: '', expires_at: '', agent_id: '' })
const creating = ref(false)
const formError = ref<string | null>(null)

async function submitCreate() {
  formError.value = null
  if (!form.value.rule_id || !form.value.reason || !form.value.owner || !form.value.expires_at) {
    formError.value = 'Rule, reason, owner, and expiry are all required.'
    return
  }
  creating.value = true
  try {
    await store.createException({
      rule_id: form.value.rule_id,
      reason: form.value.reason,
      owner: form.value.owner,
      expires_at: new Date(form.value.expires_at).toISOString(),
      agent_id: form.value.agent_id || undefined,
    })
    toast.add({ title: 'Exception requested', description: 'Pending approval before it waives anything.' })
    showCreate.value = false
    form.value = { rule_id: '', reason: '', owner: '', expires_at: '', agent_id: '' }
  } catch {
    toast.add({ title: 'Failed to create exception', color: 'red' })
  } finally {
    creating.value = false
  }
}

async function approve(id: string) {
  try {
    await store.approveException(id)
    toast.add({ title: 'Exception approved' })
  } catch {
    toast.add({ title: 'Failed to approve', color: 'red' })
  }
}

async function revoke(id: string) {
  try {
    await store.revokeException(id)
    toast.add({ title: 'Exception revoked' })
  } catch {
    toast.add({ title: 'Failed to revoke', color: 'red' })
  }
}
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div class="flex flex-wrap items-center gap-3">
        <Select
          v-model="exceptionFilters.status"
          :options="[{ label: 'All', value: '' }, { label: 'Pending', value: 'PENDING' }, { label: 'Active', value: 'ACTIVE' }, { label: 'Expired', value: 'EXPIRED' }, { label: 'Revoked', value: 'REVOKED' }]"
          placeholder="Status"
          class="w-40"
          @change="store.fetchExceptions()"
        />
        <Button variant="outline" @click="store.fetchExceptions()">
          <RefreshCw class="size-4" /> Refresh
        </Button>
      </div>
      <div class="flex items-center gap-3">
        <Badge color="gray">{{ exceptionsTotal }} exceptions</Badge>
        <Button v-if="canEdit" @click="showCreate = true">
          <Plus class="size-4" /> New exception
        </Button>
      </div>
    </div>

    <DataTable :rows="exceptions" :columns="columns" :loading="exceptionsLoading">
      <template #rule_id-data="{ row }">
        <span class="font-mono text-xs">{{ row.rule_id }}</span>
      </template>
      <template #reason-data="{ row }">
        <span class="text-sm truncate max-w-xs block" :title="row.reason">{{ row.reason }}</span>
      </template>
      <template #status-data="{ row }">
        <Badge :color="STATUS_COLORS[String(row.status)] ?? 'gray'" size="xs">{{ row.status }}</Badge>
      </template>
      <template #expires_at-data="{ row }">
        <span class="font-mono text-xs">{{ new Date(String(row.expires_at)).toLocaleDateString() }}</span>
      </template>
      <template #actions-data="{ row }">
        <div class="flex items-center gap-1">
          <Button v-if="isAdmin && row.status === 'PENDING'" size="xs" variant="ghost" @click="approve(String(row.id))">
            Approve
          </Button>
          <Button v-if="canEdit && ['PENDING', 'ACTIVE'].includes(String(row.status))" size="xs" variant="ghost" @click="revoke(String(row.id))">
            Revoke
          </Button>
        </div>
      </template>
    </DataTable>

    <div v-if="exceptionsNextCursor" class="mt-4 flex justify-center">
      <Button variant="outline" @click="store.fetchExceptions(exceptionsNextCursor!)">
        Load more
      </Button>
    </div>

    <Dialog v-model="showCreate" title="New exception">
      <template #body>
        <div class="space-y-4">
          <FormField label="Rule ID" required help="UUID of the compliance rule">
            <Input v-model="form.rule_id" placeholder="e.g. from the Rule Catalog" />
          </FormField>
          <FormField label="Agent ID" help="Leave empty for a broader-scope exception">
            <Input v-model="form.agent_id" placeholder="Optional" />
          </FormField>
          <FormField label="Reason" required>
            <Input v-model="form.reason" placeholder="Legacy application requirement" />
          </FormField>
          <FormField label="Owner" required>
            <Input v-model="form.owner" placeholder="Infrastructure team" />
          </FormField>
          <FormField label="Expires" required>
            <Input v-model="form.expires_at" type="date" />
          </FormField>
          <Alert v-if="formError" color="red">{{ formError }}</Alert>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showCreate = false">Cancel</Button>
        <Button :loading="creating" @click="submitCreate">Request exception</Button>
      </template>
    </Dialog>
  </div>
</template>
