<script setup lang="ts">
import { RefreshCw, Plus, Pencil, Trash2, Play, Upload } from 'lucide-vue-next'
import type { Playbook } from '~/stores/playbooks'

const store = usePlaybooksStore()
const serversStore = useServersStore()
const projectsStore = useAnsibleProjectsStore()
const { canEdit } = useCurrentUser()
const toast = useToast()

const NO_PROJECT = '__none__'

const columns = [
  { key: 'name', label: 'Name' },
  { key: 'project_id', label: 'Project' },
  { key: 'version', label: 'Version' },
  { key: 'is_enabled', label: 'Status' },
  { key: 'updated_at', label: 'Updated' },
  { key: 'actions', label: '' },
]

await Promise.all([store.fetchPlaybooks(), projectsStore.fetchProjects()])

const projectFilter = ref('')
const projectFilterOptions = computed(() => [
  { label: 'All projects', value: '' },
  { label: 'Debug / Uncategorized', value: NO_PROJECT },
  ...projectsStore.projects.map((p) => ({ label: p.name, value: p.id })),
])

function projectName(id: string | null): string {
  if (!id) return 'Debug / Uncategorized'
  return projectsStore.projects.find((p) => p.id === id)?.name ?? id
}

const filteredPlaybooks = computed(() => {
  if (!projectFilter.value) return store.playbooks
  if (projectFilter.value === NO_PROJECT) return store.playbooks.filter((p) => !p.project_id)
  return store.playbooks.filter((p) => p.project_id === projectFilter.value)
})

// ── Create/edit — dedicated editor page ──────────────────────────────────
function openCreate() {
  navigateTo('/automation/ansible/playbooks/new')
}

function openEdit(playbook: Playbook) {
  navigateTo(`/automation/ansible/playbooks/${playbook.id}`)
}

// ── Upload .yml files as playbooks ────────────────────────────────────────
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)

