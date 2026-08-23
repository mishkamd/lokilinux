import { parseDocument, Document } from 'yaml'
import type { WorkflowNode, WorkflowEdge, WorkflowNodeType, WorkflowHandleSide, ValidationIssue } from '~/types/workflow'

export interface ParsedWorkflowYaml {
  doc: Document
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
}

/**
 * Text -> Document (CST, comments preserved) -> nodes/edges. Client-side
 * mirror of the backend compiler's build_graph (services/workflow_compiler.py)
 * — deliberately loose (no Pydantic-grade validation): this only has to be
 * good enough to keep the canvas showing *something* reasonable while
 * typing. The authoritative check is POST /workflows/validate, debounced
 * separately (plan §13 — client is Level 1, server is Level 2/3).
 *
 * Returns null on a YAML syntax error — the caller freezes the canvas
 * rather than applying a partial/wrong graph (The Invalid-YAML Freeze Rule).
 */
export function parseWorkflowYaml(text: string): { result: ParsedWorkflowYaml | null; error: ValidationIssue | null } {
  const doc = parseDocument(text)

  if (doc.errors.length > 0) {
    const err = doc.errors[0]!
    const pos = err.linePos?.[0]
    return {
      result: null,
      error: { code: 'YAML_SYNTAX', message: err.message, path: '$', line: pos?.line, column: pos?.col },
    }
  }

  const data = doc.toJS() as {
    spec?: {
      steps?: Array<{ id: string; type: string; name: string; config?: Record<string, unknown>; disabled?: boolean; timeout?: number; retry?: { attempts: number; delay: number }; on_failure?: string }>
      edges?: Array<{ from: string; to: string; on?: string; label?: string }>
    }
    layout?: Record<string, { x: number; y: number }>
    // `view:` (Faza B, plan Partea II §D2) is cosmetic-only, same spirit as
    // `layout:` — it records which side of each node an edge was manually
    // dragged from/to. Absent entirely for every workflow written before
    // Faza B, and for any edge nobody has re-pinned since: `sourceSide`/
    // `targetSide` stay undefined and the caller (WorkflowCanvas.vue)
    // falls back to today's bottom→top default, so old workflows render
    // pixel-identical to before this feature existed.
    view?: { edges?: Record<string, { from?: WorkflowHandleSide; to?: WorkflowHandleSide }> }
  } | null

  if (!data || typeof data !== 'object') {
    return { result: null, error: { code: 'YAML_SHAPE', message: 'Document must be a YAML mapping at the top level', path: '$' } }
  }

  const rawSteps = data.spec?.steps ?? []
  const rawEdges = data.spec?.edges ?? []
  const layout = data.layout ?? {}
  const viewEdges = data.view?.edges ?? {}

  const nodes: WorkflowNode[] = rawSteps.map(s => ({
    id: s.id,
    type: s.type as WorkflowNodeType,
    name: s.name,
    config: s.config ?? {},
    disabled: s.disabled,
    timeout: s.timeout,
    retry: s.retry,
    on_failure: s.on_failure as WorkflowNode['on_failure'],
    position: layout[s.id],
  }))

  const edges: WorkflowEdge[] = rawEdges.map((e) => {
    // `:` — not `-` — since step ids allow hyphens (^[a-z0-9_-]{1,64}$),
    // so `from-success-to` could collide across two differently-split
    // triples (e.g. a step literally named "x-success-y"). `:` can't
    // appear in a step id, so the triple is always unambiguous. Same key
    // `view.edges` uses below.
    const on = (e.on ?? 'success') as WorkflowEdge['on']
    const id = `${e.from}:${on}:${e.to}`
    const route = viewEdges[id]
    return {
      id, from: e.from, to: e.to, on, label: e.label,
      sourceSide: route?.from, targetSide: route?.to,
    }
  })

  return { result: { doc, nodes, edges }, error: null }
}

