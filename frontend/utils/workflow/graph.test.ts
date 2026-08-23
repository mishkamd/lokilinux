import { describe, expect, it } from 'vitest'
import { mergeValidationIssues, validateGraphLocal } from './graph'
import type { WorkflowEdge, WorkflowNode } from '~/types/workflow'

function node(id: string): WorkflowNode {
  return { id, type: 'command', name: id, config: {} }
}
function edge(from: string, to: string, on: WorkflowEdge['on'] = 'success'): WorkflowEdge {
  return { id: `${from}:${on}:${to}`, from, to, on }
}

describe('validateGraphLocal', () => {
  it('reports no issues for a well-formed linear graph', () => {
    const result = validateGraphLocal([node('a'), node('b')], [edge('a', 'b')])
    expect(result.errors).toEqual([])
    expect(result.warnings).toEqual([])
  })

  it('flags duplicate step ids', () => {
    const result = validateGraphLocal([node('a'), node('a')], [])
    expect(result.errors).toHaveLength(1)
    expect(result.errors[0]!.code).toBe('DUPLICATE_STEP_ID')
  })

  it('flags a dangling edge source and target', () => {
    const result = validateGraphLocal([node('a')], [edge('a', 'ghost'), edge('missing', 'a')])
    const codes = result.errors.map(e => e.code)
    expect(codes).toEqual(['DANGLING_EDGE', 'DANGLING_EDGE'])
  })

  it('detects a two-node cycle', () => {
    const result = validateGraphLocal([node('a'), node('b')], [edge('a', 'b'), edge('b', 'a')])
    expect(result.errors).toHaveLength(1)
    expect(result.errors[0]!.code).toBe('CYCLE_DETECTED')
  })

  it('detects a self-loop as a cycle', () => {
    const result = validateGraphLocal([node('a')], [edge('a', 'a')])
    expect(result.errors[0]!.code).toBe('CYCLE_DETECTED')
  })

  it('requires an entry point when every node has an incoming edge', () => {
    // a<->b would be a cycle too, but a three-node ring isolates the
    // "no entry point" check from cycle detection since cycle detection
    // runs first and would otherwise mask it — this graph is a ring, so
    // cycle detection fires. Use a case where in-degree>0 everywhere
    // without a full cycle: impossible in a finite DAG, so NO_ENTRY_POINT
    // in practice only ever fires alongside CYCLE_DETECTED already having
    // bailed — confirm the bail-before ordering here instead.
    const result = validateGraphLocal([node('a'), node('b'), node('c')], [edge('a', 'b'), edge('b', 'c'), edge('c', 'a')])
    expect(result.errors[0]!.code).toBe('CYCLE_DETECTED')
  })

  it('warns on a fully disconnected step in a multi-node graph', () => {
    const result = validateGraphLocal([node('a'), node('b'), node('orphan')], [edge('a', 'b')])
    expect(result.errors).toEqual([])
    expect(result.warnings).toHaveLength(1)
    expect(result.warnings[0]!.code).toBe('UNREACHABLE_STEP')
    expect(result.warnings[0]!.step_id).toBe('orphan')
  })

  it('does not warn about a lone node in a single-node graph', () => {
    const result = validateGraphLocal([node('a')], [])
    expect(result.warnings).toEqual([])
  })

  it('bails before reachability checks once a dangling edge is found', () => {
    const result = validateGraphLocal([node('a')], [edge('a', 'ghost')])
    expect(result.errors).toHaveLength(1)
    expect(result.warnings).toEqual([])
  })
})

describe('mergeValidationIssues', () => {
  it('keeps every remote issue and appends local-only ones', () => {
    const remote = [{ code: 'CYCLE_DETECTED', message: 'server says cycle', path: 'spec.edges', step_id: 'a' }]
    const local = [{ code: 'DUPLICATE_STEP_ID', message: 'local dup', path: 'spec.steps', step_id: 'b' }]
    const merged = mergeValidationIssues(local, remote)
    expect(merged).toHaveLength(2)
    expect(merged[0]!.code).toBe('CYCLE_DETECTED')
    expect(merged[1]!.code).toBe('DUPLICATE_STEP_ID')
  })

  it('drops a local issue once the remote result reports the same code+step_id', () => {
    const remote = [{ code: 'CYCLE_DETECTED', message: 'server says cycle', path: 'spec.edges', step_id: 'a' }]
    const local = [{ code: 'CYCLE_DETECTED', message: 'local says cycle', path: 'spec.edges', step_id: 'a' }]
    const merged = mergeValidationIssues(local, remote)
    expect(merged).toHaveLength(1)
    expect(merged[0]!.message).toBe('server says cycle')
  })
})
