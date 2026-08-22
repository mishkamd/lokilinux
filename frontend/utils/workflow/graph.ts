import type { ValidationIssue, WorkflowEdge, WorkflowNode } from '~/types/workflow'

/**
 * Level 1 validation (plan §13) — pure client-side graph checks that mirror
 * a subset of the backend's validate_graph (workflow_compiler.py): duplicate
 * ids, dangling edges, cycles, missing entry point, unreachable steps.
 * Runs on every mutation for <16ms feedback; the backend's `/workflows/validate`
 * (800ms debounced) stays authoritative — this exists purely so a broken
 * graph doesn't wait 800ms to show red, not to replace the server check.
 */

export interface LocalValidationResult {
  errors: ValidationIssue[]
  warnings: ValidationIssue[]
}

export function validateGraphLocal(nodes: WorkflowNode[], edges: WorkflowEdge[]): LocalValidationResult {
  const errors: ValidationIssue[] = []
  const warnings: ValidationIssue[] = []

  const seen = new Set<string>()
  const duplicates = new Set<string>()
  for (const n of nodes) {
    if (seen.has(n.id)) duplicates.add(n.id)
    seen.add(n.id)
  }
  for (const id of duplicates) {
    errors.push({ code: 'DUPLICATE_STEP_ID', message: `Step id '${id}' is declared twice`, path: 'spec.steps', step_id: id })
  }

  const validIds = new Set(nodes.map(n => n.id))
  const adjacency = new Map<string, { to: string; on: string }[]>()
  const incoming = new Map<string, number>()
  for (const id of validIds) {
    adjacency.set(id, [])
    incoming.set(id, 0)
  }
  for (const e of edges) {
    if (!validIds.has(e.from)) {
      errors.push({ code: 'DANGLING_EDGE', message: `Edge source '${e.from}' has no matching step`, path: 'spec.edges' })
    }
    if (!validIds.has(e.to)) {
      errors.push({ code: 'DANGLING_EDGE', message: `Edge target '${e.to}' has no matching step`, path: 'spec.edges' })
    }
    if (validIds.has(e.from) && validIds.has(e.to)) {
      adjacency.get(e.from)!.push({ to: e.to, on: e.on })
      incoming.set(e.to, (incoming.get(e.to) ?? 0) + 1)
    }
  }
  // Cycle/reachability analysis assumes a well-formed edge list — same
  // bail-before reasoning as the backend's validate_graph.
  if (errors.length) return { errors, warnings }

  const WHITE = 0, GRAY = 1, BLACK = 2
  const color = new Map<string, number>()
  for (const id of validIds) color.set(id, WHITE)
  let cycleStep: string | null = null

  function dfs(node: string): boolean {
    color.set(node, GRAY)
    for (const { to } of adjacency.get(node) ?? []) {
      if (color.get(to) === GRAY) {
        cycleStep = to
        return true
      }
      if (color.get(to) === WHITE && dfs(to)) return true
    }
    color.set(node, BLACK)
    return false
  }

  for (const id of validIds) {
    if (color.get(id) === WHITE && dfs(id)) {
      errors.push({
        code: 'CYCLE_DETECTED', message: `Step '${cycleStep}' is part of a cycle — workflows must be a DAG`,
        path: 'spec.edges', step_id: cycleStep ?? undefined,
      })
      break
    }
  }
  if (errors.length) return { errors, warnings }

  const entryIds = [...validIds].filter(id => (incoming.get(id) ?? 0) === 0)
  if (nodes.length > 0 && entryIds.length === 0) {
    errors.push({ code: 'NO_ENTRY_POINT', message: 'Every step has an incoming edge — a workflow needs at least one entry point', path: 'spec.edges' })
    return { errors, warnings }
  }

  // Orphan detection: a step with neither incoming nor outgoing edges will
  // never run. Not the same as "unreachable from an entry point" — in an
  // acyclic graph every node has a path back to some in-degree-0 node, so
  // that broader check can never actually fire (see backend's comment).
  if (nodes.length > 1) {
    for (const id of validIds) {
      if ((incoming.get(id) ?? 0) === 0 && (adjacency.get(id)?.length ?? 0) === 0) {
        warnings.push({ code: 'UNREACHABLE_STEP', message: `Step '${id}' has no connections — it will never run`, path: `spec.steps.${id}`, step_id: id })
      }
    }
  }

  return { errors, warnings }
}

/** Merges local (instant) issues with remote (authoritative, debounced)
 * ones for display — every remote issue always shows; a local issue is
 * dropped once the remote check reports the same (code, step_id) pair, so
 * the instant feedback doesn't linger as a visual duplicate once the
 * 800ms server round-trip catches up. */
export function mergeValidationIssues(local: ValidationIssue[], remote: ValidationIssue[]): ValidationIssue[] {
  const remoteKeys = new Set(remote.map(i => `${i.code}:${i.step_id ?? ''}`))
  const localOnly = local.filter(i => !remoteKeys.has(`${i.code}:${i.step_id ?? ''}`))
  return [...remote, ...localOnly]
}