/**
 * Surgical edit: touches ONLY layout.<stepId>.{x,y}, preserving every
 * comment and the formatting of everything else (The Layout-Is-Cosmetic
 * Rule, plan §6 — moving a node must never touch `spec:`). Falls back to
 * appending a fresh `layout:` block if the source doesn't parse at all
 * (shouldn't happen in practice — the canvas is frozen on invalid YAML,
 * see The Invalid-YAML Freeze Rule — but this keeps the function total).
 */
export function applyLayoutPatch(yamlText: string, stepId: string, x: number, y: number): string {
  const doc = parseDocument(yamlText)
  if (doc.errors.length > 0) return yamlText

  doc.setIn(['layout', stepId, 'x'], Math.round(x))
  doc.setIn(['layout', stepId, 'y'], Math.round(y))
  return doc.toString()
}

/** spec.steps is a sequence, not a map keyed by id — every surgical step
 * edit below needs the array index for the step whose `id` field matches.
 * Returns -1 (not undefined) so callers can no-op with a single comparison
 * instead of an extra null check. */
function _findStepIndex(doc: Document, stepId: string): number {
  const steps = doc.getIn(['spec', 'steps']) as { items?: unknown[] } | undefined
  if (!steps?.items) return -1
  for (let i = 0; i < steps.items.length; i++) {
    const item = steps.items[i] as { get?: (key: string) => unknown }
    if (item?.get?.('id') === stepId) return i
  }
  return -1
}

/** `deleteIn`, unlike `setIn`/`addIn`, throws if an intermediate collection
 * on the path doesn't exist yet — `view:` is absent from every workflow
 * written before Faza B (and from any workflow where nobody has ever
 * pinned an edge), so an unguarded `deleteIn(['view','edges',key])` would
 * crash the ordinary case, not just the pinned one. */
function _deleteViewRoute(doc: Document, key: string): void {
  if (doc.hasIn(['view', 'edges'])) doc.deleteIn(['view', 'edges', key])
}

/** `doc.setIn`/`deleteIn` always re-emit the node at that path from scratch,
 * which can reformat it (flow-style → block-style, quote style) even when
 * the value being written is exactly what's already there — e.g. the
 * properties panel's per-field watchDebounced re-emitting a freshly
 * selected node's own unchanged name after its reset-from-node round trip.
 * Without this guard that "no-op" still produces a text-level diff: noise
 * in `spec:` for a human reviewing it, and a spurious workflow-store undo
 * entry that makes one Ctrl+Z revert nothing visible. */
function _valueUnchanged(doc: Document, path: (string | number)[], value: unknown): boolean {
  if (value === undefined || value === '') return !doc.hasIn(path)
  const current = doc.getIn(path) as { toJSON?: () => unknown }
  const currentJs = current && typeof current.toJSON === 'function' ? current.toJSON() : current
  return JSON.stringify(currentJs) === JSON.stringify(value)
}

/**
 * Surgical edit of ONE step-level field (name/timeout/on_failure/disabled —
 * anything that's a direct sibling of `config`, not inside it). `undefined`
 * deletes the key rather than writing a YAML null, so clearing an optional
 * field (e.g. timeout) removes the line instead of leaving `timeout: null`.
 */
export function applyStepFieldPatch(yamlText: string, stepId: string, field: string, value: unknown): string {
  const doc = parseDocument(yamlText)
  if (doc.errors.length > 0) return yamlText
  const i = _findStepIndex(doc, stepId)
  if (i === -1) return yamlText

  // Dot notation reaches nested fields — retry.attempts / retry.delay are
  // the only ones today, but this stays general rather than special-cased.
  const path = ['spec', 'steps', i, ...field.split('.')]
  if (_valueUnchanged(doc, path, value)) return yamlText
  if (value === undefined || value === '') doc.deleteIn(path)
  else doc.setIn(path, value)
  return doc.toString()
}

/** Surgical edit of ONE key inside a step's `config` block — what every
 * WorkflowNodeConfigForm.vue field writes through. */
export function applyStepConfigPatch(yamlText: string, stepId: string, key: string, value: unknown): string {
  const doc = parseDocument(yamlText)
  if (doc.errors.length > 0) return yamlText
  const i = _findStepIndex(doc, stepId)
  if (i === -1) return yamlText

  const path = ['spec', 'steps', i, 'config', key]
  if (_valueUnchanged(doc, path, value)) return yamlText
  if (value === undefined || value === '') doc.deleteIn(path)
  else doc.setIn(path, value)
  return doc.toString()
}

