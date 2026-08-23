import { useDebounceFn, useManualRefHistory, watchDebounced } from '@vueuse/core'
import {
  applyAddEdge, applyAddStep, applyDisconnectStep, applyDuplicateStep, applyEdgeRoutePatch, applyLayoutPatch,
  applyRemoveEdge, applyRemoveStep, applyRenameStep,
  applyStepConfigPatch, applyStepFieldPatch, applyUpdateEdge, parseWorkflowYaml,
} from '~/utils/workflow/yaml'
import { nodeDefinition } from '~/utils/workflow/registry'
import { mergeValidationIssues, validateGraphLocal } from '~/utils/workflow/graph'
import type {
  WorkflowDetail, WorkflowNode, WorkflowEdge, WorkflowNodeType, WorkflowHandleSide, ValidationIssue,
  WorkflowRunDetail, WorkflowStepRun, WorkflowVersion, DryRunResponse,
} from '~/types/workflow'

// Agent heartbeat is ~60s (backend's own dry-run estimate uses the same
// constant, services/workflow_engine.py's _HEARTBEAT_INTERVAL_SECONDS) —
// polling a run every 3s is plenty responsive without hammering the API
// while waiting on something that only ever changes on a much slower clock.
const RUN_POLL_MS = 3000
const RUN_ACTIVE_STATUSES = ['PENDING', 'RUNNING', 'WAITING_APPROVAL']

