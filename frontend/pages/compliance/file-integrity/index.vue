<script setup lang="ts">
import { RefreshCw } from 'lucide-vue-next'
import type { FileChangeKind } from '~/stores/compliance'

const store = useComplianceStore()
const serversStore = useServersStore()
const {
  fileHashes, fileHashesLoading, fileHashPathPrefix,
  fileChanges, fileChangesTotal, fileChangesLoading, fileChangesNextCursor, fileChangeFilters,
} = storeToRefs(store)

const agentOptions = ref<{ label: string; value: string }[]>([])
const selectedAgentId = ref('')

onMounted(async () => {
  agentOptions.value = await serversStore.fetchAgentsForSelect()
  if (agentOptions.value.length > 0) {
    selectedAgentId.value = agentOptions.value[0].value
    await store.fetchFileHashes(selectedAgentId.value)
  }
  await store.fetchFileChanges()
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
]

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
        <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
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
        </div>

        <DataTable :rows="fileHashes" :columns="hashColumns" :loading="fileHashesLoading">
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
            <span class="font-mono text-xs">{{ new Date(String(row.updated_at)).toLocaleString() }}</span>
          </template>
        </DataTable>
      </template>

      <template #history>
        <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div class="flex flex-wrap items-center gap-3">
            <Select v-model="fileChangeFilters.change_kind" :options="['', ...CHANGE_KINDS]" placeholder="Change type"
                    class="w-48" @change="store.fetchFileChanges()" />
            <Button variant="outline" @click="store.fetchFileChanges()">
              <RefreshCw class="size-4" /> Refresh
            </Button>
          </div>
          <Badge color="gray">{{ fileChangesTotal }} changes</Badge>
        </div>

        <DataTable :rows="fileChanges" :columns="changeColumns" :loading="fileChangesLoading">
          <template #time-data="{ row }">
            <span class="font-mono text-xs">{{ new Date(String(row.time)).toLocaleString() }}</span>
          </template>
          <template #path-data="{ row }">
            <span class="font-mono text-xs">{{ row.path }}</span>
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
    </AppTabs>
  </div>
</template>
