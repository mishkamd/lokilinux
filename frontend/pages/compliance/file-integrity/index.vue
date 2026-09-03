<script setup lang="ts">
import { SEVERITY_COLORS } from '~/utils/complianceColors'
import { RefreshCw, Plus } from 'lucide-vue-next'
import type { FileChangeKind, FIMScope } from '~/stores/compliance'

const store = useComplianceStore()
const serversStore = useServersStore()
const { format: fmtDateTime } = useDateTime()
const { canEdit } = useCurrentUser()
const toast = useToast()
const {
  fileHashes, fileHashesLoading, fileHashPathPrefix,
  fileChanges, fileChangesTotal, fileChangesLoading, fileChangesNextCursor, fileChangeFilters,
  fileChangePathDetail, fileChangePathDetailLoading,
  fimScopes, fimScopesLoading,
} = storeToRefs(store)

const showPathDetail = ref(false)
async function openPathDetail(path: string) {
  showPathDetail.value = true
  await store.fetchFileChangesByPath(path)
}

const agentOptions = ref<{ label: string; value: string }[]>([])
const selectedAgentId = ref('')

const route = useRoute()

onMounted(async () => {
  agentOptions.value = await serversStore.fetchAgentsForSelect()
  if (agentOptions.value.length > 0) {
    selectedAgentId.value = agentOptions.value[0].value
    await store.fetchFileHashes(selectedAgentId.value)
  }
  await store.fetchFileChanges()
  await store.fetchFIMScopes()

  const pathParam = route.query.path
  if (typeof pathParam === 'string' && pathParam) {
    await openPathDetail(pathParam)
  }
})

async function onAgentChange() {
  if (selectedAgentId.value) await store.fetchFileHashes(selectedAgentId.value)
}

const CHANGE_KIND_COLORS: Record<FileChangeKind, string> = {
  CREATED: 'green', MODIFIED: 'amber', DELETED: 'red', PERMISSION_CHANGED: 'amber', OWNER_CHANGED: 'amber',
}
const CHANGE_KINDS: FileChangeKind[] = ['CREATED', 'MODIFIED', 'DELETED', 'PERMISSION_CHANGED', 'OWNER_CHANGED']

function formatModeChange(row: { old_mode: number | null; new_mode: number | null }) {
  if (row.old_mode === null && row.new_mode === null) return null
  const old = row.old_mode !== null ? row.old_mode.toString(8) : '—'
  const next = row.new_mode !== null ? row.new_mode.toString(8) : '—'
  return old === next ? null : `${old} → ${next}`
}
function formatOwnerChange(row: { old_uid: number | null; new_uid: number | null; old_gid: number | null; new_gid: number | null }) {
  if (row.old_uid === row.new_uid && row.old_gid === row.new_gid) return null
  const old = `${row.old_uid ?? '—'}:${row.old_gid ?? '—'}`
  const next = `${row.new_uid ?? '—'}:${row.new_gid ?? '—'}`
  return `${old} → ${next}`
}

const tabs = [
  { label: 'Current State', slot: 'current' },
  { label: 'Change History', slot: 'history' },
  { label: 'Watched paths', slot: 'scope' },
]

// ── Watched paths tab: global default + per-server overrides ──────────────

function linesToArray(text: string): string[] {
  return text.split('\n').map((s) => s.trim()).filter(Boolean)
}
function arrayToLines(arr: string[]): string {
  return arr.join('\n')
}

const globalWatchText = ref('')
const globalIgnoreText = ref('')
const savingGlobal = ref(false)

watch(() => fimScopes.value?.global_scope, (scope) => {
  if (!scope) return
  globalWatchText.value = arrayToLines(scope.watch_paths)
  globalIgnoreText.value = arrayToLines(scope.ignore_paths)
}, { immediate: true })

function errorDetail(err: unknown, fallback: string): string {
  return (err as { data?: { detail?: string } })?.data?.detail ?? fallback
}

async function onSaveGlobal() {
  savingGlobal.value = true
  try {
    await store.updateGlobalFIMScope(linesToArray(globalWatchText.value), linesToArray(globalIgnoreText.value))
    toast.add({ title: 'Global watch scope saved' })
  } catch (err) {
    toast.add({ title: errorDetail(err, 'Save failed') })
  } finally {
    savingGlobal.value = false
  }
}

