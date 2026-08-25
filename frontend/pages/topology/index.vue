<script setup lang="ts">
// v1: simple list/form editor (node select + depends-on target), no SVG
// graph — the plan explicitly defers the visual graph to a later pass.
import { Plus, Trash2 } from 'lucide-vue-next'

const store = useTopologyStore()
const { nodes, edges, loading } = storeToRefs(store)
const toast = useToast()

const KINDS = ['HOST', 'SERVICE', 'APPLICATION', 'EXTERNAL']

const newNode = ref({ kind: 'SERVICE', name: '' })
const creatingNode = ref(false)

const newEdge = ref({ from: '', to: '' })
const creatingEdge = ref(false)
const removingEdge = ref<string | null>(null)

const nodeOptions = computed(() => nodes.value.map((n) => ({ label: `${n.name} (${n.kind})`, value: n.id })))

function nodeName(id: string): string {
  return nodes.value.find((n) => n.id === id)?.name ?? id
}

async function createNode() {
  if (!newNode.value.name.trim()) return
  creatingNode.value = true
  try {
    await store.createNode({ kind: newNode.value.kind, name: newNode.value.name.trim() })
    newNode.value.name = ''
    toast.add({ title: 'Node created', color: 'green' })
  } catch {
    toast.add({ title: 'Error', description: 'Failed to create node', color: 'red' })
  } finally {
    creatingNode.value = false
  }
}

async function addEdge() {
  if (!newEdge.value.from || !newEdge.value.to || newEdge.value.from === newEdge.value.to) return
  creatingEdge.value = true
  try {
    await store.addEdge(newEdge.value.from, newEdge.value.to)
    newEdge.value = { from: '', to: '' }
    toast.add({ title: 'Edge created', color: 'green' })
  } catch {
    toast.add({ title: 'Error', description: 'Failed to create edge', color: 'red' })
  } finally {
    creatingEdge.value = false
  }
}

async function removeEdge(fromNode: string, toNode: string) {
  removingEdge.value = `${fromNode}:${toNode}`
  try {
    await store.removeEdge(fromNode, toNode)
  } catch {
    toast.add({ title: 'Error', description: 'Failed to remove edge', color: 'red' })
  } finally {
    removingEdge.value = null
  }
}

onMounted(() => store.fetchGraph())
</script>

<template>
  <div class="space-y-6">
    <div>
      <h2 class="text-sm font-medium mb-2">Nodes ({{ nodes.length }})</h2>
      <div class="flex flex-wrap items-end gap-2 mb-3">
        <FormField label="Kind">
          <Select v-model="newNode.kind" :options="KINDS" class="w-36" />
        </FormField>
        <FormField label="Name">
          <Input v-model="newNode.name" placeholder="e.g. checkout, db-1..." class="w-56" @keyup.enter="createNode" />
        </FormField>
        <Button :loading="creatingNode" @click="createNode">
          <Plus class="size-4" />
          Add node
        </Button>
      </div>
      <p v-if="loading" class="text-sm text-muted-foreground">Loading…</p>
      <div v-else class="flex flex-wrap gap-2">
        <div v-for="n in nodes" :key="n.id" class="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-xs">
          <Badge color="gray" size="xs">{{ n.kind }}</Badge>
          <span class="font-mono">{{ n.name }}</span>
        </div>
        <p v-if="!nodes.length" class="text-sm text-muted-foreground">No nodes yet.</p>
      </div>
    </div>

    <Separator />

    <div>
      <h2 class="text-sm font-medium mb-2">Dependencies ({{ edges.length }})</h2>
      <div class="flex flex-wrap items-end gap-2 mb-3">
        <FormField label="Depends on">
          <Select v-model="newEdge.from" :options="nodeOptions" placeholder="From node..." class="w-56" />
        </FormField>
        <FormField label="Target">
          <Select v-model="newEdge.to" :options="nodeOptions" placeholder="To node..." class="w-56" />
        </FormField>
        <Button :loading="creatingEdge" @click="addEdge">
          <Plus class="size-4" />
          Add edge
        </Button>
      </div>
      <div class="space-y-1">
        <div
          v-for="e in edges"
          :key="`${e.from_node}:${e.to_node}`"
          class="flex items-center justify-between gap-2 rounded-lg border border-border px-3 py-2 text-sm"
        >
          <span class="font-mono">{{ nodeName(e.from_node) }} → {{ nodeName(e.to_node) }}</span>
          <Button
            size="xs"
            variant="ghost"
            class="text-muted-foreground"
            :loading="removingEdge === `${e.from_node}:${e.to_node}`"
            @click="removeEdge(e.from_node, e.to_node)"
          >
            <Trash2 class="size-3.5" />
          </Button>
        </div>
        <p v-if="!edges.length" class="text-sm text-muted-foreground">No dependencies yet.</p>
      </div>
    </div>
  </div>
</template>
