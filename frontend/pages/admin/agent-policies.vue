<script setup lang="ts">
import { Plus, FileCode2, Rocket, History } from 'lucide-vue-next'

definePageMeta({ layout: 'default' })

const api = useApi()
const toast = useToast()

interface PolicyRow {
  id: string
  name: string
  description: string
  status: string
  current_version: number | null
}

const { data, refresh, pending } = await useAsyncData('agent-policies', () =>
  api.get<{ items: PolicyRow[]; total: number }>('/agent-policies?limit=200'),
)

const columns = [
  { key: 'name', label: 'Name' },
  { key: 'status', label: 'Status' },
  { key: 'current_version', label: 'Version' },
  { key: 'actions', label: '', noSort: true },
]

const searchQuery = ref('')
const filtered = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  const items = data.value?.items ?? []
  if (!q) return items
  return items.filter((p) =>
    [p.name, p.description].some((v) => v != null && String(v).toLowerCase().includes(q)),
  )
})

const STATUS_COLORS: Record<string, string> = { draft: 'gray', active: 'green', archived: 'gray' }

// ── create/edit modal ─────────────────────────────────────────────────────────
const showEditor = ref(false)
const editing = ref<PolicyRow | null>(null)
const form = reactive({ name: '', description: '', yaml_text: '' })
const saving = ref(false)
const yamlError = ref('')

const SKELETON = `apiVersion: lokilinux.io/v1
kind: AgentPolicy
metadata:
  name: my-policy
spec:
  collectors:
    sshd: {enabled: true}
    users: {enabled: true}
  heartbeat:
    interval_seconds: 60
  health:
    collect_interval_seconds: 30
`

function openCreate() {
  editing.value = null
  form.name = ''
  form.description = ''
  form.yaml_text = SKELETON
  yamlError.value = ''
  showEditor.value = true
}

async function openEdit(p: PolicyRow) {
  editing.value = p
  form.name = p.name
  form.description = p.description
  yamlError.value = ''
  try {
    const detail = await api.get<{ payload?: Record<string, unknown> }>(`/agent-policies/${p.id}`)
    form.yaml_text = detail?.payload ? yamlStringify(detail.payload) : SKELETON
  } catch {
    form.yaml_text = SKELETON
  }
  showEditor.value = true
}

function yamlStringify(payload: Record<string, unknown>): string {
  // client-side only: convert stored JSONB payload to readable YAML-ish form
  try {
    // @ts-expect-error js-yaml ships with nuxt deps transitive
    return window.jsyaml ? window.jsyaml.dump(payload) : JSON.stringify(payload, null, 2)
  } catch {
    return JSON.stringify(payload, null, 2)
  }
}

async function save() {
  saving.value = true
  yamlError.value = ''
  try {
    if (editing.value) {
      await api.put<void>(`/agent-policies/${editing.value.id}`, {
        description: form.description,
        yaml_text: form.yaml_text,
      })
      toast.add({ title: 'Draft updated', color: 'green' })
    } else {
      await api.post('/agent-policies', { name: form.name, description: form.description, yaml_text: form.yaml_text })
      toast.add({ title: 'Policy created', color: 'green' })
    }
    showEditor.value = false
    await refresh()
  } catch (e: unknown) {
    const detail = (e as { data?: { detail?: string } })?.data?.detail
    yamlError.value = detail ?? 'Save failed'
  } finally {
    saving.value = false
  }
}

// ── publish ───────────────────────────────────────────────────────────────────
const publishing = ref<string | null>(null)
async function publish(p: PolicyRow) {
  publishing.value = p.id
  try {
    const versions = await api.get<{ items: { id: string; version: number; status: string }[] }>(`/agent-policies/${p.id}/versions`)
    const draft = (versions?.items ?? []).find((v: { status: string }) => v.status === 'draft') ?? versions?.items?.[0]
    if (!draft) throw new Error('no version')
    await api.post(`/agent-policies/${p.id}/publish`, { version_id: draft.id })
    toast.add({ title: `Published v${draft.version} (signed)`, color: 'green' })
    await refresh()
  } catch (e: unknown) {
    toast.add({ title: 'Publish failed', description: errMsg(e), color: 'red' })
  } finally {
    publishing.value = null
  }
}

function errMsg(e: unknown): string {
  return (e as { data?: { detail?: string } })?.data?.detail ?? 'unexpected error'
}

// ── deploy modal ──────────────────────────────────────────────────────────────
const showDeploy = ref(false)
const deployTarget = ref<PolicyRow | null>(null)
const deployForm = reactive({ agent_id: '' })
const deploying = ref(false)

function openDeploy(p: PolicyRow) {
  deployTarget.value = p
  deployForm.agent_id = ''
  showDeploy.value = true
}