const overriddenAgentIds = computed(() => new Set((fimScopes.value?.agents ?? []).map((a) => a.agent_id)))
const availableAgentOptions = computed(() => agentOptions.value.filter((o) => !overriddenAgentIds.value.has(o.value)))

const showAgentEdit = ref(false)
const agentEditTarget = ref('')
const agentEditIsNew = ref(false)
const agentEditWatchText = ref('')
const agentEditIgnoreText = ref('')
const savingAgentScope = ref(false)

function openAgentCreate() {
  agentEditTarget.value = ''
  agentEditIsNew.value = true
  agentEditWatchText.value = ''
  agentEditIgnoreText.value = ''
  showAgentEdit.value = true
}
function openAgentEditRow(scope: FIMScope) {
  agentEditTarget.value = scope.agent_id ?? ''
  agentEditIsNew.value = false
  agentEditWatchText.value = arrayToLines(scope.watch_paths)
  agentEditIgnoreText.value = arrayToLines(scope.ignore_paths)
  showAgentEdit.value = true
}

async function onSaveAgentScope() {
  if (!agentEditTarget.value) return
  savingAgentScope.value = true
  try {
    await store.updateAgentFIMScope(
      agentEditTarget.value, linesToArray(agentEditWatchText.value), linesToArray(agentEditIgnoreText.value),
    )
    showAgentEdit.value = false
    toast.add({ title: 'Per-server override saved' })
  } catch (err) {
    toast.add({ title: errorDetail(err, 'Save failed') })
  } finally {
    savingAgentScope.value = false
  }
}

async function onResetAgentScope(agentId: string) {
  if (!confirm('Reset this server to the global default?')) return
  try {
    await store.deleteAgentFIMScope(agentId)
    toast.add({ title: 'Reverted to global default' })
  } catch (err) {
    toast.add({ title: errorDetail(err, 'Reset failed') })
  }
}

function agentLabel(scope: FIMScope): string {
  return scope.hostname || scope.agent_id || '—'
}

const hashColumns = [
  { key: 'path', label: 'Path' },
  { key: 'hash', label: 'Hash' },
  { key: 'size_bytes', label: 'Size' },
  { key: 'updated_at', label: 'Last seen' },
]

const changeColumns = [
  { key: 'time', label: 'Time' },
  { key: 'agent_id', label: 'Server' },
  { key: 'path', label: 'Path' },
  { key: 'change_kind', label: 'Change' },
  { key: 'details', label: 'Details' },
]
</script>