/** Appends a brand-new step (dropped from WorkflowPalette.vue) — the one
 * mutation here that's additive rather than surgical-on-existing, since
 * there's nothing existing to touch yet. Still respects Layout-Is-Cosmetic:
 * position goes to `layout.<id>`, never into `spec.steps[i]` itself. */
export function applyAddStep(
  yamlText: string, step: { id: string; type: string; name: string; config: Record<string, unknown> },
  position: { x: number; y: number },
): string {
  const doc = parseDocument(yamlText)
  if (doc.errors.length > 0) return yamlText

  doc.addIn(['spec', 'steps'], { id: step.id, type: step.type, name: step.name, config: step.config })
  doc.setIn(['layout', step.id, 'x'], Math.round(position.x))
  doc.setIn(['layout', step.id, 'y'], Math.round(position.y))
  return doc.toString()
}

/** Removes a step, every edge touching it (in either direction), and its
 * layout entry. Deletes edges highest-index-first — deleting a YAMLSeq
 * item by index shifts every later index, so low-to-high would skip or
 * mis-delete whichever edge landed at the now-stale index. */
/** Shared by applyRemoveStep and applyDisconnectStep — deletes every edge
 * touching stepId (either direction) plus its view.edges route pin.
 * Highest-index-first: deleting a YAMLSeq item by index shifts every later
 * index, so low-to-high would skip or mis-delete whichever edge landed at
 * the now-stale index. */
function _removeEdgesTouching(doc: Document, stepId: string): void {
  const edges = doc.getIn(['spec', 'edges']) as { items?: { get?: (key: string) => unknown }[] } | undefined
  if (!edges?.items) return
  for (let j = edges.items.length - 1; j >= 0; j--) {
    const e = edges.items[j]
    const from = e?.get?.('from'), to = e?.get?.('to')
    if (from === stepId || to === stepId) {
      doc.deleteIn(['spec', 'edges', j])
      _deleteViewRoute(doc, `${from}:${e?.get?.('on') ?? 'success'}:${to}`)
    }
  }
}

export function applyRemoveStep(yamlText: string, stepId: string): string {
  const doc = parseDocument(yamlText)
  if (doc.errors.length > 0) return yamlText
  const i = _findStepIndex(doc, stepId)
  if (i === -1) return yamlText

  doc.deleteIn(['spec', 'steps', i])
  doc.deleteIn(['layout', stepId])
  _removeEdgesTouching(doc, stepId)
  return doc.toString()
}

/** Removes every edge touching a step without removing the step itself —
 * WorkflowContextMenu.vue's "Disconnect" action (right-click a node when
 * you want to rewire it from scratch without losing its config). */
export function applyDisconnectStep(yamlText: string, stepId: string): string {
  const doc = parseDocument(yamlText)
  if (doc.errors.length > 0) return yamlText
  if (_findStepIndex(doc, stepId) === -1) return yamlText

  _removeEdgesTouching(doc, stepId)
  return doc.toString()
}

/** Appends a new edge — what dragging Handle-to-Handle on the canvas
 * produces (WorkflowCanvas.vue's onConnect). No-ops on an exact duplicate
 * (same from/to/on) rather than writing a second identical line — Vue
 * Flow itself won't visually distinguish two overlapping edges anyway. */
export function applyAddEdge(yamlText: string, from: string, to: string, on: string): string {
  const doc = parseDocument(yamlText)
  if (doc.errors.length > 0) return yamlText

  const edges = doc.getIn(['spec', 'edges']) as { items?: { get?: (key: string) => unknown }[] } | undefined
  const exists = edges?.items?.some(e => e?.get?.('from') === from && e?.get?.('to') === to && e?.get?.('on') === on)
  if (exists) return yamlText

  doc.addIn(['spec', 'edges'], { from, to, on })
  return doc.toString()
}

