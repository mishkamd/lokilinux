<script setup lang="ts">
import { Plus, Trash2, Workflow as WorkflowIcon } from 'lucide-vue-next'
import type { Workflow } from '~/types/workflow'

const store = useWorkflowsStore()
const { workflows, loading } = storeToRefs(store)
const { canEdit } = useCurrentUser()
const toast = useToast()

onMounted(() => store.fetchWorkflows())

const columns = [
  { key: 'name', label: 'Name' },
  { key: 'trigger_type', label: 'Trigger' },
  { key: 'severity', label: 'Severity' },
  { key: 'current_version_id', label: 'Status' },
  { key: 'last_run_at', label: 'Last run' },
  { key: 'actions', label: '' },
]

function fmtDate(v: string | null): string {
  return v ? new Date(v).toLocaleString() : '—'
}

const SEVERITY_COLOR: Record<string, string> = { CRITICAL: 'red', HIGH: 'orange', MEDIUM: 'amber', LOW: 'blue' }

const showCreate = ref(false)
const createForm = ref({ name: '', yaml: '' })
const creating = ref(false)

const STARTER_YAML = `apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: my-new-workflow
spec:
  targets:
    all: true
  steps:
    - { id: step1, type: command, name: First step, config: { command: "true" } }
  edges: []
`

function openCreate() {
  createForm.value = { name: '', yaml: STARTER_YAML }
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  try {
    const workflow = await store.createWorkflow(createForm.value.name, createForm.value.yaml)
    showCreate.value = false
    await navigateTo(`/workflows/${workflow.id}`)
  } catch (e) {
    const detail = (e as { data?: { detail?: unknown } })?.data?.detail
    toast.add({ title: 'Could not create workflow', description: typeof detail === 'string' ? detail : 'Check the YAML is valid.', color: 'red' })
  } finally {
    creating.value = false
  }
}

const deletingId = ref<string | null>(null)
async function remove(workflow: Workflow) {
  deletingId.value = workflow.id
  try {
    await store.deleteWorkflow(workflow.id)
  } catch {
    toast.add({ title: 'Could not delete workflow', color: 'red' })
  } finally {
    deletingId.value = null
  }
}
</script>

<template>
  <div>
    <div class="flex items-center justify-end mb-3">
      <Button v-if="canEdit" size="sm" @click="openCreate">
        <Plus class="size-4" />
        New Workflow
      </Button>
    </div>

    <DataTable
      :rows="workflows"
      :columns="columns"
      :loading="loading"
      sortable
      :page-size="25"
      empty-title="No workflows"
      empty-description="Create a workflow to automate remediation."
      rows-clickable
      @row-click="(row) => navigateTo(`/workflows/${(row as unknown as Workflow).id}`)"
    >
      <template #name-data="{ row }">
        <div class="flex items-center gap-2">
          <span class="flex size-7 shrink-0 items-center justify-center rounded-md bg-[color-mix(in_oklch,var(--info)_15%,transparent)] text-info">
            <WorkflowIcon class="size-3.5" />
          </span>
          <div class="min-w-0">
            <p class="font-medium leading-tight truncate">{{ row.name as string }}</p>
            <p class="text-xs text-muted-foreground truncate">{{ row.slug as string }}</p>
          </div>
        </div>
      </template>
      <template #trigger_type-data="{ row }">
        <Badge size="xs" :color="row.trigger_type === 'SCHEDULE' ? 'blue' : 'gray'">{{ row.trigger_type }}</Badge>
      </template>
      <template #severity-data="{ row }">
        <Badge v-if="row.severity" size="xs" :color="SEVERITY_COLOR[row.severity as string] ?? 'gray'">{{ row.severity }}</Badge>
        <span v-else class="text-xs text-muted-foreground">—</span>
      </template>
      <template #current_version_id-data="{ row }">
        <Badge size="xs" :color="row.current_version_id ? 'green' : 'gray'">{{ row.current_version_id ? 'Published' : 'Draft only' }}</Badge>
      </template>
      <template #last_run_at-data="{ row }">
        <span class="text-xs text-muted-foreground font-mono">{{ fmtDate(row.last_run_at as string | null) }}</span>
      </template>
      <template #actions-data="{ row }">
        <div v-if="canEdit" class="flex items-center justify-end">
          <Tooltip text="Delete workflow">
            <Button
              size="xs" variant="ghost"
              aria-label="Delete workflow"
              :loading="deletingId === row.id"
              @click.stop="remove(row as unknown as Workflow)"
            >
              <Trash2 class="size-3.5" />
            </Button>
          </Tooltip>
        </div>
      </template>
    </DataTable>

    <Dialog v-model="showCreate" title="New Workflow" size="xl">
      <template #body>
        <div class="space-y-3">
          <FormField label="Name" required>
            <Input v-model="createForm.name" placeholder="Oracle Linux 8 to 9 upgrade" />
          </FormField>
          <FormField label="YAML" help="metadata.name must be a lowercase-dash slug, 3-64 chars.">
            <Textarea v-model="createForm.yaml" :rows="16" class="text-xs" />
          </FormField>
        </div>
      </template>
      <template #footer>
        <Button variant="outline" @click="showCreate = false">Cancel</Button>
        <Button :loading="creating" :disabled="!createForm.name || !createForm.yaml" @click="submitCreate">Create</Button>
      </template>
    </Dialog>
  </div>
</template>
