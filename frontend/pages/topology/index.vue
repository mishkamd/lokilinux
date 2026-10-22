<script setup lang="ts">
import { Plus, Trash2 } from 'lucide-vue-next'

const store = useTopologyStore()
const { nodes, edges, loading } = storeToRefs(store)
const toast = useToast()
const { canEdit } = useCurrentUser()
const { format: fmtDateTime } = useDateTime()

const KINDS = ['HOST', 'SERVICE', 'APPLICATION', 'EXTERNAL']

// Node kind carries meaning, so it gets a real hue instead of a gray pill.
const KIND_COLOR: Record<string, string> = {
  HOST: 'blue',
  SERVICE: 'green',
  APPLICATION: 'orange',
  EXTERNAL: 'gray',
}

const nodeColumns = [
  { key: 'kind', label: 'Kind' },
  { key: 'name', label: 'Name' },
  { key: 'created_at', label: 'Created' },
]

const edgeColumns = [
  { key: 'from_node', label: 'Depends on' },
  { key: 'to_node', label: 'Target' },
  { key: 'actions', label: '', noSort: true },
]

const nodeOptions = computed(() =>
  nodes.value.map((n) => ({ label: `${n.name} (${n.kind})`, value: n.id })),
)

function nodeName(id: string): string {
  return nodes.value.find((n) => n.id === id)?.name ?? id
}

const showNodeDialog = ref(false)
const showEdgeDialog = ref(false)
const nodeForm = ref({ kind: 'SERVICE', name: '' })
const edgeForm = ref({ from: '', to: '' })
const submitting = ref(false)

function openNodeDialog() {
  nodeForm.value = { kind: 'SERVICE', name: '' }
  showNodeDialog.value = true
}

function openEdgeDialog() {
  edgeForm.value = { from: '', to: '' }
  showEdgeDialog.value = true
}

async function createNode() {
  if (!nodeForm.value.name.trim()) {
    toast.add({ title: 'Name is required', description: 'Give the node a name.', color: 'red' })
    return
  }
  submitting.value = true
  try {
    await store.createNode({ kind: nodeForm.value.kind, name: nodeForm.value.name.trim() })
    showNodeDialog.value = false
    toast.add({ title: 'Node created', color: 'green' })
  } catch {
    toast.add({ title: 'Error', description: 'Failed to create node', color: 'red' })
  } finally {
    submitting.value = false
  }
}

async function addEdge() {
  const { from, to } = edgeForm.value
  if (!from || !to) {
    toast.add({ title: 'Both nodes are required', description: 'Pick the source and the target.', color: 'red' })
    return
  }
  if (from === to) {
    toast.add({ title: 'A node cannot depend on itself', color: 'red' })
    return
  }
  submitting.value = true
  try {
    await store.addEdge(from, to)
    showEdgeDialog.value = false
    toast.add({ title: 'Dependency created', color: 'green' })
  } catch {
    toast.add({ title: 'Error', description: 'Failed to create dependency', color: 'red' })
  } finally {
    submitting.value = false
  }
}

const removingEdge = ref<{ from: string; to: string } | null>(null)
const removing = ref(false)

async function confirmRemoveEdge() {
  if (!removingEdge.value) return
  removing.value = true
  try {
    await store.removeEdge(removingEdge.value.from, removingEdge.value.to)
    removingEdge.value = null
  } catch {
    toast.add({ title: 'Error', description: 'Failed to remove dependency', color: 'red' })
  } finally {
    removing.value = false
  }
}

onMounted(() => store.fetchGraph())
</script>

<template>
  <div class="space-y-4">
    <PageHeader>
      <div class="flex items-center gap-3">
        <Badge color="gray">{{ nodes.length }} nodes</Badge>
        <Badge color="gray">{{ edges.length }} dependencies</Badge>
      </div>
      <div v-if="canEdit" class="flex items-center gap-2">
        <Button variant="outline" @click="openEdgeDialog">
          <Plus class="size-4" />
          New dependency
        </Button>
        <Button @click="openNodeDialog">
          <Plus class="size-4" />
          New node
        </Button>
      </div>
    </PageHeader>

    <div>
      <h2 class="section-title mb-2">Nodes</h2>
      <DataTable
        :rows="nodes"
        :columns="nodeColumns"
        :loading="loading"
        sortable
        :page-size="25"
        empty-title="No nodes"
        empty-description="Nodes are the services and hosts the dependency graph is built from."
        caption="Topology nodes"
        preferences-key="topology-nodes"
      >
        <template #kind-data="{ row }">
          <Badge :color="KIND_COLOR[String(row.kind)] ?? 'gray'" size="xs">{{ row.kind }}</Badge>
        </template>
        <template #name-data="{ row }">
          <span class="font-mono text-xs">{{ row.name }}</span>
        </template>
        <template #created_at-data="{ row }">
          <span class="font-mono text-xs text-muted-foreground">{{ fmtDateTime(String(row.created_at)) }}</span>
        </template>
      </DataTable>
    </div>

    <div>
      <h2 class="section-title mb-2">Dependencies</h2>
      <DataTable
        :rows="edges"
        :columns="edgeColumns"
        :loading="loading"
        :page-size="25"
        empty-title="No dependencies"
        empty-description="Dependencies tell the correlator which service failures belong together."
        caption="Topology dependencies"
        preferences-key="topology-edges"
      >
        <template #from_node-data="{ row }">
          <span class="font-mono text-xs">{{ nodeName(String(row.from_node)) }}</span>
        </template>
        <template #to_node-data="{ row }">
          <span class="font-mono text-xs">{{ nodeName(String(row.to_node)) }}</span>
        </template>
        <template #actions-data="{ row }">
          <div v-if="canEdit" class="flex items-center justify-end gap-1">
            <Tooltip text="Remove dependency">
              <Button
                size="xs"
                variant="ghost"
                aria-label="Remove dependency"
                @click="removingEdge = { from: String(row.from_node), to: String(row.to_node) }"
              >
                <Trash2 class="size-3.5" />
              </Button>
            </Tooltip>
          </div>
        </template>
      </DataTable>
    </div>

    <Dialog v-model="showNodeDialog" title="New node">
      <template #body>
        <div class="space-y-3">
          <FormField label="Kind">
            <Select v-model="nodeForm.kind" :options="KINDS" />
          </FormField>
          <FormField label="Name" required>
            <Input v-model="nodeForm.name" placeholder="e.g. checkout, db-1" @keyup.enter="createNode" />
          </FormField>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showNodeDialog = false">Cancel</Button>
        <Button :loading="submitting" @click="createNode">Create node</Button>
      </template>
    </Dialog>

    <Dialog v-model="showEdgeDialog" title="New dependency">
      <template #body>
        <div class="space-y-3">
          <FormField label="Depends on" required>
            <Select v-model="edgeForm.from" :options="nodeOptions" placeholder="Source node..." />
          </FormField>
          <FormField label="Target" required>
            <Select v-model="edgeForm.to" :options="nodeOptions" placeholder="Target node..." />
          </FormField>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showEdgeDialog = false">Cancel</Button>
        <Button :loading="submitting" :disabled="!nodeOptions.length" @click="addEdge">Create dependency</Button>
      </template>
    </Dialog>

    <ConfirmDeleteDialog
      :model-value="!!removingEdge"
      :entity-name="removingEdge ? `${nodeName(removingEdge.from)} → ${nodeName(removingEdge.to)}` : ''"
      :loading="removing"
      title="Remove dependency"
      confirm-label="Remove"
      @update:model-value="removingEdge = null"
      @confirm="confirmRemoveEdge"
    />
  </div>
</template>
