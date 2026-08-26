<script setup lang="ts">
import { ArrowLeft, ZoomIn, ZoomOut, Maximize, Save, Upload, AlertTriangle, Play, FlaskConical, Undo2, Redo2, Clock } from 'lucide-vue-next'
import type { WorkflowNodeType, WorkflowEdge, WorkflowHandleSide } from '~/types/workflow'

const route = useRoute()
const workflowId = route.params.id as string

const store = useWorkflowStore()
const {
  workflow, nodes, edges, loading, error, selectedNodeId, selectedEdgeId,
  yamlSource, yamlValid, parseError, validationErrors, validationWarnings,
  saving, isDirty, versionStatus, publishing,
  currentRun, runStarting, runActionPending, dryRunResult, dryRunning, stepRunByNodeId,
  canUndo, canRedo,
} = storeToRefs(store)

const toast = useToast()
const { canEdit } = useCurrentUser()

onMounted(() => store.load(workflowId))
onUnmounted(() => {
  store.selectNode(null)
  store.stopRunPolling()
})

// F1: zero navigation guard anywhere in the app let a stray sidebar click
// discard everything since the last Save. Two halves — in-app navigation
// (Vue Router, can show our own dialog and await the choice) and the
// browser-native cases reload/close-tab (no custom UI possible there, only
// the browser's own generic prompt via preventDefault + returnValue).
const showLeaveConfirm = ref(false)
let resolveLeave: ((leave: boolean) => void) | null = null

onBeforeRouteLeave(() => {
  if (!isDirty.value) return true
  return new Promise<boolean>((resolve) => {
    resolveLeave = resolve
    showLeaveConfirm.value = true
  })
})

function onLeaveChoice(leave: boolean) {
  showLeaveConfirm.value = false
  resolveLeave?.(leave)
  resolveLeave = null
}

useEventListener(window, 'beforeunload', (event: BeforeUnloadEvent) => {
  if (!isDirty.value) return
  event.preventDefault()
  event.returnValue = ''
})

const canvasRef = ref<{ zoomIn: () => void; zoomOut: () => void; fitView: (opts?: { padding?: number }) => void } | null>(null)

useHead({ title: computed(() => workflow.value?.name ?? 'Workflow') })

const tabs = [
  { label: 'Visual', slot: 'visual' },
  { label: 'YAML', slot: 'yaml' },
  { label: 'Runs', slot: 'runs' },
]

const RUN_ACTIVE = ['PENDING', 'RUNNING', 'WAITING_APPROVAL']
const runIsActive = computed(() => !!currentRun.value && RUN_ACTIVE.includes(currentRun.value.status))

const showDryRun = ref(false)
async function onDryRun() {
  const ok = await store.fetchDryRun()
  if (ok) showDryRun.value = true
  else toast.add({ title: 'Dry run failed', color: 'red' })
}

async function onRun() {
  const ok = await store.startRun()
  toast.add(ok ? { title: 'Run started', color: 'green' } : { title: 'Could not start run', color: 'red' })
}

async function onCancelRun() {
  await store.cancelCurrentRun()
}
async function onApproveStep(stepId: string) {
  await store.approveStep(stepId)
}
async function onRejectStep(stepId: string) {
  await store.rejectStep(stepId)
}

function onMoveNode(payload: { id: string; position: { x: number; y: number } }) {
  store.updateNodePosition(payload.id, payload.position)
}

function onDropNode(payload: { type: string; position: { x: number; y: number } }) {
  const id = store.addStep(payload.type as WorkflowNodeType, payload.position)
  store.selectNode(id)
}

// Click-to-add (WorkflowPalette.vue) has no drop coordinates — stack new
// nodes in a loose vertical line so they never land exactly on top of an
// existing one.
function onAddNode(type: WorkflowNodeType) {
  const id = store.addStep(type, { x: 120, y: 80 + nodes.value.length * 90 })
  store.selectNode(id)
}

function onDeleteNode(id: string) {
  store.removeStep(id)
}

function onUndo() {
  store.undo()
}
function onRedo() {
  store.redo()
}

function onConnectNodes(payload: { from: string; to: string; sourceSide?: WorkflowHandleSide; targetSide?: WorkflowHandleSide }) {
  store.addEdge(payload.from, payload.to, 'success', payload.sourceSide, payload.targetSide)
}