/** Changes an existing edge's `on` and/or `label` (WorkflowEdgeProperties.vue
 * — the panel that makes the 4-handle canvas actually useful for branching,
 * since a fresh Handle-to-Handle drag always defaults `on` to 'success').
 * Changing `on` changes the edge's frontend id and its `view.edges` key
 * (both `${from}:${on}:${to}`), so any existing route pin has to move to
 * the new key in the same pass — left behind under the old key, it would
 * silently stop applying to this edge and orphan itself in the YAML. */
export function applyUpdateEdge(
  yamlText: string, from: string, to: string, on: string, patch: { on?: string; label?: string },
): string {
  const doc = parseDocument(yamlText)
  if (doc.errors.length > 0) return yamlText

  const edges = doc.getIn(['spec', 'edges']) as { items?: { get?: (key: string) => unknown }[] } | undefined
  const j = edges?.items?.findIndex(e => e?.get?.('from') === from && e?.get?.('to') === to && e?.get?.('on') === on) ?? -1
  if (j === -1) return yamlText

  const nextOn = patch.on ?? on
  if (patch.on !== undefined) doc.setIn(['spec', 'edges', j, 'on'], patch.on)
  if (patch.label !== undefined) {
    if (patch.label === '') doc.deleteIn(['spec', 'edges', j, 'label'])
    else doc.setIn(['spec', 'edges', j, 'label'], patch.label)
  }

  if (nextOn !== on) {
    const oldKey = `${from}:${on}:${to}`
    const newKey = `${from}:${nextOn}:${to}`
    const route = doc.hasIn(['view', 'edges']) ? doc.getIn(['view', 'edges', oldKey]) : undefined
    _deleteViewRoute(doc, oldKey)
    if (route !== undefined) doc.setIn(['view', 'edges', newKey], route)
  }
  return doc.toString()
}

/** Removes one edge (matched by from/to/on — the same triple that forms
 * WorkflowEdge.id on the frontend, `${from}:${on}:${to}`). */
export function applyRemoveEdge(yamlText: string, from: string, to: string, on: string): string {
  const doc = parseDocument(yamlText)
  if (doc.errors.length > 0) return yamlText

  const edges = doc.getIn(['spec', 'edges']) as { items?: { get?: (key: string) => unknown }[] } | undefined
  if (!edges?.items) return yamlText
  for (let j = edges.items.length - 1; j >= 0; j--) {
    const e = edges.items[j]
    if (e?.get?.('from') === from && e?.get?.('to') === to && e?.get?.('on') === on) {
      doc.deleteIn(['spec', 'edges', j])
      _deleteViewRoute(doc, `${from}:${on}:${to}`)
      break
    }
  }
  return doc.toString()
}

/** Records which side of each node an edge was dragged from/to (Faza B,
 * plan Partea II §D2 — the manual-pin routing model the user chose). Lives
 * under a NEW top-level `view:` key, deliberately not `spec:` or `layout:`:
 * the side an edge attaches to is exactly as cosmetic as node position, but
 * it's a property of an EDGE, and `layout:` is typed strictly as
 * `dict[str, {x,y}]` on the backend (schemas/workflow.py) — a nested
 * `{from,to}` value there would fail validation. No Pydantic model anywhere
 * declares `extra="forbid"`, so an unknown top-level key round-trips
 * untouched; see backend `schemas/workflow.py`. */
export function applyEdgeRoutePatch(
  yamlText: string, from: string, on: string, to: string, sourceSide: string, targetSide: string,
): string {
  const doc = parseDocument(yamlText)
  if (doc.errors.length > 0) return yamlText

  const path = ['view', 'edges', `${from}:${on}:${to}`]
  const value = { from: sourceSide, to: targetSide }
  if (_valueUnchanged(doc, path, value)) return yamlText
  doc.setIn(path, value)
  return doc.toString()
}

/** Backend `WorkflowMetadata`/step id pattern (schemas/workflow.py) — kept
 * in sync by hand since this is the one shape check worth doing client-side
 * before writing to the doc at all (an id that would fail server validation
 * shouldn't even produce a local edit to undo). */