async function doDeploy() {
  if (!deployTarget.value || !deployForm.agent_id.trim()) return
  deploying.value = true
  try {
    const res = await api.post<{ deployments: unknown[]; count: number }>(`/agent-policies/${deployTarget.value.id}/deploy`, {
      scope_type: 'AGENT',
      scope_ref: deployForm.agent_id.trim(),
    })
    toast.add({
      title: `Deployed to ${res?.count ?? 0} agent(s)`,
      description: 'Agents apply on their next heartbeat; drift panel shows sync status.',
      color: 'green',
    })
    showDeploy.value = false
  } catch (e: unknown) {
    toast.add({ title: 'Deploy failed', description: errMsg(e), color: 'red' })
  } finally {
    deploying.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="Agent Policies" description="Desired-state configuration for the fleet — signed, versioned, applied autonomously.">
      <template #actions>
        <Button @click="openCreate">
          <Plus class="size-4" />
          New Policy
        </Button>
      </template>
    </PageHeader>

    <DataTable
      :rows="filtered"
      :columns="columns"
      :loading="pending"
      sortable
      :page-size="25"
      empty-title="No policies"
      :empty-description="searchQuery ? `Nothing matches “${searchQuery}”.` : 'Create a policy or start from a seeded template.'"
    >
      <template #toolbar>
        <Input v-model="searchQuery" placeholder="Search policies..." class="w-full sm:w-64" />
      </template>
      <template #name-data="{ row }">
        <button class="font-medium hover:underline" @click="openEdit(row as PolicyRow)">{{ row.name }}</button>
        <p v-if="row.description" class="text-xs text-muted-foreground">{{ row.description }}</p>
      </template>
      <template #status-data="{ row }">
        <Badge :color="STATUS_COLORS[String(row.status)] ?? 'gray'" size="xs">{{ row.status }}</Badge>
      </template>
      <template #current_version-data="{ row }">
        <span class="font-mono text-xs tabular-nums">{{ row.current_version ? `v${row.current_version}` : '—' }}</span>
      </template>
      <template #actions-data="{ row }">
        <div class="flex items-center justify-end gap-1">
          <Tooltip text="Edit draft">
            <Button size="xs" variant="ghost" aria-label="Edit policy" @click="openEdit(row as PolicyRow)">
              <FileCode2 class="size-3.5" />
            </Button>
          </Tooltip>
          <Tooltip v-if="row.status === 'draft'" text="Publish (sign + freeze)">
            <Button size="xs" variant="ghost" aria-label="Publish policy" :loading="publishing === row.id" @click="publish(row as PolicyRow)">
              <History class="size-3.5" />
            </Button>
          </Tooltip>
          <Tooltip v-if="row.status === 'active'" text="Deploy to agent">
            <Button size="xs" variant="ghost" aria-label="Deploy policy" @click="openDeploy(row as PolicyRow)">
              <Rocket class="size-3.5" />
            </Button>
          </Tooltip>
        </div>
      </template>
    </DataTable>

    <Dialog v-model="showEditor" :title="editing ? `Edit ${editing.name}` : 'New Policy'" size="xl">
      <template #body>
        <div class="space-y-3">
          <FormField label="Name" required>
            <Input v-model="form.name" :disabled="!!editing" placeholder="production-linux" />
          </FormField>
          <FormField label="Description">
            <Input v-model="form.description" placeholder="What this policy enforces..." />
          </FormField>
          <FormField label="Policy YAML" help="Unknown fields are rejected; unlisted collectors are disabled (deny-by-default).">
            <Textarea v-model="form.yaml_text" :rows="18" class="font-mono text-xs" />
          </FormField>
          <p v-if="yamlError" class="text-xs text-destructive">{{ yamlError }}</p>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showEditor = false">Cancel</Button>
        <Button :loading="saving" @click="save">{{ editing ? 'Save draft' : 'Create' }}</Button>
      </template>
    </Dialog>

    <Dialog v-model="showDeploy" :title="`Deploy ${deployTarget?.name ?? ''}`" size="sm">
      <template #body>
        <div class="space-y-3">
          <FormField label="Agent ID (UUID)" required help="Deployments fan out per-agent; the agent applies on its next heartbeat.">
            <Input v-model="deployForm.agent_id" placeholder="973717bf-2d10-4b5f-a97f-1ab13beffd14" />
          </FormField>
          <p class="text-xs text-muted-foreground">
            The document is verified (ed25519 + hash + version monotonicity) before apply; a failed health check keeps the last-good policy active.
          </p>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showDeploy = false">Cancel</Button>
        <Button :loading="deploying" @click="doDeploy">Deploy</Button>
      </template>
    </Dialog>
  </div>
</template>
