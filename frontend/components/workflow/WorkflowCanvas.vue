<script setup lang="ts">
import { VueFlow, useVueFlow, MarkerType, ConnectionMode } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { MiniMap } from '@vue-flow/minimap'
import { Copy, Ban, Unlink, Trash2, CheckCircle2, XCircle, RefreshCw } from 'lucide-vue-next'
import type { Node as FlowNode, Edge as FlowEdge, Connection, NodeMouseEvent, EdgeMouseEvent } from '@vue-flow/core'
import WorkflowNodeBase from '~/components/workflow/nodes/WorkflowNodeBase.vue'
import type { ContextMenuEntry } from '~/components/ui/ContextMenu.vue'
import { computeAutoLayout } from '~/utils/workflow/layout'
import type { WorkflowNode, WorkflowEdge, WorkflowStepRun, WorkflowHandleSide } from '~/types/workflow'

// Only the functional stylesheet — never @vue-flow/core/dist/theme-default.css.
// A custom node is just a Vue SFC bound through a slot (confirmed against
// Vue Flow's own docs); nothing about how a node LOOKS comes from the
// library. DESIGN.md owns 100% of the visible surface here.
import '@vue-flow/core/dist/style.css'
import '@vue-flow/minimap/dist/style.css'

const props = defineProps<{
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  selectedNodeId?: string | null
  selectedEdgeId?: string | null
  stepRunByNodeId?: Record<string, WorkflowStepRun>
}>()

const emit = defineEmits<{
  'select-node': [string | null]
  'select-edge': [string | null]
  'move-node': [{ id: string; position: { x: number; y: number } }]
  'drop-node': [{ type: string; position: { x: number; y: number } }]
  'delete-node': [string]
  'duplicate-node': [string]
  'disconnect-node': [string]
  'toggle-disable-node': [string]
  'connect-nodes': [{ from: string; to: string; sourceSide?: WorkflowHandleSide; targetSide?: WorkflowHandleSide }]
  'delete-edge': [WorkflowEdge]
  'set-edge-on': [{ edge: WorkflowEdge; on: WorkflowEdge['on'] }]
  undo: []
  redo: []
}>()

const EDGE_COLOR: Record<WorkflowEdge['on'], string> = {
  success: 'var(--border)',
  failure: 'var(--destructive)',
  always: 'var(--info)',
}

// Deterministic fallback (utils/workflow/layout.ts) for any node with no
// explicit `layout:` entry — e.g. a workflow imported from Git. Recomputed
// from the full node/edge set so nodes missing a position land in a
// coherent layered arrangement together, not just stacked by list index.
const autoLayoutPositions = computed(() => computeAutoLayout(props.nodes, props.edges))

const flowNodes = computed<FlowNode[]>(() => props.nodes.map(step => ({
  id: step.id,
  type: 'workflow',
  position: step.position ?? autoLayoutPositions.value[step.id] ?? { x: 80, y: 40 },
  data: { step, runStatus: props.stepRunByNodeId?.[step.id]?.status },
})))

// D4 — an edge with no `view:` pin renders bottom→top, exactly what every
// workflow did before Faza B existed. Only a manually re-routed edge
// deviates, so upgrading this file causes zero visual change to any
// workflow nobody has touched since.
const flowEdges = computed<FlowEdge[]>(() => props.edges.map(e => ({
  id: e.id,
  source: e.from,
  target: e.to,
  sourceHandle: e.sourceSide ?? 'bottom',
  targetHandle: e.targetSide ?? 'top',
  label: e.on !== 'success' ? e.on : undefined,
  style: {
    stroke: e.id === props.selectedEdgeId ? 'var(--primary-active)' : EDGE_COLOR[e.on],
    strokeWidth: e.id === props.selectedEdgeId ? 2.5 : 1.5,
  },
  markerEnd: { type: MarkerType.ArrowClosed, color: e.id === props.selectedEdgeId ? 'var(--primary-active)' : EDGE_COLOR[e.on], width: 16, height: 16 },
  animated: e.on === 'always',
})))

const { fitView, zoomIn, zoomOut, project, onConnect } = useVueFlow()

function onNodeClick({ node }: { node: FlowNode }) {
  emit('select-edge', null)
  emit('select-node', node.id)
}

function onPaneClick() {
  emit('select-edge', null)
  emit('select-node', null)
}

function onEdgeClick({ edge }: { edge: FlowEdge }) {
  emit('select-node', null)
  emit('select-edge', edge.id)
}

// Faza B §B5 — Vue Flow already tells us exactly which node/edge was
// under the cursor (node-context-menu/edge-context-menu carry it), so
// there's no need to wrap every node in a radix ContextMenuTrigger and
// guess from event.target; see ui/ContextMenu.vue for why it's a plain
// "open at (x,y)" popover instead of that gesture-driven primitive.
const contextMenuRef = ref<{ show: (e: MouseEvent, entries: ContextMenuEntry[]) => void } | null>(null)

function onNodeContextMenu({ event, node }: NodeMouseEvent) {
  const step = props.nodes.find(n => n.id === node.id)
  if (!step) return
  contextMenuRef.value?.show(event as MouseEvent, [
    { label: 'Duplicate', icon: Copy, onSelect: () => emit('duplicate-node', step.id) },
    {
      label: step.disabled ? 'Enable' : 'Disable', icon: step.disabled ? CheckCircle2 : Ban,
      onSelect: () => emit('toggle-disable-node', step.id),
    },
    { label: 'Disconnect', icon: Unlink, onSelect: () => emit('disconnect-node', step.id) },
    { separator: true },
    { label: 'Delete', icon: Trash2, danger: true, onSelect: () => emit('delete-node', step.id) },
  ])
}