async function onFilesSelected(e: Event) {
  const files = (e.target as HTMLInputElement).files
  if (!files?.length) return
  uploading.value = true
  let created = 0
  try {
    for (const file of Array.from(files)) {
      const content = await file.text()
      if (!content.trim()) continue
      const name = file.name.replace(/\.(ya?ml)$/i, '')
      await store.createPlaybook({ name, description: `Uploaded from ${file.name}`, content })
      created++
    }
    toast.add({ title: `${created} playbook(s) uploaded`, color: 'green' })
  } catch {
    toast.add({ title: created ? `Uploaded ${created}, then failed` : 'Upload failed', color: 'red' })
  } finally {
    uploading.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

// ── Delete ────────────────────────────────────────────────────────────────
const deletingPlaybook = ref<Playbook | null>(null)
const deleting = ref(false)

async function confirmDelete() {
  if (!deletingPlaybook.value) return
  deleting.value = true
  try {
    await store.deletePlaybook(deletingPlaybook.value.id)
    toast.add({ title: 'Playbook deleted', color: 'green' })
    deletingPlaybook.value = null
  } catch {
    toast.add({ title: 'Failed to delete playbook', color: 'red' })
  } finally {
    deleting.value = false
  }
}

// ── Execute ───────────────────────────────────────────────────────────────
const executingPlaybook = ref<Playbook | null>(null)
const executeAgentIds = ref<string[]>([])
const executeExtraVars = ref('{}')
const agentOptions = ref<Array<{ label: string; value: string }>>([])
const executing = ref(false)

async function openExecute(playbook: Playbook) {
  executingPlaybook.value = playbook
  executeAgentIds.value = []
  executeExtraVars.value = '{}'
  if (!agentOptions.value.length) {
    agentOptions.value = await serversStore.fetchAgentsForSelect()
  }
}

async function confirmExecute() {
  if (!executingPlaybook.value) return
  if (!executeAgentIds.value.length) {
    toast.add({ title: 'Select at least one agent', color: 'red' })
    return
  }
  let extraVars: Record<string, unknown>
  try {
    extraVars = JSON.parse(executeExtraVars.value || '{}')
  } catch {
    toast.add({ title: 'extra_vars must be valid JSON', color: 'red' })
    return
  }
  executing.value = true
  try {
    const job = await store.executePlaybook(executingPlaybook.value.id, executeAgentIds.value, extraVars)
    executingPlaybook.value = null
    toast.add({ title: 'Job created — requires approval', description: `Job "${job.name}" awaits approval in Jobs.`, color: 'green' })
  } catch {
    toast.add({ title: 'Failed to execute playbook', color: 'red' })
  } finally {
    executing.value = false
  }
}
</script>

<template>
  <div>
    <PageHeader>
      <div class="flex flex-wrap items-center gap-3">
        <Button variant="outline" @click="store.fetchPlaybooks()">
          <RefreshCw class="size-4" />
          Refresh
        </Button>
        <Select v-model="projectFilter" :options="projectFilterOptions" class="w-56" />
        <Badge color="gray">{{ filteredPlaybooks.length }} playbooks</Badge>
      </div>
      <div v-if="canEdit" class="flex items-center gap-2">
        <input
          ref="fileInput"
          type="file"
          accept=".yml,.yaml"
          multiple
          class="hidden"
          @change="onFilesSelected"
        />
        <Button variant="outline" :loading="uploading" @click="fileInput?.click()">
          <Upload class="size-4" />
          Upload
        </Button>
        <Button @click="openCreate()">
          <Plus class="size-4" />
          New Playbook
        </Button>
      </div>
    </PageHeader>

    <Alert
      color="blue"
      class="mb-4"
      title="Local execution only"
      description="Playbooks run locally on each selected agent (ansible-playbook --connection=local) — no SSH, no external inventory. Execution always requires admin approval on the Jobs page before it reaches agents."
    />

    <DataTable
      :rows="filteredPlaybooks"
      :columns="columns"
      :loading="store.loading"
      sortable
      :page-size="25"
      empty-title="No playbooks"
    >
      <template #project_id-data="{ row }">
        <Badge color="gray" size="xs">{{ projectName((row as Playbook).project_id) }}</Badge>
      </template>
      <template #version-data="{ row }">
        <span class="font-mono text-xs tabular-nums">v{{ (row as Playbook).version }}</span>
      </template>
      <template #is_enabled-data="{ row }">
        <Badge :color="(row as Playbook).is_enabled ? 'green' : 'gray'" size="xs">
          {{ (row as Playbook).is_enabled ? 'enabled' : 'disabled' }}
        </Badge>
      </template>
      <template #updated_at-data="{ row }">
        <span class="font-mono text-xs">{{ new Date(String((row as Playbook).updated_at)).toLocaleString() }}</span>
      </template>
      <template #actions-data="{ row }">
        <div class="flex items-center justify-end gap-1">
          <Tooltip text="Run playbook">
            <Button size="xs" variant="ghost" aria-label="Run playbook" @click="openExecute(row as Playbook)">
              <Play class="size-3.5" />
            </Button>
          </Tooltip>
          <Tooltip v-if="canEdit" text="Edit playbook">
            <Button v-if="canEdit" size="xs" variant="ghost" aria-label="Edit playbook" @click="openEdit(row as Playbook)">
              <Pencil class="size-3.5" />
            </Button>
          </Tooltip>
          <Tooltip v-if="canEdit" text="Delete playbook">
            <Button v-if="canEdit" size="xs" variant="ghost" aria-label="Delete playbook" @click="deletingPlaybook = row as Playbook">
              <Trash2 class="size-3.5" />
            </Button>
          </Tooltip>
        </div>
      </template>
    </DataTable>

    <!-- Delete confirm -->
    <ConfirmDeleteDialog
      :model-value="!!deletingPlaybook"
      :entity-name="deletingPlaybook?.name"
      :loading="deleting"
      title="Delete Playbook"
      @update:model-value="deletingPlaybook = null"
      @confirm="confirmDelete"
    />

    <!-- Execute dialog -->
    <Dialog :model-value="!!executingPlaybook" title="Run Playbook" @update:model-value="executingPlaybook = null">
      <template #body>
        <div class="space-y-4">
          <p class="text-sm text-muted-foreground">
            Running <strong class="text-foreground">{{ executingPlaybook?.name }}</strong> (v{{ executingPlaybook?.version }}).
            Creates a job that requires approval before agents pick it up.
          </p>
          <FormField label="Runner servers" required>
            <MultiSelect v-model="executeAgentIds" :options="agentOptions" placeholder="Select Ansible runner servers..." />
          </FormField>
          <FormField label="Extra vars (JSON)">
            <textarea
              v-model="executeExtraVars"
              rows="4"
              class="w-full rounded-lg border border-input bg-card px-2.5 py-1.5 text-sm font-mono"
            />
          </FormField>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="executingPlaybook = null">Cancel</Button>
        <Button :loading="executing" @click="confirmExecute">Run</Button>
      </template>
    </Dialog>
  </div>
</template>
