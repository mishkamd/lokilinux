<script setup lang="ts">
import { RefreshCw, Plus, Pencil, Trash2 } from 'lucide-vue-next'
import type { AnsibleProject } from '~/stores/ansible_projects'

const store = useAnsibleProjectsStore()
const serversStore = useServersStore()
const { canEdit } = useCurrentUser()
const toast = useToast()

const columns = [
  { key: 'name', label: 'Name' },
  { key: 'default_agent_ids', label: 'Default Agents' },
  { key: 'updated_at', label: 'Updated' },
  { key: 'actions', label: '' },
]

await store.fetchProjects()

// ── Create/edit ───────────────────────────────────────────────────────────
const showEditor = ref(false)
const editingId = ref<string | null>(null)
const form = ref({ name: '', description: '', default_agent_ids: [] as string[] })
const agentOptions = ref<Array<{ label: string; value: string }>>([])
const saving = ref(false)

async function openCreate() {
  editingId.value = null
  form.value = { name: '', description: '', default_agent_ids: [] }
  if (!agentOptions.value.length) agentOptions.value = await serversStore.fetchAgentsForSelect()
  showEditor.value = true
}

async function openEdit(project: AnsibleProject) {
  editingId.value = project.id
  form.value = { name: project.name, description: project.description ?? '', default_agent_ids: project.default_agent_ids }
  if (!agentOptions.value.length) agentOptions.value = await serversStore.fetchAgentsForSelect()
  showEditor.value = true
}

async function saveForm() {
  if (!form.value.name.trim()) {
    toast.add({ title: 'Name is required', color: 'red' })
    return
  }
  saving.value = true
  try {
    if (editingId.value) {
      await store.updateProject(editingId.value, form.value)
    } else {
      await store.createProject(form.value)
    }
    showEditor.value = false
    toast.add({ title: 'Project saved', color: 'green' })
  } catch {
    toast.add({ title: 'Failed to save project', color: 'red' })
  } finally {
    saving.value = false
  }
}

// ── Delete ────────────────────────────────────────────────────────────────
const deletingProject = ref<AnsibleProject | null>(null)
const deleting = ref(false)

async function confirmDelete() {
  if (!deletingProject.value) return
  deleting.value = true
  try {
    await store.deleteProject(deletingProject.value.id)
    toast.add({ title: 'Project deleted', color: 'green' })
    deletingProject.value = null
  } catch {
    toast.add({ title: 'Failed to delete project', color: 'red' })
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-4">
      <div class="flex items-center gap-3">
        <Button variant="outline" @click="store.fetchProjects()">
          <RefreshCw class="size-4" />
          Refresh
        </Button>
        <Badge color="gray">{{ store.projects.length }} projects</Badge>
      </div>
      <Button v-if="canEdit" @click="openCreate()">
        <Plus class="size-4" />
        New Project
      </Button>
    </div>

    <Alert
      color="blue"
      class="mb-4"
      title="Projects"
      description="Groups playbooks the way a real Ansible tree's projects/<name>/ does. Default agents are this project's inventory — playbooks attached to it default to targeting them. Playbooks with no project show under Debug/Uncategorized."
    />

    <DataTable :rows="store.projects" :columns="columns" :loading="store.loading">
      <template #default_agent_ids-data="{ row }">
        <Badge color="gray" size="xs">{{ (row as AnsibleProject).default_agent_ids.length }} agents</Badge>
      </template>
      <template #updated_at-data="{ row }">
        <span class="font-mono text-xs">{{ new Date(String((row as AnsibleProject).updated_at)).toLocaleString() }}</span>
      </template>
      <template #actions-data="{ row }">
        <div class="flex items-center justify-end gap-1">
          <Button v-if="canEdit" size="xs" variant="ghost" class="text-muted-foreground" @click="openEdit(row as AnsibleProject)">
            <Pencil class="size-3.5" />
          </Button>
          <Button v-if="canEdit" size="xs" variant="ghost" class="text-muted-foreground" @click="deletingProject = row as AnsibleProject">
            <Trash2 class="size-3.5" />
          </Button>
        </div>
      </template>
    </DataTable>

    <!-- Create/Edit Dialog -->
    <Dialog v-model="showEditor" :title="editingId ? 'Edit Project' : 'New Project'">
      <template #body>
        <div class="space-y-4">
          <FormField label="Name" required>
            <Input v-model="form.name" placeholder="Project name (e.g. docker, elk, keycloak)..." />
          </FormField>
          <FormField label="Description">
            <Input v-model="form.description" placeholder="What this project covers..." />
          </FormField>
          <FormField label="Default agents" help="Playbooks in this project default to targeting these agents">
            <MultiSelect v-model="form.default_agent_ids" :options="agentOptions" placeholder="Select default agents..." />
          </FormField>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showEditor = false">Cancel</Button>
        <Button :loading="saving" @click="saveForm">Save</Button>
      </template>
    </Dialog>

    <!-- Delete confirm -->
    <Dialog :model-value="!!deletingProject" title="Delete Project" @update:model-value="deletingProject = null">
      <template #body>
        <p class="text-sm text-muted-foreground">
          Delete <strong class="text-foreground">{{ deletingProject?.name }}</strong>?
          Playbooks in it move to Debug/Uncategorized — nothing is deleted.
        </p>
      </template>
      <template #footer>
        <Button variant="ghost" @click="deletingProject = null">Cancel</Button>
        <Button variant="destructive" :loading="deleting" @click="confirmDelete">Delete</Button>
      </template>
    </Dialog>
  </div>
</template>