function onEdgeContextMenu({ event, edge: flowEdge }: EdgeMouseEvent) {
  const edge = props.edges.find(e => e.id === flowEdge.id)
  if (!edge) return
  contextMenuRef.value?.show(event as MouseEvent, [
    { label: 'Set on: Success', icon: CheckCircle2, disabled: edge.on === 'success', onSelect: () => emit('set-edge-on', { edge, on: 'success' }) },
    { label: 'Set on: Failure', icon: XCircle, disabled: edge.on === 'failure', onSelect: () => emit('set-edge-on', { edge, on: 'failure' }) },
    { label: 'Set on: Always', icon: RefreshCw, disabled: edge.on === 'always', onSelect: () => emit('set-edge-on', { edge, on: 'always' }) },
    { separator: true },
    { label: 'Delete', icon: Trash2, danger: true, onSelect: () => emit('delete-edge', edge) },
  ])
}

// Handle-to-Handle drag — Vue Flow already validates source !== target and
// that both handles exist; the workflow-level rule (no cycles, no dangling
// ends) is server-side (workflow_compiler.py's validate_graph, plan §13
// Level 2/3) — a bad connection here just fails validation, it doesn't
// need duplicating client-side.
//
// sourceHandle/targetHandle are the side ids set on WorkflowNodeBase.vue's
// 4 handles ('top'/'right'/'bottom'/'left') — with connectionMode Loose
// below, any of a node's 4 handles can start or end a drag, so whichever
// two the user actually grabbed is exactly the pin worth persisting.
onConnect((connection: Connection) => {
  if (connection.source && connection.target) {
    emit('connect-nodes', {
      from: connection.source, to: connection.target,
      sourceSide: (connection.sourceHandle ?? undefined) as WorkflowHandleSide | undefined,
      targetSide: (connection.targetHandle ?? undefined) as WorkflowHandleSide | undefined,
    })
  }
})

function onNodeDragStop({ node }: { node: FlowNode }) {
  emit('move-node', { id: node.id, position: { x: node.position.x, y: node.position.y } })
}

const wrapperRef = ref<HTMLElement | null>(null)

function onDragOver(event: DragEvent) {
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
}

function onDrop(event: DragEvent) {
  const type = event.dataTransfer?.getData('application/loki-workflow-node-type')
  if (!type || !wrapperRef.value) return
  const bounds = wrapperRef.value.getBoundingClientRect()
  const position = project({ x: event.clientX - bounds.left, y: event.clientY - bounds.top })
  emit('drop-node', { type, position })
}

// Delete/Backspace removes the selected node or edge — but never while a
// text field elsewhere on the page (properties panel, YAML editor) has
// focus, or "Backspace" while renaming would delete it out from under the
// user.
function onKeydown(event: KeyboardEvent) {
  const tag = (document.activeElement?.tagName ?? '').toLowerCase()
  const inTextField = tag === 'input' || tag === 'textarea' || document.activeElement?.classList.contains('cm-content')

  const mod = event.ctrlKey || event.metaKey
  if (mod && event.key.toLowerCase() === 'z' && !inTextField) {
    event.preventDefault()
    if (event.shiftKey) emit('redo')
    else emit('undo')
    return
  }

  if (event.key !== 'Delete' && event.key !== 'Backspace') return
  if (!props.selectedNodeId && !props.selectedEdgeId) return
  if (inTextField) return

  if (props.selectedEdgeId) {
    const edge = props.edges.find(e => e.id === props.selectedEdgeId)
    if (edge) emit('delete-edge', edge)
    emit('select-edge', null)
  } else if (props.selectedNodeId) {
    emit('delete-node', props.selectedNodeId)
  }
}

onMounted(() => {
  nextTick(() => fitView({ padding: 0.2 }))
  window.addEventListener('keydown', onKeydown)
})
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
defineExpose({ fitView, zoomIn, zoomOut })
</script>

<template>
  <div ref="wrapperRef" class="relative size-full" @dragover="onDragOver" @drop="onDrop">
    <VueFlow
      :nodes="flowNodes"
      :edges="flowEdges"
      :default-viewport="{ zoom: 1 }"
      :min-zoom="0.2"
      :max-zoom="2"
      :connection-mode="ConnectionMode.Loose"
      class="size-full"
      @node-click="onNodeClick"
      @pane-click="onPaneClick"
      @edge-click="onEdgeClick"
      @node-drag-stop="onNodeDragStop"
      @node-context-menu="onNodeContextMenu"
      @edge-context-menu="onEdgeContextMenu"
    >
      <template #node-workflow="nodeProps">
        <WorkflowNodeBase v-bind="nodeProps" :selected="nodeProps.id === selectedNodeId" />
      </template>

      <Background pattern-color="var(--border)" :gap="20" />
      <MiniMap
        class="!rounded-[var(--radius-md)] !border !border-border !bg-card"
        node-color="var(--muted-foreground)"
        mask-color="color-mix(in oklch, var(--background) 70%, transparent)"
      />
    </VueFlow>
    <ContextMenu ref="contextMenuRef" />
  </div>
</template>

<style>
/* Vue Flow's functional stylesheet ships bare CSS custom properties for a
   few structural bits (selection box, connection line) — repointed at our
   own tokens instead of its light-mode defaults. Everything else (node/edge
   appearance) is fully owned by WorkflowNodeBase.vue and the edge style
   binding above, not by anything in this block. */
.vue-flow {
  background: var(--background);
}
.vue-flow__attribution {
  display: none;
}
.vue-flow__edge-text {
  fill: var(--muted-foreground);
  font-size: 11px;
}
.vue-flow__edge-textbg {
  fill: var(--background);
}
</style>
