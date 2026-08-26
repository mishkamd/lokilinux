<script setup lang="ts">
import { RefreshCw, Plus, Play, Pencil, Trash2, History } from 'lucide-vue-next'
import type { PlaybookTemplate } from '~/stores/playbook_templates'
import type { Job } from '~/stores/jobs'

const store = usePlaybookTemplatesStore()
const playbooksStore = usePlaybooksStore()
const serversStore = useServersStore()
const { canEdit } = useCurrentUser()
const toast = useToast()
const { statusColor } = useJobs()

const columns = [
  { key: 'name', label: 'Name' },
  { key: 'playbook_id', label: 'Playbook' },
  { key: 'agent_ids', label: 'Agents' },
  { key: 'updated_at', label: 'Updated' },
  { key: 'actions', label: '' },
]

await Promise.all([store.fetchTemplates(), playbooksStore.fetchPlaybooks()])

function playbookName(id: string): string {
  return playbooksStore.playbooks.find((p) => p.id === id)?.name ?? id
}

// ── Create/edit ───────────────────────────────────────────────────────────
const showEditor = ref(false)
const editingId = ref<string | null>(null)
const agentOptions = ref<Array<{ label: string; value: string }>>([])
const playbookOptions = computed(() => playbooksStore.playbooks.map((p) => ({ label: p.name, value: p.id })))
const form = ref({ name: '', description: '', playbook_id: '', agent_ids: [] as string[], extra_vars: '{}' })
const saving = ref(false)

async function openCreate() {
  editingId.value = null
  form.value = { name: '', description: '', playbook_id: '', agent_ids: [], extra_vars: '{}' }
  if (!agentOptions.value.length) agentOptions.value = await serversStore.fetchAgentsForSelect()
  showEditor.value = true
}

async function openEdit(template: PlaybookTemplate) {
  editingId.value = template.id
  form.value = {
    name: template.name,
    description: template.description ?? '',
    playbook_id: template.playbook_id,
    agent_ids: template.agent_ids,
    extra_vars: JSON.stringify(template.extra_vars ?? {}, null, 2),
  }
  if (!agentOptions.value.length) agentOptions.value = await serversStore.fetchAgentsForSelect()
  showEditor.value = true
}

async function saveForm() {
  if (!form.value.name.trim() || !form.value.playbook_id || !form.value.agent_ids.length) {
    toast.add({ title: 'Name, playbook and at least one agent are required', color: 'red' })
    return
  }
  let extraVars: Record<string, unknown>
  try {
    extraVars = JSON.parse(form.value.extra_vars || '{}')
  } catch {
    toast.add({ title: 'extra_vars must be valid JSON', color: 'red' })
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.value.name,
      description: form.value.description,
      playbook_id: form.value.playbook_id,
      agent_ids: form.value.agent_ids,
      extra_vars: extraVars,
    }
    if (editingId.value) {
      await store.updateTemplate(editingId.value, payload)
    } else {
      await store.createTemplate(payload)
    }
    showEditor.value = false
    toast.add({ title: 'Job Template saved', color: 'green' })
  } catch {
    toast.add({ title: 'Failed to save template', color: 'red' })
  } finally {
    saving.value = false
  }
}

// ── Delete ────────────────────────────────────────────────────────────────
const deletingTemplate = ref<PlaybookTemplate | null>(null)
const deleting = ref(false)

async function confirmDelete() {
  if (!deletingTemplate.value) return
  deleting.value = true
  try {
    await store.deleteTemplate(deletingTemplate.value.id)
    toast.add({ title: 'Job Template deleted', color: 'green' })
    deletingTemplate.value = null
  } catch {
    toast.add({ title: 'Failed to delete template', color: 'red' })
  } finally {
    deleting.value = false
  }
}

// ── Launch ────────────────────────────────────────────────────────────────
const launching = ref<string | null>(null)

async function launch(template: PlaybookTemplate) {
  launching.value = template.id
  try {
    const job = await store.launchTemplate(template.id)
    toast.add({ title: 'Job created — requires approval', description: `Job "${job.name}" awaits approval in Jobs.`, color: 'green' })
  } catch {
    toast.add({ title: 'Failed to launch template', color: 'red' })
  } finally {
    launching.value = null
  }
}

// ── History ───────────────────────────────────────────────────────────────
const historyTemplate = ref<PlaybookTemplate | null>(null)
const history = ref<Job[]>([])
const historyLoading = ref(false)

async function openHistory(template: PlaybookTemplate) {
  historyTemplate.value = template
  historyLoading.value = true
  try {
    history.value = await store.fetchHistory(template.id)
  } finally {
    historyLoading.value = false
  }
}
</script>

