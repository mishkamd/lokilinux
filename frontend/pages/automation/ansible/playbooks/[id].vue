<script setup lang="ts">
import { ArrowLeft, Save, Play } from 'lucide-vue-next'
import type { Playbook } from '~/stores/playbooks'

const route = useRoute()
const store = usePlaybooksStore()
const serversStore = useServersStore()
const rolesStore = useAnsibleRolesStore()
const projectsStore = useAnsibleProjectsStore()
const { canEdit } = useCurrentUser()
const toast = useToast()

const NO_PROJECT = '__none__'

const isNew = computed(() => route.params.id === 'new')
const playbook = ref<Playbook | null>(null)
const form = ref({ name: '', description: '', content: '- hosts: localhost\n  tasks: []\n', role_ids: [] as string[], project_id: NO_PROJECT })
const saving = ref(false)

await Promise.all([rolesStore.fetchRoles(), projectsStore.fetchProjects()])
const roleOptions = computed(() => rolesStore.roles.map((r) => ({ label: r.name, value: r.id })))
const projectOptions = computed(() => [
  { label: 'Debug / Uncategorized', value: NO_PROJECT },
  ...projectsStore.projects.map((p) => ({ label: p.name, value: p.id })),
])

if (!isNew.value) {
  playbook.value = await store.fetchPlaybook(String(route.params.id))
  form.value = {
    name: playbook.value.name,
    description: playbook.value.description ?? '',
    content: playbook.value.content,
    role_ids: playbook.value.role_ids ?? [],
    project_id: playbook.value.project_id ?? NO_PROJECT,
  }
}

async function save() {
  if (!form.value.name.trim()) {
    toast.add({ title: 'Name is required', color: 'red' })
    return
  }
  saving.value = true
  try {
    const payload = {
      ...form.value,
      project_id: form.value.project_id === NO_PROJECT ? null : form.value.project_id,
    }
    if (isNew.value) {
      const created = await store.createPlaybook(payload)
      toast.add({ title: 'Playbook created', color: 'green' })
      await navigateTo(`/automation/ansible/playbooks/${created.id}`)
    } else {
      playbook.value = await store.updatePlaybook(String(route.params.id), payload)
      toast.add({ title: `Playbook saved (v${playbook.value.version})`, color: 'green' })
    }
  } catch {
    toast.add({ title: 'Failed to save playbook', color: 'red' })
  } finally {
    saving.value = false
  }
}

// ── Run from editor ──────────────────────────────────────────────────────
const showRun = ref(false)
const runAgentIds = ref<string[]>([])
const runExtraVars = ref('{}')
const agentOptions = ref<Array<{ label: string; value: string }>>([])
const running = ref(false)

async function openRun() {
  // Prefill from the playbook's project default agents — the project's
  // "inventory" — same convenience a real projects/<name>/inventory/ gives.
  const project = projectsStore.projects.find((p) => p.id === form.value.project_id)
  runAgentIds.value = project ? [...project.default_agent_ids] : []
  runExtraVars.value = '{}'
  if (!agentOptions.value.length) agentOptions.value = await serversStore.fetchAgentsForSelect()
  showRun.value = true
}

async function confirmRun() {
  if (!playbook.value) return
  if (!runAgentIds.value.length) {
    toast.add({ title: 'Select at least one runner server', color: 'red' })
    return
  }
  let extraVars: Record<string, unknown>
  try {
    extraVars = JSON.parse(runExtraVars.value || '{}')
  } catch {
    toast.add({ title: 'extra_vars must be valid JSON', color: 'red' })
    return
  }
  running.value = true
  try {
    const job = await store.executePlaybook(playbook.value.id, runAgentIds.value, extraVars)
    showRun.value = false
    toast.add({ title: 'Job created — requires approval', description: `Job "${job.name}" awaits approval in Jobs.`, color: 'green' })
  } catch {
    toast.add({ title: 'Failed to execute playbook', color: 'red' })
  } finally {
    running.value = false
  }
}
</script>

<template>
  <div class="max-w-5xl">
    <div class="flex items-center justify-between mb-4">
      <div class="flex items-center gap-3">
        <NuxtLink to="/automation/ansible/playbooks">
          <Button variant="ghost" size="sm">
            <ArrowLeft class="size-4" />
            Playbooks
          </Button>
        </NuxtLink>
        <h1 class="text-lg font-bold">{{ isNew ? 'New Playbook' : form.name }}</h1>
        <Badge v-if="playbook" color="gray" size="xs">v{{ playbook.version }}</Badge>
      </div>
      <div class="flex items-center gap-2">
        <Button v-if="!isNew && playbook" variant="outline" @click="openRun()">
          <Play class="size-4" />
          Run
        </Button>
        <Button v-if="canEdit" :loading="saving" @click="save">
          <Save class="size-4" />
          Save
        </Button>
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
      <FormField label="Name" required>
        <Input v-model="form.name" placeholder="Playbook name..." :disabled="!canEdit" />
      </FormField>
      <FormField label="Description">
        <Input v-model="form.description" placeholder="What this playbook does..." :disabled="!canEdit" />
      </FormField>
      <FormField label="Project" help="Default runner servers for this project prefill on Run">
        <Select v-model="form.project_id" :options="projectOptions" :disabled="!canEdit" />
      </FormField>
      <FormField label="Roles" help="Attached roles ship with the playbook under ./roles/ at run time">
        <MultiSelect v-model="form.role_ids" :options="roleOptions" placeholder="Attach Ansible roles..." />
      </FormField>
    </div>

    <FormField label="Content (YAML)" required>
      <PlaybookEditor v-model="form.content" tall />
    </FormField>

    <!-- Run dialog -->
    <Dialog v-model="showRun" title="Run Playbook">
      <template #body>
        <div class="space-y-4">
          <p class="text-sm text-muted-foreground">
            The playbook runs locally on each selected runner server (ansible-playbook --connection=local).
            Execution requires approval on the Jobs page before it starts.
          </p>
          <FormField label="Runner servers" required>
            <MultiSelect v-model="runAgentIds" :options="agentOptions" placeholder="Select Ansible runner servers..." />
          </FormField>
          <FormField label="Extra vars (JSON)">
            <textarea
              v-model="runExtraVars"
              rows="4"
              class="w-full rounded-lg border border-input bg-card px-2.5 py-1.5 text-sm font-mono"
            />
          </FormField>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showRun = false">Cancel</Button>
        <Button :loading="running" @click="confirmRun">Run</Button>
      </template>
    </Dialog>
  </div>
</template>