// Own isolated state, not routed through any other store — same reasoning
// as every dashboard widget in stores/dashboard.ts: nothing else in the app
// shares "the workflow currently open in the editor."
//
// Sync model (plan §9), simplified from the plan's own origin-guard design
// once actually implementing it: yamlSource (text) is the single client-side
// source of truth. nodes/edges are ALWAYS derived from parsing it, on a
// 300ms debounce. A canvas drag doesn't write nodes.value directly — it
// writes a surgical patch into yamlSource (touching only layout.<id>, never
// spec:), and the same debounced parse rebuilds nodes/edges from that new
// text. No origin flag needed: Vue's ref setter already no-ops on an
// unchanged string, so re-deriving the same graph from the same text the
// canvas just produced is not a loop, just a redundant-but-harmless pass.
export const useWorkflowStore = defineStore('workflow', () => {
  const api = useApi()

  const workflow = ref<WorkflowDetail | null>(null)
  const versionId = ref<string | null>(null)
  const versionStatus = ref<'DRAFT' | 'PUBLISHED' | 'ARCHIVED' | null>(null)
  const baseContentHash = ref<string | null>(null)

  const yamlSource = ref('')
  const nodes = ref<WorkflowNode[]>([])
  const edges = ref<WorkflowEdge[]>([])

  const yamlValid = ref(true)
  const parseError = ref<ValidationIssue | null>(null)
  // Authoritative, server-checked (800ms debounced) — see validateRemote.
  const remoteValidationErrors = ref<ValidationIssue[]>([])
  const remoteValidationWarnings = ref<ValidationIssue[]>([])
  // Level 1 (plan §13) — pure client-side graph checks, recomputed on every
  // nodes/edges change for <16ms feedback, merged with the remote result
  // below so a broken graph shows red instantly instead of after 800ms.
  const localValidation = computed(() => validateGraphLocal(nodes.value, edges.value))
  const validationErrors = computed(() => mergeValidationIssues(localValidation.value.errors, remoteValidationErrors.value))
  const validationWarnings = computed(() => mergeValidationIssues(localValidation.value.warnings, remoteValidationWarnings.value))

  const loading = ref(false)
  const error = ref(false)
  const saving = ref(false)
  const isDirty = ref(false)

  const selectedNodeId = ref<string | null>(null)
  const selectedEdgeId = ref<string | null>(null)

  // Undo/redo (plan §8, simplified same as the YAML sync itself): since
  // yamlSource is the single source of truth, one string history covers
  // the whole editor — no separate nodes/edges/vars snapshot machinery.
  // "Manual" means nothing commits on its own; every mutation below calls
  // _commitHistory() once, at its own natural semantic boundary (one
  // add-step, one drag-stop, one debounced form edit) — except raw YAML
  // typing, which has no upstream debounce and gets its own via
  // commitHistoryDebounced so undo doesn't land on a half-typed line.
  const history = useManualRefHistory(yamlSource, { capacity: 50 })

  // vueuse's commit() is unconditional — it'll happily push a duplicate
  // entry for a patch that left the text unchanged (e.g. CodeMirror firing
  // an update:model-value on mount with the same text it was given). Left
  // unguarded, one undo press lands on that no-op duplicate instead of
  // visibly reverting anything, which reads as "undo is broken." Comparing
  // against history.last — the value actually on top of the stack right
  // now — is what makes every entry meaningful, and works uniformly for
  // both the synchronous call sites below and the debounced YAML-typing
  // one (where a locally-captured "before" from call time would be stale
  // by the time the debounce fires).
  function _commitHistory() {
    if (yamlSource.value !== history.last.value.snapshot) history.commit()
  }
  const commitHistoryDebounced = useDebounceFn(_commitHistory, 600)

  function undo() {
    if (!history.canUndo.value) return
    history.undo()
    isDirty.value = true
    _applyParsedYaml(yamlSource.value)
  }

  function redo() {
    if (!history.canRedo.value) return
    history.redo()
    isDirty.value = true
    _applyParsedYaml(yamlSource.value)
  }

  async function load(workflowId: string) {
    loading.value = true
    error.value = false
    try {
      const detail = await api.get<WorkflowDetail>(`/workflows/${workflowId}`)
      workflow.value = detail

      let version = detail.current_version
      if (!version) {
        // Workflow.current_version_id is only ever set by publish — a
        // freshly created workflow (e.g. "New Workflow") has a real DRAFT
        // row but current_version stays null forever until someone
        // publishes it. Without this fallback the editor had no way to
        // even DISPLAY that draft, let alone publish it — confirmed live,
        // the only way in was a hand-crafted API call. `/versions` is
        // ordered by version desc, so the first item is the most recent
        // one regardless of status.
        const versions = await api.get<{ items: WorkflowVersion[] }>(`/workflows/${workflowId}/versions`)
        version = versions.items[0] ?? null
      }

      if (version) {
        versionId.value = version.id
        versionStatus.value = version.status
        baseContentHash.value = version.content_hash
        yamlSource.value = version.yaml_source
        _applyParsedYaml(yamlSource.value)
        isDirty.value = false
      } else {
        versionId.value = null
        versionStatus.value = null
        nodes.value = []
        edges.value = []
      }

      // The loaded/published version is the undo floor — nobody should be
      // able to undo past what's actually on the server. commit() must run
      // BEFORE clear(): commit() always pushes the ref's PRIOR value (here,
      // the stale '' from before this load) onto the stack as a side effect
      // of recording the new one — clear() afterward drops that stale entry
      // without touching the fresh baseline commit() just recorded.
      history.commit()
      history.clear()

      await loadLatestRun(workflowId)
    } catch {
      error.value = true
    } finally {
      loading.value = false
    }
  }

  // The single re-derivation point: any yamlSource change (drag patch or
  // typed edit) flows through here. Frozen on syntax error — nodes/edges
  // keep their last-good value, never a partial/wrong graph. Also called
  // directly (not through the 300ms debounce below) by undo/redo, so the
  // canvas snaps back immediately instead of lagging behind the keystroke.
  function _applyParsedYaml(text: string) {
    if (!text) return
    const { result, error: err } = parseWorkflowYaml(text)
    if (err) {
      yamlValid.value = false
      parseError.value = err
      return
    }
    yamlValid.value = true
    parseError.value = null
    nodes.value = result!.nodes
    edges.value = result!.edges
  }

  watchDebounced(yamlSource, _applyParsedYaml, { debounce: 300 })

  function updateNodePosition(id: string, position: { x: number; y: number }) {
    const node = nodes.value.find(n => n.id === id)
    if (node) node.position = position
    yamlSource.value = applyLayoutPatch(yamlSource.value, id, position.x, position.y)
    isDirty.value = true
    _commitHistory()
  }

  // Raw YAML tab typing has no upstream debounce (PlaybookEditor emits on
  // every keystroke) — history commits go through commitHistoryDebounced
  // instead of a synchronous commit() here, so undo lands on a pause in
  // typing, not a half-typed line.
  function setYamlText(text: string) {
    yamlSource.value = text
    isDirty.value = true
    commitHistoryDebounced()
  }

  /** Dropped from WorkflowPalette.vue. Id is derived from the type plus a
   * counter — short, readable, stable enough for a first cut; renameStep
   * below is what turns `command_3` into something a Git diff reads as
   * meaningful. */
  function addStep(
    type: WorkflowNodeType, position: { x: number; y: number },
    overrides?: { name?: string; config?: Record<string, unknown> },
  ) {
    const def = nodeDefinition(type)
    let n = 1
    let id = `${type}_${n}`
    while (nodes.value.some(node => node.id === id)) { n += 1; id = `${type}_${n}` }

    const name = overrides?.name ?? def.label
    const config = overrides?.config ?? {}
    yamlSource.value = applyAddStep(yamlSource.value, { id, type, name, config }, position)
    isDirty.value = true
    _commitHistory()
    return id
  }

  function removeStep(stepId: string) {
    yamlSource.value = applyRemoveStep(yamlSource.value, stepId)
    isDirty.value = true
    if (selectedNodeId.value === stepId) selectedNodeId.value = null
    _commitHistory()
  }

  /** Rewrites a step's id everywhere (itself, referencing edges, layout,
   * view route pins — all in one yaml.ts call, see applyRenameStep). Only
   * commits on the server-matching id pattern and no collision; the caller
   * (WorkflowProperties.vue, on blur/Enter, never live per-keystroke — a
   * step id has uniqueness and pattern constraints a debounced live-write
   * would violate mid-type) is expected to show its own error state on a
   * `false` return rather than this function throwing or toasting. */
  function renameStep(oldId: string, newId: string): boolean {
    if (oldId === newId) return true
    const before = yamlSource.value
    yamlSource.value = applyRenameStep(before, oldId, newId)
    if (yamlSource.value === before) return false
    isDirty.value = true
    if (selectedNodeId.value === oldId) selectedNodeId.value = newId
    _commitHistory()
    return true
  }

  /** Duplicates a step (same type/config, offset position, no edges — see
   * applyDuplicateStep) and selects the copy, matching addStep's UX so a
   * duplicated step is immediately editable in the properties panel. */
  function duplicateStep(stepId: string): string | null {
    const { yaml, newId } = applyDuplicateStep(yamlSource.value, stepId)
    if (!newId) return null
    yamlSource.value = yaml
    isDirty.value = true
    _commitHistory()
    selectedNodeId.value = newId
    return newId
  }

  /** WorkflowContextMenu.vue's "Disconnect" — removes every edge touching
   * a step without removing the step itself. */
  function disconnectStep(stepId: string) {
    const before = yamlSource.value
    yamlSource.value = applyDisconnectStep(before, stepId)
    if (yamlSource.value === before) return
    isDirty.value = true
    _commitHistory()
  }

  /** From WorkflowCanvas's onConnect (Handle-to-Handle drag). `on` defaults
   * to success — the common case — WorkflowEdgeProperties.vue is where an
   * existing edge's condition gets changed after the fact. sourceSide/
   * targetSide are the handle ids the user actually dragged from/to (Faza
   * B, plan §D2) — recorded under `view:` in the same call so a single
   * drag gesture produces one coherent edit, not two separate undo steps. */
  function addEdge(
    from: string, to: string, on: WorkflowEdge['on'] = 'success',
    sourceSide?: WorkflowHandleSide, targetSide?: WorkflowHandleSide,
  ) {
    yamlSource.value = applyAddEdge(yamlSource.value, from, to, on)
    if (sourceSide && targetSide) {
      yamlSource.value = applyEdgeRoutePatch(yamlSource.value, from, on, to, sourceSide, targetSide)
    }
    isDirty.value = true
    _commitHistory()
  }

  function removeEdge(from: string, to: string, on: WorkflowEdge['on']) {
    yamlSource.value = applyRemoveEdge(yamlSource.value, from, to, on)
    isDirty.value = true
    if (selectedEdgeId.value === `${from}:${on}:${to}`) selectedEdgeId.value = null
    _commitHistory()
  }

  /** Changes an existing edge's `on`/`label` from WorkflowEdgeProperties.vue.
   * Changing `on` changes the edge's id (`${from}:${on}:${to}`), so the
   * view.edges route pin — keyed on that same triple — has to move with
   * it; applyUpdateEdge does both atomically in yaml.ts rather than this
   * function orchestrating two separate patches that could partially fail. */
  function updateEdge(from: string, to: string, on: WorkflowEdge['on'], patch: { on?: WorkflowEdge['on']; label?: string }) {
    yamlSource.value = applyUpdateEdge(yamlSource.value, from, to, on, patch)
    isDirty.value = true
    if (patch.on && patch.on !== on) selectedEdgeId.value = `${from}:${patch.on}:${to}`
    _commitHistory()
  }

  /** Step-level field (name/timeout/on_failure/disabled) — a real semantic
   * change, unlike a position drag, so it touches spec: on purpose. Already
   * debounced upstream (WorkflowProperties.vue's watchDebounced), so one
   * call here is already one coalesced form edit — commit synchronously
   * (guarded: the debounce still fires once on mount with the unchanged
   * value, which must not count as an edit). */
  function updateStepField(stepId: string, field: string, value: unknown) {
    yamlSource.value = applyStepFieldPatch(yamlSource.value, stepId, field, value)
    isDirty.value = true
    _commitHistory()
  }

  /** One key inside a step's config block — what WorkflowNodeConfigForm.vue
   * writes through, keyed by the field's registry-defined `key`. Same
   * already-debounced-upstream reasoning as updateStepField. */
  function updateStepConfig(stepId: string, key: string, value: unknown) {
    yamlSource.value = applyStepConfigPatch(yamlSource.value, stepId, key, value)
    isDirty.value = true
    _commitHistory()
  }

  async function validateRemote() {
    try {
      const result = await api.post<{ valid: boolean; errors: ValidationIssue[]; warnings: ValidationIssue[] }>(
        '/workflows/validate', { yaml: yamlSource.value },
      )
      remoteValidationErrors.value = result.errors
      remoteValidationWarnings.value = result.warnings
      return result.valid
    } catch {
      return false
    }
  }

  watchDebounced(yamlSource, () => {
    if (yamlValid.value) void validateRemote()
  }, { debounce: 800 })

  /** Result distinguishes "created a new draft" from "updated the existing
   * one" purely so the caller can toast something more honest than "Saved"
   * — the version list just grew, which a silent success would hide. */
  async function save(): Promise<{ ok: true; createdNewDraft: boolean; version: number } | { ok: false }> {
    if (!workflow.value || !versionId.value) return { ok: false }
    saving.value = true
    try {
      // A PUBLISHED/ARCHIVED version is immutable (workflow_service.py's
      // update_draft rejects it with 409) — the only honest move is to
      // start a new DRAFT from the current text, not retry the same PUT
      // against a version that can never accept it.
      if (versionStatus.value !== 'DRAFT') {
        const created = await api.post<{ id: string; content_hash: string; version: number }>(
          `/workflows/${workflow.value.id}/versions`, { yaml: yamlSource.value },
        )
        versionId.value = created.id
        versionStatus.value = 'DRAFT'
        baseContentHash.value = created.content_hash
        isDirty.value = false
        return { ok: true, createdNewDraft: true, version: created.version }
      }

      const version = await api.put<{ content_hash: string; version: number }>(
        `/workflows/${workflow.value.id}/versions/${versionId.value}`,
        { yaml: yamlSource.value, base_content_hash: baseContentHash.value },
      )
      baseContentHash.value = version.content_hash
      isDirty.value = false
      return { ok: true, createdNewDraft: false, version: version.version }
    } catch {
      return { ok: false }
    } finally {
      saving.value = false
    }
  }

  const publishing = ref(false)

  /** No UI action for this existed anywhere in the editor — a workflow
   * created through the "New Workflow" dialog got a DRAFT version and
   * simply had no way to become runnable from the browser (confirmed live:
   * POST .../versions/{id}/publish had to be called by hand). Mirrors
   * save()'s error handling; a DRAFT is required since PUBLISHED/ARCHIVED
   * can't be re-published (workflow_service.py's publish_version rejects
   * it, same 409 rule save() already works around). */
  async function publish(): Promise<{ ok: true; version: number } | { ok: false }> {
    if (!workflow.value || !versionId.value || versionStatus.value !== 'DRAFT') return { ok: false }
    publishing.value = true
    try {
      const published = await api.post<{ status: 'DRAFT' | 'PUBLISHED' | 'ARCHIVED'; version: number }>(
        `/workflows/${workflow.value.id}/versions/${versionId.value}/publish`, {},
      )
      versionStatus.value = published.status
      workflow.value.current_version_id = versionId.value
      return { ok: true, version: published.version }
    } catch {
      return { ok: false }
    } finally {
      publishing.value = false
    }
  }

  /** Phase 8 — the backend's cron scheduling (WorkflowSchedulerWorker) was
   * fully built and unit-tested, but no UI anywhere let a user actually set
   * a workflow's trigger_type/cron_expr — same class of gap as the missing
   * Publish button. `update_metadata` (workflow_service.py) recomputes
   * next_run_at and validates the cron expression server-side; this just
   * surfaces both outcomes. */
  async function updateSchedule(triggerType: 'MANUAL' | 'SCHEDULE', cronExpr: string | null): Promise<{ ok: true } | { ok: false; error: string }> {
    if (!workflow.value) return { ok: false, error: 'No workflow loaded' }
    try {
      const updated = await api.patch<{ trigger_type: 'MANUAL' | 'SCHEDULE'; cron_expr: string | null; next_run_at: string | null }>(
        `/workflows/${workflow.value.id}`, { trigger_type: triggerType, cron_expr: cronExpr },
      )
      workflow.value.trigger_type = updated.trigger_type
      workflow.value.cron_expr = updated.cron_expr
      workflow.value.next_run_at = updated.next_run_at
      return { ok: true }
    } catch (err) {
      const message = (err as { data?: { detail?: string } })?.data?.detail ?? 'Could not update schedule'
      return { ok: false, error: message }
    }
  }

  function selectNode(id: string | null) {
    selectedNodeId.value = id
    if (id) selectedEdgeId.value = null
  }

  function selectEdge(id: string | null) {
    selectedEdgeId.value = id
    if (id) selectedNodeId.value = null
  }

  // ── Execution (Phase 6/8 UI) ────────────────────────────────────────────
  // Own state, not stores/jobs.ts — a run's step_runs reference Jobs, but
  // this widget must never touch the shared `jobs` array that /jobs and
  // server-detail pages depend on (same isolation rule as every other
  // store in this app, stores/dashboard.ts:63-83 documents the original
  // case for it).

  const currentRun = ref<WorkflowRunDetail | null>(null)
  const runStarting = ref(false)
  const runActionPending = ref(false)
  const dryRunResult = ref<DryRunResponse | null>(null)
  const dryRunning = ref(false)

  let pollTimer: ReturnType<typeof setInterval> | null = null

  function _stopPolling() {
    if (pollTimer) clearInterval(pollTimer)
    pollTimer = null
  }

  function _startPolling() {
    _stopPolling()
    pollTimer = setInterval(() => void refreshRun(), RUN_POLL_MS)
  }

  async function refreshRun() {
    if (!currentRun.value) return
    try {
      const detail = await api.get<WorkflowRunDetail>(`/workflows/runs/${currentRun.value.id}`)
      currentRun.value = detail
      if (!RUN_ACTIVE_STATUSES.includes(detail.status)) _stopPolling()
    } catch {
      _stopPolling()
    }
  }

  /** Called from load() — resumes watching an already-in-progress run
   * (e.g. the page was reloaded mid-execution) and still shows the most
   * recent terminal run read-only otherwise, rather than showing nothing. */
  async function loadLatestRun(workflowId: string) {
    try {
      const list = await api.get<{ items: { id: string }[] }>(`/workflows/${workflowId}/runs?limit=1`)
      if (!list.items.length) { currentRun.value = null; return }
      currentRun.value = await api.get<WorkflowRunDetail>(`/workflows/runs/${list.items[0]!.id}`)
      if (currentRun.value && RUN_ACTIVE_STATUSES.includes(currentRun.value.status)) _startPolling()
    } catch {
      currentRun.value = null
    }
  }

  async function fetchDryRun() {
    if (!workflow.value) return
    dryRunning.value = true
    try {
      dryRunResult.value = await api.post<DryRunResponse>(`/workflows/${workflow.value.id}/dry-run`, {})
      return true
    } catch {
      return false
    } finally {
      dryRunning.value = false
    }
  }

  async function startRun(): Promise<boolean> {
    if (!workflow.value) return false
    runStarting.value = true
    try {
      const run = await api.post<{ id: string }>(`/workflows/${workflow.value.id}/run`, {})
      currentRun.value = await api.get<WorkflowRunDetail>(`/workflows/runs/${run.id}`)
      _startPolling()
      return true
    } catch {
      return false
    } finally {
      runStarting.value = false
    }
  }

  async function cancelCurrentRun() {
    if (!currentRun.value) return
    runActionPending.value = true
    try {
      await api.post(`/workflows/runs/${currentRun.value.id}/cancel`, {})
      await refreshRun()
    } finally {
      runActionPending.value = false
    }
  }

  async function approveStep(stepId: string) {
    if (!currentRun.value) return
    runActionPending.value = true
    try {
      await api.post(`/workflows/runs/${currentRun.value.id}/steps/${stepId}/approve`, {})
      await refreshRun()
    } finally {
      runActionPending.value = false
    }
  }

  async function rejectStep(stepId: string) {
    if (!currentRun.value) return
    runActionPending.value = true
    try {
      await api.post(`/workflows/runs/${currentRun.value.id}/steps/${stepId}/reject`, {})
      await refreshRun()
    } finally {
      runActionPending.value = false
    }
  }

  function stopRunPolling() {
    _stopPolling()
  }

  /** WorkflowCanvas's per-node status overlay reads this — id -> latest
   * WorkflowStepRun for the current run, or undefined for a step that
   * hasn't started (or when there's no current run at all). */
  const stepRunByNodeId = computed<Record<string, WorkflowStepRun>>(() => {
    const map: Record<string, WorkflowStepRun> = {}
    for (const sr of currentRun.value?.step_runs ?? []) map[sr.step_id] = sr
    return map
  })

  return {
    workflow, versionId, versionStatus, baseContentHash,
    yamlSource, nodes, edges,
    yamlValid, parseError, validationErrors, validationWarnings,
    loading, error, saving, isDirty, publishing,
    selectedNodeId, selectedEdgeId,
    load, selectNode, selectEdge, updateNodePosition, setYamlText, save, publish, updateSchedule, validateRemote,
    updateStepField, updateStepConfig, addStep, removeStep, renameStep, duplicateStep, disconnectStep,
    addEdge, removeEdge, updateEdge,
    undo, redo, canUndo: history.canUndo, canRedo: history.canRedo,
    currentRun, runStarting, runActionPending, dryRunResult, dryRunning, stepRunByNodeId,
    fetchDryRun, startRun, cancelCurrentRun, approveStep, rejectStep, stopRunPolling,
  }
})
