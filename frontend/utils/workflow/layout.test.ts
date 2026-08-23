import { describe, expect, it } from 'vitest'
import { computeAutoLayout } from './layout'
import type { WorkflowEdge, WorkflowNode } from '~/types/workflow'

function node(id: string): WorkflowNode {
  return { id, type: 'command', name: id, config: {} }
}
function edge(from: string, to: string): WorkflowEdge {
  return { id: `${from}:success:${to}`, from, to, on: 'success' }
}

describe('computeAutoLayout', () => {
  it('places a linear chain in one column, one row per step', () => {
    const positions = computeAutoLayout([node('a'), node('b'), node('c')], [edge('a', 'b'), edge('b', 'c')])
    expect(positions.a).toEqual({ x: 80, y: 40 })
    expect(positions.b).toEqual({ x: 80, y: 160 })
    expect(positions.c).toEqual({ x: 80, y: 280 })
  })

  it('places a fan-out on the same row, different columns', () => {
    const positions = computeAutoLayout([node('a'), node('b'), node('c')], [edge('a', 'b'), edge('a', 'c')])
    expect(positions.a!.y).toBe(40)
    expect(positions.b!.y).toBe(160)
    expect(positions.c!.y).toBe(160)
    expect(positions.b!.x).not.toBe(positions.c!.x)
  })

  it('places an isolated node with no edges at the origin row', () => {
    const positions = computeAutoLayout([node('lonely')], [])
    expect(positions.lonely).toEqual({ x: 80, y: 40 })
  })

  it('is deterministic across repeated calls on the same input', () => {
    const nodes = [node('a'), node('b'), node('c'), node('d')]
    const edges = [edge('a', 'b'), edge('a', 'c'), edge('b', 'd'), edge('c', 'd')]
    const first = computeAutoLayout(nodes, edges)
    const second = computeAutoLayout(nodes, edges)
    expect(second).toEqual(first)
  })

  it('degrades a cycle to layer 0 instead of looping', () => {
    const positions = computeAutoLayout([node('a'), node('b')], [edge('a', 'b'), edge('b', 'a')])
    expect(positions.a).toBeDefined()
    expect(positions.b).toBeDefined()
  })

  it('ignores dangling edges referencing an unknown step', () => {
    const positions = computeAutoLayout([node('a')], [edge('a', 'ghost')])
    expect(positions.a).toEqual({ x: 80, y: 40 })
    expect(positions.ghost).toBeUndefined()
  })
})