function onDeleteEdge(edge: WorkflowEdge) {
  store.removeEdge(edge.from, edge.to, edge.on)
}

function onDuplicateNode(id: string) {
  store.duplicateStep(id)
}
function onDisconnectNode(id: string) {
  store.disconnectStep(id)
}
function onToggleDisableNode(id: string) {
  const node = nodes.value.find(n => n.id === id)
  if (node) store.updateStepField(id, 'disabled', node.disabled ? undefined : true)
}
function onSetEdgeOn(payload: { edge: WorkflowEdge; on: WorkflowEdge['on'] }) {
  store.updateEdge(payload.edge.from, payload.edge.to, payload.edge.on, { on: payload.on })
}

const selectedNode = computed(() => nodes.value.find(n => n.id === selectedNodeId.value) ?? null)
const selectedEdge = computed(() => edges.value.find(e => e.id === selectedEdgeId.value) ?? null)

function onUpdateEdge(patch: { on?: WorkflowEdge['on']; label?: string }) {
  if (selectedEdge.value) store.updateEdge(selectedEdge.value.from, selectedEdge.value.to, selectedEdge.value.on, patch)
}
function onDeleteSelectedEdge() {
  if (selectedEdge.value) store.removeEdge(selectedEdge.value.from, selectedEdge.value.to, selectedEdge.value.on)
}

function onUpdateField(field: string, value: unknown) {
  if (selectedNode.value) store.updateStepField(selectedNode.value.id, field, value)
}
function onUpdateConfig(key: string, value: unknown) {
  if (selectedNode.value) store.updateStepConfig(selectedNode.value.id, key, value)
}

async function onSave() {
  const result = await store.save()
  if (!result.ok) {
    toast.add({ title: 'Could not save', description: 'Someone else may have changed this version — reload and retry.', color: 'red' })
    return
  }
  toast.add(result.createdNewDraft
    ? { title: `Saved as new draft (v${result.version})`, description: 'The published version is unchanged — publish this draft when ready.', color: 'green' }
    : { title: 'Saved', color: 'green' })
}

async function onPublish() {
  const result = await store.publish()
  toast.add(result.ok
    ? { title: `Published v${result.version}`, description: 'This workflow can now be run.', color: 'green' }
    : { title: 'Could not publish', color: 'red' })
}

// Phase 8 — WorkflowSchedulerWorker (backend) was fully built and unit
// tested, but nothing in the app let a user actually turn a workflow into
// a scheduled one. scheduleTriggerLocal/scheduleCronLocal are local drafts,
// reset from the loaded workflow whenever the dialog opens — same
// edit-then-explicit-commit shape as everything else here, not a live
// patch per keystroke.
const showSchedule = ref(false)
const scheduleTriggerLocal = ref<'MANUAL' | 'SCHEDULE'>('MANUAL')
const scheduleCronLocal = ref('')
const scheduleSaving = ref(false)
const scheduleError = ref('')

const TRIGGER_OPTIONS = [
  { label: 'Manual', value: 'MANUAL' },
  { label: 'Schedule (cron)', value: 'SCHEDULE' },
]

function openSchedule() {
  scheduleTriggerLocal.value = workflow.value?.trigger_type ?? 'MANUAL'
  scheduleCronLocal.value = workflow.value?.cron_expr ?? ''
  scheduleError.value = ''
  showSchedule.value = true
}

async function onSaveSchedule() {
  scheduleSaving.value = true
  scheduleError.value = ''
  const result = await store.updateSchedule(
    scheduleTriggerLocal.value, scheduleTriggerLocal.value === 'SCHEDULE' ? scheduleCronLocal.value : null,
  )
  scheduleSaving.value = false
  if (!result.ok) {
    scheduleError.value = result.error
    return
  }
  showSchedule.value = false
  toast.add({ title: 'Schedule updated', color: 'green' })
}
</script>

