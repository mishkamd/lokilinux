<script setup lang="ts">
import { Plus, Trash2 } from 'lucide-vue-next'
import type { Runbook, RunbookInput } from '~/stores/runbooks'

const store = useRunbooksStore()
const workflowsStore = useWorkflowsStore()
const { runbooks, loading } = storeToRefs(store)
const { workflows } = storeToRefs(workflowsStore)
const toast = useToast()

const columns = [
  { key: 'name', label: 'Name' },
  { key: 'incident_type', label: 'Incident type' },
  { key: 'workflow_id', label: 'Workflow' },
  { key: 'trigger_mode', label: 'Trigger' },
  { key: 'min_severity', label: 'Min severity' },
  { key: 'enabled', label: 'Enabled' },
  { key: 'actions', label: '' },
]

const workflowOptions = computed(() => workflows.value.map((w) => ({ label: w.name, value: w.id })))
function workflowName(id: string | null): string {
  if (!id) return '—'
  return workflows.value.find((w) => w.id === id)?.name ?? id
}

const showEditor = ref(false)
const editingId = ref<string | null>(null)
const submitting = ref(false)
const form = ref<RunbookInput>(emptyForm())

function emptyForm(): RunbookInput {
  return { name: '', incident_type: '', workflow_id: null, trigger_mode: 'MANUAL', min_severity: 'HIGH', enabled: true }
}

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  showEditor.value = true
}

function openEdit(runbook: Runbook) {
  editingId.value = runbook.id
  form.value = {
    name: runbook.name, incident_type: runbook.incident_type, workflow_id: runbook.workflow_id,
    trigger_mode: runbook.trigger_mode, min_severity: runbook.min_severity, enabled: runbook.enabled,
  }
  showEditor.value = true
}

async function submit() {
  if (!form.value.name.trim() || !form.value.incident_type.trim()) {
    toast.add({ title: 'Invalid runbook', description: 'Name and incident type are required', color: 'red' })
    return
  }
  submitting.value = true
  try {
    if (editingId.value) {
      await store.updateRunbook(editingId.value, form.value)
      toast.add({ title: 'Runbook updated', color: 'green' })
    } else {
      await store.createRunbook(form.value)
      toast.add({ title: 'Runbook created', color: 'green' })
    }
    showEditor.value = false
  } catch {
    toast.add({ title: 'Error', description: 'Failed to save runbook', color: 'red' })
  } finally {
    submitting.value = false
  }
}

const deletingRunbook = ref<Runbook | null>(null)
const deleting = ref(false)

async function confirmDelete() {
  if (!deletingRunbook.value) return
  deleting.value = true
  try {
    await store.deleteRunbook(deletingRunbook.value.id)
    deletingRunbook.value = null
  } catch {
    toast.add({ title: 'Error', description: 'Failed to delete runbook', color: 'red' })
  } finally {
    deleting.value = false
  }
}

async function toggle(runbook: Runbook) {
  try {
    await store.toggleEnabled(runbook)
  } catch {
    toast.add({ title: 'Error', description: 'Failed to toggle runbook', color: 'red' })
  }
}

onMounted(() => {
  store.fetchRunbooks()
  workflowsStore.fetchWorkflows()
})
</script>

<template>
  <div>
    <div class="flex items-center justify-end mb-4">
      <Button @click="openCreate">
        <Plus class="size-4" />
        New runbook
      </Button>
    </div>

    <DataTable :rows="runbooks" :columns="columns" :loading="loading">
      <template #name-data="{ row }">
        <button class="font-medium hover:underline" @click="openEdit(row as Runbook)">{{ row.name }}</button>
      </template>
      <template #incident_type-data="{ row }">
        <span class="font-mono text-xs">{{ row.incident_type }}</span>
      </template>
      <template #workflow_id-data="{ row }">
        <span class="text-xs">{{ workflowName(row.workflow_id as string | null) }}</span>
      </template>
      <template #trigger_mode-data="{ row }">
        <Badge :color="row.trigger_mode === 'AUTO' ? 'blue' : 'gray'" size="xs">{{ row.trigger_mode }}</Badge>
      </template>
      <template #enabled-data="{ row }">
        <Switch :model-value="Boolean(row.enabled)" @update:model-value="toggle(row as Runbook)" />
      </template>
      <template #actions-data="{ row }">
        <Button size="xs" variant="ghost" class="text-muted-foreground" @click="deletingRunbook = row as Runbook">
          <Trash2 class="size-3.5" />
        </Button>
      </template>
    </DataTable>

    <Dialog v-model="showEditor" :title="editingId ? 'Edit runbook' : 'New runbook'">
      <template #body>
        <div class="space-y-4">
          <FormField label="Name" required>
            <Input v-model="form.name" />
          </FormField>
          <FormField label="Incident type" required>
            <Input v-model="form.incident_type" placeholder="application_degradation" />
          </FormField>
          <FormField label="Workflow">
            <Select
              :model-value="form.workflow_id ?? undefined"
              :options="workflowOptions"
              placeholder="Select workflow..."
              @update:model-value="(v) => (form.workflow_id = v ?? null)"
            />
          </FormField>
          <FormField label="Trigger mode">
            <Select v-model="form.trigger_mode" :options="['MANUAL', 'AUTO']" />
          </FormField>
          <FormField label="Minimum severity">
            <Select v-model="form.min_severity" :options="['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']" />
          </FormField>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showEditor = false">Cancel</Button>
        <Button :loading="submitting" @click="submit">{{ editingId ? 'Save' : 'Create' }}</Button>
      </template>
    </Dialog>

    <Dialog :model-value="!!deletingRunbook" title="Delete runbook" @update:model-value="deletingRunbook = null">
      <template #body>
        <p class="text-sm text-muted-foreground">
          Delete <strong class="text-foreground">{{ deletingRunbook?.name }}</strong>? This cannot be undone.
        </p>
      </template>
      <template #footer>
        <Button variant="ghost" @click="deletingRunbook = null">Cancel</Button>
        <Button variant="destructive" :loading="deleting" @click="confirmDelete">Delete</Button>
      </template>
    </Dialog>
  </div>
</template>