<template>
  <div>
    <AppTabs :items="tabs">
      <template #current>
        <PageHeader>
          <div class="flex flex-wrap items-center gap-3">
            <Select v-model="selectedAgentId" :options="agentOptions" placeholder="Server" class="w-64"
                    @change="onAgentChange" />
            <Input v-model="fileHashPathPrefix" placeholder="Filter by path prefix (e.g. /etc/ssh)" class="w-72"
                   @keyup.enter="onAgentChange" />
            <Button variant="outline" @click="onAgentChange">
              <RefreshCw class="size-4" /> Refresh
            </Button>
          </div>
          <Badge color="gray">{{ fileHashes.length }} watched files</Badge>
        </PageHeader>

        <DataTable
          :rows="fileHashes"
          :columns="hashColumns"
          :loading="fileHashesLoading"
          sortable
          :page-size="25"
          empty-title="No watched files"
          :empty-description="fileHashPathPrefix ? 'No watched files match the path prefix.' : 'Files appear here after agents report their inventory.'"
        >
          <template #path-data="{ row }">
            <span class="font-mono text-xs">{{ row.path }}</span>
          </template>
          <template #hash-data="{ row }">
            <span class="font-mono text-xs text-muted-foreground">{{ String(row.hash).slice(0, 16) }}…</span>
          </template>
          <template #size_bytes-data="{ row }">
            <span class="font-mono text-xs">{{ row.size_bytes ?? '—' }}</span>
          </template>
          <template #updated_at-data="{ row }">
            <span class="font-mono text-xs">{{ fmtDateTime(String(row.updated_at)) }}</span>
          </template>
        </DataTable>
      </template>

      <template #history>
        <PageHeader>
          <div class="flex flex-wrap items-center gap-3">
            <Select v-model="fileChangeFilters.change_kind" :options="['', ...CHANGE_KINDS]" placeholder="Change type"
                    class="w-48" @change="store.fetchFileChanges()" />
            <Button variant="outline" @click="store.fetchFileChanges()">
              <RefreshCw class="size-4" /> Refresh
            </Button>
          </div>
          <Badge color="gray">{{ fileChangesTotal }} changes</Badge>
        </PageHeader>

        <DataTable
          :rows="fileChanges"
          :columns="changeColumns"
          :loading="fileChangesLoading"
          sortable
          :page-size="25"
          empty-title="No changes recorded"
        >
          <template #time-data="{ row }">
            <span class="font-mono text-xs">{{ fmtDateTime(String(row.time)) }}</span>
          </template>
          <template #agent_id-data="{ row }">
            <span class="font-mono text-xs">{{ row.hostname || row.agent_id }}</span>
          </template>
          <template #path-data="{ row }">
            <button class="font-mono text-xs text-primary hover:underline text-left" @click="openPathDetail(String(row.path))">
              {{ row.path }}
            </button>
          </template>
          <template #change_kind-data="{ row }">
            <Badge :color="CHANGE_KIND_COLORS[row.change_kind as FileChangeKind] ?? 'gray'" size="xs">
              {{ row.change_kind }}
            </Badge>
          </template>
          <template #details-data="{ row }">
            <span v-if="row.change_kind === 'PERMISSION_CHANGED'" class="font-mono text-xs text-muted-foreground">
              {{ formatModeChange(row) }}
            </span>
            <span v-else-if="row.change_kind === 'OWNER_CHANGED'" class="font-mono text-xs text-muted-foreground">
              {{ formatOwnerChange(row) }}
            </span>
            <span v-else class="text-muted-foreground">—</span>
          </template>
        </DataTable>

        <div v-if="fileChangesNextCursor" class="mt-4 flex justify-center">
          <Button variant="outline" @click="store.fetchFileChanges(fileChangesNextCursor!)">
            Load more
          </Button>
        </div>
      </template>

      <template #scope>
        <PageHeader>
          <p class="text-sm text-muted-foreground">
            What the agent scans, fleet-wide by default and per server when overridden.
            Applies to agents ≥ 0.41.0 — older agents keep scanning <code>/etc</code>.
          </p>
          <Button variant="outline" @click="store.fetchFIMScopes()">
            <RefreshCw class="size-4" /> Refresh
          </Button>
        </PageHeader>

        <Skeleton v-if="fimScopesLoading && !fimScopes" class="h-40 w-full" />
        <template v-else-if="fimScopes">
          <Card class="mb-4">
            <template #header>
              <p class="label-caps">Global default</p>
            </template>
            <div class="grid gap-4 sm:grid-cols-2">
              <div>
                <p class="text-xs text-muted-foreground mb-1">Watched paths (one per line)</p>
                <Textarea v-model="globalWatchText" :disabled="!canEdit" :rows="5" placeholder="/etc" />
              </div>
              <div>
                <p class="text-xs text-muted-foreground mb-1">Ignore patterns (one per line)</p>
                <Textarea v-model="globalIgnoreText" :disabled="!canEdit" :rows="5" placeholder="/etc/mtab" />
              </div>
            </div>
            <div v-if="canEdit" class="mt-3 flex justify-end">
              <Button :disabled="!globalWatchText.trim()" :loading="savingGlobal" @click="onSaveGlobal">Save global default</Button>
            </div>
          </Card>

          <Card>
            <template #header>
              <div class="flex items-center justify-between">
                <p class="label-caps">Per-server overrides</p>
                <Button v-if="canEdit" size="sm" variant="outline" @click="openAgentCreate">
                  <Plus class="size-4" /> Add override
                </Button>
              </div>
            </template>
            <p v-if="fimScopes.agents.length === 0" class="text-sm text-muted-foreground">
              Every server uses the global default.
            </p>
            <ul v-else class="divide-y divide-border">
              <li v-for="s in fimScopes.agents" :key="s.agent_id ?? ''" class="py-2.5 flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <p class="text-sm font-medium truncate">{{ agentLabel(s) }}</p>
                  <p class="text-xs text-muted-foreground font-mono truncate">{{ s.watch_paths.join(', ') }}</p>
                  <p v-if="s.ignore_paths.length" class="text-xs text-muted-foreground font-mono truncate">
                    ignore: {{ s.ignore_paths.join(', ') }}
                  </p>
                </div>
                <div v-if="canEdit" class="flex shrink-0 gap-2">
                  <Button size="sm" variant="outline" @click="openAgentEditRow(s)">Edit</Button>
                  <Button size="sm" variant="ghost" @click="onResetAgentScope(s.agent_id!)">Reset</Button>
                </div>
              </li>
            </ul>
          </Card>
        </template>
      </template>
    </AppTabs>

    <Dialog v-model="showAgentEdit" :title="agentEditIsNew ? 'Add per-server override' : 'Edit per-server override'">
      <template #body>
        <div class="space-y-4">
          <FormField v-if="agentEditIsNew" label="Server">
            <Select v-model="agentEditTarget" :options="availableAgentOptions" placeholder="Select a server" />
          </FormField>
          <FormField label="Watched paths (one per line)">
            <Textarea v-model="agentEditWatchText" :rows="5" placeholder="/etc" />
          </FormField>
          <FormField label="Ignore patterns (one per line)">
            <Textarea v-model="agentEditIgnoreText" :rows="4" placeholder="/etc/mtab" />
          </FormField>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showAgentEdit = false">Cancel</Button>
        <Button :disabled="!agentEditTarget || !agentEditWatchText.trim()" :loading="savingAgentScope" @click="onSaveAgentScope">Save</Button>
      </template>
    </Dialog>

    <Dialog v-model="showPathDetail" :title="fileChangePathDetail?.path ?? 'File detail'">
      <template #body>
        <Skeleton v-if="fileChangePathDetailLoading" class="h-48 w-full" />
        <div v-else-if="fileChangePathDetail" class="space-y-4">
          <div>
            <p class="label-caps mb-1">Servers</p>
            <p class="text-sm text-muted-foreground">{{ fileChangePathDetail.servers.length }} server(s) with a recorded change to this path</p>
          </div>

          <div>
            <p class="label-caps mb-1">Related rules</p>
            <p v-if="fileChangePathDetail.related_rules.length === 0" class="text-sm text-muted-foreground">
              No compliance rules depend on this exact path.
            </p>
            <div v-else class="flex flex-wrap gap-1">
              <NuxtLink
                v-for="r in fileChangePathDetail.related_rules" :key="r.rule_id"
                :to="`/compliance/rules/${r.rule_id}`" class="text-xs"
              >
                <Badge color="gray" size="xs">{{ r.rule_key }}</Badge>
              </NuxtLink>
            </div>
          </div>

          <div>
            <p class="label-caps mb-1">Related open drift</p>
            <p v-if="fileChangePathDetail.related_drift.length === 0" class="text-sm text-muted-foreground">
              No open drift on the domains this file feeds.
            </p>
            <ul v-else class="divide-y divide-border">
              <li v-for="d in fileChangePathDetail.related_drift" :key="String(d.id)" class="py-1.5 flex items-center justify-between gap-2">
                <span class="text-xs truncate">{{ d.summary }}</span>
                <Badge :color="SEVERITY_COLORS[String(d.severity)] ?? 'gray'" size="xs">{{ d.severity }}</Badge>
              </li>
            </ul>
          </div>

          <div>
            <p class="label-caps mb-1">Timeline</p>
            <ul class="divide-y divide-border">
              <li v-for="(c, i) in fileChangePathDetail.timeline" :key="i" class="py-1.5 flex items-center justify-between gap-2 text-xs">
                <span class="font-mono text-muted-foreground">{{ fmtDateTime(c.time) }} · {{ c.hostname || c.agent_id.slice(0, 8) + '…' }}</span>
                <Badge :color="CHANGE_KIND_COLORS[c.change_kind] ?? 'gray'" size="xs">{{ c.change_kind }}</Badge>
              </li>
            </ul>
            <p v-if="fileChangePathDetail.timeline.length === 0" class="text-sm text-muted-foreground">No changes recorded.</p>
          </div>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showPathDetail = false">Close</Button>
      </template>
    </Dialog>
  </div>
</template>