<template>
  <div class="relative -m-3 sm:-m-4 flex h-[calc(100vh-4rem)] flex-col overflow-hidden">
    <div class="flex shrink-0 items-center gap-3 border-b border-border bg-card px-3 py-2 sm:px-4">
      <NuxtLink to="/workflows" aria-label="Back to workflows" class="flex items-center justify-center rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors">
        <ArrowLeft class="size-4" />
      </NuxtLink>
      <div class="min-w-0 flex-1">
        <p class="truncate text-[14px] font-medium">{{ workflow?.name ?? '…' }}</p>
        <p v-if="workflow" class="truncate text-[11px] text-muted-foreground">{{ workflow.slug }}</p>
      </div>
      <Badge v-if="!yamlValid" size="xs" color="red">Invalid YAML</Badge>
      <Badge v-else-if="isDirty" size="xs" color="amber">Unsaved</Badge>
      <Badge v-else-if="workflow" size="xs" :color="workflow.current_version_id ? 'green' : 'gray'">
        {{ workflow.current_version_id ? `v${workflow.current_version?.version} published` : 'Draft only' }}
      </Badge>
      <Button size="xs" :loading="saving" :disabled="!isDirty || !yamlValid" @click="onSave">
        <Save class="size-3.5" />
        Save
      </Button>
      <Button
        v-if="canEdit" size="xs" variant="outline" :loading="publishing"
        :disabled="versionStatus !== 'DRAFT' || isDirty"
        @click="onPublish"
      >
        <Upload class="size-3.5" />
        Publish
      </Button>
      <Button size="xs" variant="outline" :loading="dryRunning" :disabled="!workflow?.current_version_id" @click="onDryRun">
        <FlaskConical class="size-3.5" />
        Dry Run
      </Button>
      <Button v-if="canEdit" size="xs" variant="ghost" @click="openSchedule">
        <Clock class="size-3.5" />
        {{ workflow?.trigger_type === 'SCHEDULE' ? workflow.cron_expr : 'Manual' }}
      </Button>
      <Button
        v-if="canEdit" size="xs" :loading="runStarting"
        :disabled="!workflow?.current_version_id || runIsActive"
        @click="onRun"
      >
        <Play class="size-3.5" />
        {{ runIsActive ? 'Running…' : 'Run' }}
      </Button>
      <div class="flex items-center gap-1">
        <Button size="xs" variant="ghost" aria-label="Undo" :disabled="!canUndo" @click="onUndo">
          <Undo2 class="size-4" />
        </Button>
        <Button size="xs" variant="ghost" aria-label="Redo" :disabled="!canRedo" @click="onRedo">
          <Redo2 class="size-4" />
        </Button>
        <Button size="xs" variant="ghost" aria-label="Zoom out" @click="canvasRef?.zoomOut()">
          <ZoomOut class="size-4" />
        </Button>
        <Button size="xs" variant="ghost" aria-label="Zoom in" @click="canvasRef?.zoomIn()">
          <ZoomIn class="size-4" />
        </Button>
        <Button size="xs" variant="ghost" aria-label="Fit view" @click="canvasRef?.fitView({ padding: 0.2 })">
          <Maximize class="size-4" />
        </Button>
      </div>
    </div>

    <DashboardError v-if="error" @retry="store.load(workflowId)" />
    <div v-else-if="loading" class="flex flex-1 items-center justify-center text-sm text-muted-foreground">
      Loading workflow…
    </div>
    <div v-else-if="!workflow?.current_version_id && !nodes.length" class="flex flex-1 items-center justify-center text-sm text-muted-foreground">
      This workflow has no published version yet.
    </div>
    <AppTabs v-else :items="tabs" class="flex min-h-0 flex-1 flex-col [&>[role=tabpanel]]:min-h-0 [&>[role=tabpanel]]:flex-1">
      <template #visual>
        <div class="flex size-full">
          <WorkflowPalette v-if="canEdit && yamlValid" @add-node="onAddNode" />
          <div class="relative min-w-0 flex-1">
            <div v-if="!yamlValid" class="absolute inset-x-0 top-0 z-10 flex items-center gap-2 border-b border-destructive/30 bg-[color-mix(in_oklch,var(--destructive)_10%,var(--background))] px-3 py-2 text-xs text-destructive">
              <AlertTriangle class="size-4 shrink-0" />
              <span class="min-w-0 truncate">
                YAML Parse Error — Line {{ parseError?.line ?? '?' }}: {{ parseError?.message }}. Canvas is frozen until the YAML tab is fixed.
              </span>
            </div>
            <WorkflowCanvas
              ref="canvasRef"
              :nodes="nodes"
              :edges="edges"
              :selected-node-id="selectedNodeId"
              :selected-edge-id="selectedEdgeId"
              :step-run-by-node-id="stepRunByNodeId"
              @select-node="store.selectNode"
              @select-edge="store.selectEdge"
              @move-node="onMoveNode"
              @drop-node="onDropNode"
              @delete-node="onDeleteNode"
              @duplicate-node="onDuplicateNode"
              @disconnect-node="onDisconnectNode"
              @toggle-disable-node="onToggleDisableNode"
              @connect-nodes="onConnectNodes"
              @delete-edge="onDeleteEdge"
              @set-edge-on="onSetEdgeOn"
              @undo="onUndo"
              @redo="onRedo"
            />
          </div>
          <WorkflowProperties
            v-if="selectedNode"
            :node="selectedNode"
            @update-field="onUpdateField"
            @update-config="onUpdateConfig"
            @close="store.selectNode(null)"
          />
          <WorkflowEdgeProperties
            v-else-if="selectedEdge"
            :edge="selectedEdge"
            @update-edge="onUpdateEdge"
            @delete="onDeleteSelectedEdge"
            @close="store.selectEdge(null)"
          />
        </div>
      </template>
      <template #yaml>
        <div class="flex h-full flex-col gap-2 overflow-y-auto p-3 sm:p-4">
          <PlaybookEditor :model-value="yamlSource" tall @update:model-value="store.setYamlText" />
          <div v-if="validationErrors.length || validationWarnings.length" class="space-y-1.5">
            <div v-for="issue in validationErrors" :key="`${issue.code}-${issue.path}`" class="flex items-start gap-2 rounded-[var(--radius-sm)] border border-destructive/30 bg-[color-mix(in_oklch,var(--destructive)_8%,var(--background))] px-2.5 py-1.5 text-xs text-destructive">
              <AlertTriangle class="size-3.5 shrink-0 mt-0.5" />
              <span>{{ issue.path }} — {{ issue.message }}</span>
            </div>
            <div v-for="issue in validationWarnings" :key="`${issue.code}-${issue.path}`" class="flex items-start gap-2 rounded-[var(--radius-sm)] border border-warning/30 bg-[color-mix(in_oklch,var(--warning)_8%,var(--background))] px-2.5 py-1.5 text-xs text-warning">
              <AlertTriangle class="size-3.5 shrink-0 mt-0.5" />
              <span>{{ issue.path }} — {{ issue.message }}</span>
            </div>
          </div>
        </div>
      </template>
      <template #runs>
        <WorkflowRunPanel
          :run="currentRun"
          :nodes="nodes"
          :action-pending="runActionPending"
          @cancel="onCancelRun"
          @approve="onApproveStep"
          @reject="onRejectStep"
        />
      </template>
    </AppTabs>

    <WorkflowDryRunDialog v-model="showDryRun" :result="dryRunResult" />

    <Dialog :model-value="showLeaveConfirm" title="Discard unsaved changes?" size="sm" @update:model-value="(v) => !v && onLeaveChoice(false)">
      <template #body>
        <p class="text-sm text-muted-foreground">This workflow has unsaved edits. Leaving now discards them.</p>
      </template>
      <template #footer>
        <Button size="sm" variant="outline" @click="onLeaveChoice(false)">Cancel</Button>
        <Button size="sm" variant="destructive" @click="onLeaveChoice(true)">Discard and leave</Button>
      </template>
    </Dialog>

    <Dialog v-model="showSchedule" title="Schedule" size="sm">
      <template #body>
        <div class="space-y-3">
          <FormField label="Trigger">
            <Select v-model="scheduleTriggerLocal" :options="TRIGGER_OPTIONS" />
          </FormField>
          <FormField v-if="scheduleTriggerLocal === 'SCHEDULE'" label="Cron expression" help="Standard 5-field cron, e.g. 0 */6 * * * for every 6 hours.">
            <Input v-model="scheduleCronLocal" placeholder="0 */6 * * *" class="font-mono text-xs" />
          </FormField>
          <p v-if="scheduleError" class="text-xs text-destructive">{{ scheduleError }}</p>
        </div>
      </template>
      <template #footer>
        <Button size="sm" variant="outline" @click="showSchedule = false">Cancel</Button>
        <Button size="sm" :loading="scheduleSaving" @click="onSaveSchedule">Save</Button>
      </template>
    </Dialog>
  </div>
</template>