<template>
  <div>
    <PageHeader>
      <div class="flex flex-wrap items-center gap-3">
        <Button variant="outline" @click="store.fetchTemplates()">
          <RefreshCw class="size-4" />
          Refresh
        </Button>
        <Badge color="gray">{{ store.templates.length }} templates</Badge>
      </div>
      <Button v-if="canEdit" @click="openCreate()">
        <Plus class="size-4" />
        New Job Template
      </Button>
    </PageHeader>

    <Alert
      color="blue"
      class="mb-4"
      title="Job Templates"
      description="A saved playbook + agents + extra_vars combo — launch it repeatedly with one click. Every launch still requires admin approval on the Jobs page before it reaches agents."
    />

    <DataTable
      :rows="store.templates"
      :columns="columns"
      :loading="store.loading"
      sortable
      :page-size="25"
      empty-title="No templates"
    >
      <template #playbook_id-data="{ row }">
        <span class="text-sm">{{ playbookName((row as PlaybookTemplate).playbook_id) }}</span>
      </template>
      <template #agent_ids-data="{ row }">
        <Badge color="gray" size="xs">{{ (row as PlaybookTemplate).agent_ids.length }} agents</Badge>
      </template>
      <template #updated_at-data="{ row }">
        <span class="font-mono text-xs">{{ new Date(String((row as PlaybookTemplate).updated_at)).toLocaleString() }}</span>
      </template>
      <template #actions-data="{ row }">
        <div class="flex items-center justify-end gap-1">
          <Tooltip text="Launch template">
            <Button size="xs" variant="ghost" class="text-success" aria-label="Launch template" :loading="launching === (row as PlaybookTemplate).id" @click="launch(row as PlaybookTemplate)">
              <Play class="size-3.5" />
            </Button>
          </Tooltip>
          <Tooltip text="View history">
            <Button size="xs" variant="ghost" aria-label="View history" @click="openHistory(row as PlaybookTemplate)">
              <History class="size-3.5" />
            </Button>
          </Tooltip>
          <Tooltip v-if="canEdit" text="Edit template">
            <Button v-if="canEdit" size="xs" variant="ghost" aria-label="Edit template" @click="openEdit(row as PlaybookTemplate)">
              <Pencil class="size-3.5" />
            </Button>
          </Tooltip>
          <Tooltip v-if="canEdit" text="Delete template">
            <Button v-if="canEdit" size="xs" variant="ghost" aria-label="Delete template" @click="deletingTemplate = row as PlaybookTemplate">
              <Trash2 class="size-3.5" />
            </Button>
          </Tooltip>
        </div>
      </template>
    </DataTable>

    <!-- Create/Edit Dialog -->
    <Dialog v-model="showEditor" :title="editingId ? 'Edit Job Template' : 'New Job Template'">
      <template #body>
        <div class="space-y-4">
          <FormField label="Name" required>
            <Input v-model="form.name" placeholder="Template name..." />
          </FormField>
          <FormField label="Description">
            <Input v-model="form.description" placeholder="What this template does..." />
          </FormField>
          <FormField label="Playbook" required>
            <Select v-model="form.playbook_id" :options="playbookOptions" />
          </FormField>
          <FormField label="Default runner servers" required>
            <MultiSelect v-model="form.agent_ids" :options="agentOptions" placeholder="Select default runner servers..." />
          </FormField>
          <FormField label="Default extra_vars (JSON)">
            <textarea
              v-model="form.extra_vars"
              rows="4"
              class="w-full rounded-lg border border-input bg-card px-2.5 py-1.5 text-sm font-mono"
            />
          </FormField>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showEditor = false">Cancel</Button>
        <Button :loading="saving" @click="saveForm">Save</Button>
      </template>
    </Dialog>

    <!-- Delete confirm -->
    <ConfirmDeleteDialog
      :model-value="!!deletingTemplate"
      :entity-name="deletingTemplate?.name"
      :loading="deleting"
      title="Delete Job Template"
      @update:model-value="deletingTemplate = null"
      @confirm="confirmDelete"
    />

    <!-- History sheet -->
    <Sheet :model-value="!!historyTemplate" @update:model-value="(v: boolean) => { if (!v) historyTemplate = null }">
      <div v-if="historyTemplate" class="p-6 space-y-4 pt-12">
        <h2 class="text-lg font-bold">{{ historyTemplate.name }} — history</h2>
        <p v-if="historyLoading" class="text-sm text-muted-foreground">Loading…</p>
        <EmptyState v-else-if="!history.length">No launches yet.</EmptyState>
        <div v-else class="space-y-1">
          <div v-for="job in history" :key="job.id" class="rounded border border-border p-2 text-sm flex items-center gap-2">
            <Badge :color="statusColor(String(job.status))" size="xs">{{ job.status }}</Badge>
            <span class="flex-1">{{ job.name }}</span>
            <span class="text-xs text-muted-foreground font-mono">{{ new Date(String(job.created_at)).toLocaleString() }}</span>
          </div>
        </div>
      </div>
    </Sheet>
  </div>
</template>
