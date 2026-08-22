import type { WorkflowEdge, WorkflowNode } from '~/types/workflow'

/**
 * Deterministic auto-layout (plan §6) for a workflow imported from Git with
 * no `layout:` block, or any node dropped/added without an explicit
 * position. Same YAML always produces the same layout — required so
 * "auto-layout" never shows up as noise in a diff. Longest-path layering
 * (row = distance from the nearest entry point) → barycenter ordering
 * within each row (column = average position of already-placed
 * predecessors) → fixed grid spacing. Best-effort and cosmetic only: a
 * cycle degrades gracefully (falls back to layer 0) rather than looping —
 * validateGraphLocal (graph.ts) is what actually rejects cycles.
 */

const ROW_HEIGHT = 120
const COL_WIDTH = 260
const BASE_X = 80
const BASE_Y = 40

export function computeAutoLayout(nodes: WorkflowNode[], edges: WorkflowEdge[]): Record<string, { x: number; y: number }> {
  const ids = nodes.map(n => n.id)
  const idSet = new Set(ids)
  const incoming = new Map<string, string[]>()
  for (const id of ids) incoming.set(id, [])
  for (const e of edges) {
    if (idSet.has(e.from) && idSet.has(e.to)) incoming.get(e.to)!.push(e.from)
  }

  const layer = new Map<string, number>()
  const visiting = new Set<string>()
  function layerOf(id: string): number {
    if (layer.has(id)) return layer.get(id)!
    if (visiting.has(id)) return 0 // cycle guard — cosmetic fallback, not a validity check
    visiting.add(id)
    const preds = incoming.get(id) ?? []
    const value = preds.length === 0 ? 0 : 1 + Math.max(...preds.map(layerOf))
    visiting.delete(id)
    layer.set(id, value)
    return value
  }
  for (const id of ids) layerOf(id)

  const byLayer = new Map<number, string[]>()
  for (const id of ids) {
    const l = layer.get(id)!
    if (!byLayer.has(l)) byLayer.set(l, [])
    byLayer.get(l)!.push(id)
  }

  const orderIndex = new Map<string, number>()
  function barycenter(id: string): number {
    const preds = (incoming.get(id) ?? []).map(p => orderIndex.get(p)).filter((v): v is number => v !== undefined)
    if (!preds.length) return orderIndex.get(id) ?? 0 // no placed predecessors yet — keep original (stable) order
    return preds.reduce((a, b) => a + b, 0) / preds.length
  }

  for (const l of [...byLayer.keys()].sort((a, b) => a - b)) {
    const layerIds = byLayer.get(l)!
    // Array.prototype.sort is stable (ES2019+) — ties keep the original
    // (already-deterministic) node order, so this never varies across runs.
    layerIds.sort((a, b) => barycenter(a) - barycenter(b))
    layerIds.forEach((id, i) => orderIndex.set(id, i))
  }

  const positions: Record<string, { x: number; y: number }> = {}
  for (const id of ids) {
    positions[id] = {
      x: BASE_X + (orderIndex.get(id) ?? 0) * COL_WIDTH,
      y: BASE_Y + (layer.get(id) ?? 0) * ROW_HEIGHT,
    }
  }
  return positions
}