const _STEP_ID_RE = /^[a-z0-9_-]{1,64}$/

/** Renames a step's id everywhere it's referenced — the step itself, every
 * edge's `from`/`to`, its `layout:` entry, and any `view.edges` route pins
 * (keyed on the old from:on:to triple). One atomic edit, not four separate
 * store calls: a rename that updated the step but missed an edge would
 * silently orphan that edge's `from`/`to` into a dangling reference the
 * backend validator would then reject at publish, far from where the typo
 * actually happened. Written to be safe even if oldId appears as BOTH
 * from and to on the same edge (a self-loop) — from/to are read once per
 * edge before either is written. */
export function applyRenameStep(yamlText: string, oldId: string, newId: string): string {
  const doc = parseDocument(yamlText)
  if (doc.errors.length > 0) return yamlText
  if (oldId === newId || !_STEP_ID_RE.test(newId)) return yamlText
  const i = _findStepIndex(doc, oldId)
  if (i === -1 || _findStepIndex(doc, newId) !== -1) return yamlText

  doc.setIn(['spec', 'steps', i, 'id'], newId)

  if (doc.hasIn(['layout', oldId])) {
    const position = doc.getIn(['layout', oldId])
    doc.deleteIn(['layout', oldId])
    doc.setIn(['layout', newId], position)
  }

  const edges = doc.getIn(['spec', 'edges']) as { items?: { get?: (key: string) => unknown }[] } | undefined
  if (edges?.items) {
    for (let j = 0; j < edges.items.length; j++) {
      const e = edges.items[j]
      const from = e?.get?.('from') as string, to = e?.get?.('to') as string
      const on = (e?.get?.('on') as string) ?? 'success'
      if (from !== oldId && to !== oldId) continue

      if (from === oldId) doc.setIn(['spec', 'edges', j, 'from'], newId)
      if (to === oldId) doc.setIn(['spec', 'edges', j, 'to'], newId)

      const oldKey = `${from}:${on}:${to}`
      const newKey = `${from === oldId ? newId : from}:${on}:${to === oldId ? newId : to}`
      const route = doc.hasIn(['view', 'edges']) ? doc.getIn(['view', 'edges', oldKey]) : undefined
      if (route !== undefined) {
        _deleteViewRoute(doc, oldKey)
        doc.setIn(['view', 'edges', newKey], route)
      }
    }
  }

  return doc.toString()
}

/** Duplicates a step: same type/config, a fresh non-colliding id derived
 * from the original, offset +32/+32 on canvas so the copy doesn't sit
 * exactly on top of the original. Deliberately does NOT copy edges — a
 * duplicated step starts disconnected, since guessing whether the copy
 * should inherit the original's incoming edges, outgoing edges, or both
 * is exactly the kind of silent behavior a user would have to discover by
 * accident; disconnected-by-default is the one choice that never surprises. */
export function applyDuplicateStep(yamlText: string, stepId: string): { yaml: string; newId: string | null } {
  const doc = parseDocument(yamlText)
  if (doc.errors.length > 0) return { yaml: yamlText, newId: null }
  const i = _findStepIndex(doc, stepId)
  if (i === -1) return { yaml: yamlText, newId: null }

  const step = doc.getIn(['spec', 'steps', i]) as { toJSON?: () => Record<string, unknown> } | undefined
  const stepJs = step?.toJSON?.()
  if (!stepJs) return { yaml: yamlText, newId: null }

  let n = 2
  let newId = `${stepId}_copy`
  while (_findStepIndex(doc, newId) !== -1) { newId = `${stepId}_copy${n}`; n += 1 }

  const position = doc.getIn(['layout', stepId]) as { toJSON?: () => { x: number; y: number } } | undefined
  const pos = position?.toJSON?.() ?? { x: 80, y: 40 }

  doc.addIn(['spec', 'steps'], { ...stepJs, id: newId })
  doc.setIn(['layout', newId, 'x'], Math.round(pos.x + 32))
  doc.setIn(['layout', newId, 'y'], Math.round(pos.y + 32))
  return { yaml: doc.toString(), newId }
}
