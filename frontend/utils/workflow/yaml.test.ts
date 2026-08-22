import { describe, expect, it } from 'vitest'
import {
  applyAddEdge, applyAddStep, applyDuplicateStep, applyEdgeRoutePatch, applyLayoutPatch,
  applyRemoveEdge, applyRemoveStep, applyRenameStep,
  applyStepConfigPatch, applyStepFieldPatch, applyUpdateEdge, parseWorkflowYaml,
} from './yaml'

// Corpus fixtures — deliberately awkward YAML a human would actually write
// or that a hand-authored Git file would carry: comments, a multiline block
// scalar, unusual key order, flow-style maps. The round-trip tests below
// assert these survive a canvas edit byte-for-byte outside the touched path
// (plan §18 — "the test that matters most").

const SIMPLE = `apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: sample-flow
spec:
  targets:
    all: true
  steps:
    - id: whoami
      type: command
      name: Check identity
      config: { command: "whoami" }
    - id: gate
      type: approval
      name: Confirm proceed
      config: {}
  edges:
    - { from: whoami, to: gate, on: success }
layout:
  whoami: { x: 80, y: 40 }
  gate: { x: 80, y: 160 }
`

const COMMENTED = `# Oracle upgrade — read the runbook before touching this
apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: oracle-upgrade
  # severity drives the audit trail's default filter
  severity: HIGH
spec:
  targets:
    all: true
  steps:
    - id: precheck
      type: command
      name: Preflight
      config:
        # multiline shell block — keep the heredoc, don't collapse it
        command: |
          set -e
          echo "checking disk"
          df -h /
      timeout: 900 # seconds, not minutes
    - id: upgrade
      type: command
      name: Upgrade
      config: { command: "leapp upgrade" }
  edges:
    - { from: precheck, to: upgrade, on: success } # happy path
layout:
  precheck: { x: 80, y: 40 }
  upgrade: { x: 80, y: 160 }
`

describe('parseWorkflowYaml', () => {
  it('derives nodes/edges and defaults edge.on to success', () => {
    const { result, error } = parseWorkflowYaml(SIMPLE)
    expect(error).toBeNull()
    expect(result!.nodes.map(n => n.id)).toEqual(['whoami', 'gate'])
    expect(result!.edges).toEqual([
      { id: 'whoami:success:gate', from: 'whoami', to: 'gate', on: 'success', label: undefined },
    ])
  })

  it('reads layout into node.position', () => {
    const { result } = parseWorkflowYaml(SIMPLE)
    expect(result!.nodes[0]!.position).toEqual({ x: 80, y: 40 })
  })

  it('returns a YAML_SYNTAX error with line/column on invalid YAML, never a partial result', () => {
    const { result, error } = parseWorkflowYaml('spec:\n  steps: [\n')
    expect(result).toBeNull()
    expect(error!.code).toBe('YAML_SYNTAX')
    expect(error!.line).toBeGreaterThan(0)
  })

  it('a non-mapping top level parses to an empty graph rather than throwing', () => {
    const { result, error } = parseWorkflowYaml('- just\n- a\n- list\n')
    expect(error).toBeNull()
    expect(result!.nodes).toEqual([])
    expect(result!.edges).toEqual([])
  })

  it('an empty document reports YAML_SHAPE rather than crashing', () => {
    const { result, error } = parseWorkflowYaml('null\n')
    expect(result).toBeNull()
    expect(error!.code).toBe('YAML_SHAPE')
  })
})

describe('The Layout-Is-Cosmetic Rule — applyLayoutPatch', () => {
  it('touches only layout.<id>.{x,y}; every other line is byte-identical', () => {
    const patched = applyLayoutPatch(SIMPLE, 'gate', 500, 300)
    expect(patched).toContain('gate: { x: 500, y: 300 }')

    // Every line that isn't the layout.gate line must survive verbatim.
    const before = SIMPLE.split('\n').filter(l => !l.includes('gate: { x: 80, y: 160 }'))
    const after = patched.split('\n').filter(l => !l.includes('gate: { x: 500, y: 300 }'))
    expect(after).toEqual(before)
  })

  it('preserves comments and the multiline block scalar untouched', () => {
    const patched = applyLayoutPatch(COMMENTED, 'upgrade', 10, 20)
    expect(patched).toContain('# Oracle upgrade — read the runbook before touching this')
    expect(patched).toContain('# multiline shell block — keep the heredoc, don\'t collapse it')
    expect(patched).toContain('set -e\n          echo "checking disk"\n          df -h /')
    expect(patched).toContain('timeout: 900 # seconds, not minutes')
  })

  it('is a no-op string return on invalid YAML (Invalid-YAML Freeze Rule)', () => {
    const broken = 'spec:\n  steps: [\n'
    expect(applyLayoutPatch(broken, 'x', 1, 2)).toBe(broken)
  })
})

describe('value-unchanged guard (regression: undo/redo duplicate-commit bug)', () => {
  it('applyStepFieldPatch returns the input unchanged when the value already matches', () => {
    const once = applyStepFieldPatch(SIMPLE, 'whoami', 'name', 'Check identity')
    expect(once).toBe(SIMPLE)
  })

  it('applyStepConfigPatch returns the input unchanged when the value already matches', () => {
    const once = applyStepConfigPatch(SIMPLE, 'whoami', 'command', 'whoami')
    expect(once).toBe(SIMPLE)
  })

  it('applyStepConfigPatch is a no-op when clearing a key that was never set', () => {
    const once = applyStepConfigPatch(SIMPLE, 'gate', 'message', undefined)
    expect(once).toBe(SIMPLE)
  })

  it('still writes through when the value genuinely differs', () => {
    const patched = applyStepFieldPatch(SIMPLE, 'whoami', 'name', 'Renamed')
    expect(patched).not.toBe(SIMPLE)
    expect(parseWorkflowYaml(patched).result!.nodes[0]!.name).toBe('Renamed')
  })

  it('undefined deletes the key rather than writing a YAML null', () => {
    const withTimeout = applyStepFieldPatch(SIMPLE, 'whoami', 'timeout', 60)
    const cleared = applyStepFieldPatch(withTimeout, 'whoami', 'timeout', undefined)
    expect(cleared).not.toContain('timeout')
  })
})

describe('applyAddStep / applyRemoveStep', () => {
  it('appends a step and its layout entry without touching existing steps', () => {
    const added = applyAddStep(SIMPLE, { id: 'notify', type: 'notification', name: 'Notify', config: {} }, { x: 400, y: 40 })
    const { result } = parseWorkflowYaml(added)
    expect(result!.nodes.map(n => n.id)).toEqual(['whoami', 'gate', 'notify'])
    expect(result!.nodes[2]!.position).toEqual({ x: 400, y: 40 })
    expect(added).toContain('whoami: { x: 80, y: 40 }')
  })

  it('removes a step, its layout entry, and every edge touching it in either direction', () => {
    const removed = applyRemoveStep(SIMPLE, 'gate')
    const { result } = parseWorkflowYaml(removed)
    expect(result!.nodes.map(n => n.id)).toEqual(['whoami'])
    expect(result!.edges).toEqual([])
    expect(removed).not.toContain('gate:')
  })

  it('removeStep on an unknown id is a no-op', () => {
    expect(applyRemoveStep(SIMPLE, 'nope')).toBe(SIMPLE)
  })
})

describe('applyAddEdge / applyRemoveEdge', () => {
  it('adds an edge reachable by parseWorkflowYaml', () => {
    const added = applyAddEdge(SIMPLE, 'gate', 'whoami', 'failure')
    const { result } = parseWorkflowYaml(added)
    expect(result!.edges).toContainEqual({ id: 'gate:failure:whoami', from: 'gate', to: 'whoami', on: 'failure', label: undefined })
  })

  it('does not duplicate an exact from/to/on match', () => {
    const added = applyAddEdge(SIMPLE, 'whoami', 'gate', 'success')
    expect(added).toBe(SIMPLE)
  })

  it('two edges between the same nodes with different `on` are both kept', () => {
    const added = applyAddEdge(SIMPLE, 'whoami', 'gate', 'failure')
    const { result } = parseWorkflowYaml(added)
    expect(result!.edges).toHaveLength(2)
  })

  it('removes exactly the matching edge, leaving spec.steps and layout untouched', () => {
    const removed = applyRemoveEdge(SIMPLE, 'whoami', 'gate', 'success')
    const { result } = parseWorkflowYaml(removed)
    expect(result!.edges).toEqual([])
    expect(result!.nodes.map(n => n.id)).toEqual(['whoami', 'gate'])
    expect(removed).toContain('gate: { x: 80, y: 160 }')
  })
})

describe('Faza B — applyEdgeRoutePatch (`view:` manual edge routing)', () => {
  it('records the side under view.edges, touching neither spec: nor layout:', () => {
    const patched = applyEdgeRoutePatch(SIMPLE, 'whoami', 'success', 'gate', 'right', 'left')
    expect(patched).toContain('view:')
    const { result } = parseWorkflowYaml(patched)
    const edge = result!.edges.find(e => e.id === 'whoami:success:gate')!
    expect(edge.sourceSide).toBe('right')
    expect(edge.targetSide).toBe('left')

    // spec: and layout: content survives byte-for-byte.
    expect(patched).toContain('- { from: whoami, to: gate, on: success }')
    expect(patched).toContain('gate: { x: 80, y: 160 }')
  })

  it('an edge with no pin has undefined sourceSide/targetSide — old workflows render unchanged', () => {
    const { result } = parseWorkflowYaml(SIMPLE)
    const edge = result!.edges.find(e => e.id === 'whoami:success:gate')!
    expect(edge.sourceSide).toBeUndefined()
    expect(edge.targetSide).toBeUndefined()
  })

  it('is a no-op when the pin already matches (undo-duplicate-commit guard applies here too)', () => {
    const once = applyEdgeRoutePatch(SIMPLE, 'whoami', 'success', 'gate', 'right', 'left')
    const twice = applyEdgeRoutePatch(once, 'whoami', 'success', 'gate', 'right', 'left')
    expect(twice).toBe(once)
  })

  it('applyRemoveEdge also deletes the matching view.edges entry', () => {
    const pinned = applyEdgeRoutePatch(SIMPLE, 'whoami', 'success', 'gate', 'right', 'left')
    const removed = applyRemoveEdge(pinned, 'whoami', 'gate', 'success')
    expect(removed).not.toContain('whoami:success:gate')
  })

  it('applyRemoveStep also deletes the view.edges entry for every edge it removes', () => {
    const pinned = applyEdgeRoutePatch(SIMPLE, 'whoami', 'success', 'gate', 'right', 'left')
    const removed = applyRemoveStep(pinned, 'gate')
    expect(removed).not.toContain('whoami:success:gate')
  })

  it('applyRemoveEdge on a document with no view: section at all does not crash', () => {
    expect(() => applyRemoveEdge(SIMPLE, 'whoami', 'gate', 'success')).not.toThrow()
  })

  it('applyRemoveStep on a document with no view: section at all does not crash', () => {
    expect(() => applyRemoveStep(SIMPLE, 'gate')).not.toThrow()
  })
})

describe('applyUpdateEdge', () => {
  it('changes on without touching from/to', () => {
    const patched = applyUpdateEdge(SIMPLE, 'whoami', 'gate', 'success', { on: 'failure' })
    const { result } = parseWorkflowYaml(patched)
    expect(result!.edges).toContainEqual({ id: 'whoami:failure:gate', from: 'whoami', to: 'gate', on: 'failure', label: undefined, sourceSide: undefined, targetSide: undefined })
  })

  it('sets a label without changing on', () => {
    const patched = applyUpdateEdge(SIMPLE, 'whoami', 'gate', 'success', { label: 'happy path' })
    const { result } = parseWorkflowYaml(patched)
    expect(result!.edges.find(e => e.id === 'whoami:success:gate')!.label).toBe('happy path')
  })

  it('moves an existing view.edges route pin to the new on-based key when on changes', () => {
    const pinned = applyEdgeRoutePatch(SIMPLE, 'whoami', 'success', 'gate', 'right', 'left')
    const patched = applyUpdateEdge(pinned, 'whoami', 'gate', 'success', { on: 'failure' })
    const { result } = parseWorkflowYaml(patched)
    const edge = result!.edges.find(e => e.id === 'whoami:failure:gate')!
    expect(edge.sourceSide).toBe('right')
    expect(edge.targetSide).toBe('left')
    expect(patched).not.toContain('whoami:success:gate')
  })

  it('is a no-op on an edge that does not exist', () => {
    expect(applyUpdateEdge(SIMPLE, 'nope', 'nowhere', 'success', { on: 'failure' })).toBe(SIMPLE)
  })
})

describe('Faza B — applyRenameStep', () => {
  it('renames the step id and its layout entry', () => {
    const renamed = applyRenameStep(SIMPLE, 'whoami', 'identity-check')
    const { result } = parseWorkflowYaml(renamed)
    expect(result!.nodes.map(n => n.id)).toEqual(['identity-check', 'gate'])
    expect(result!.nodes[0]!.position).toEqual({ x: 80, y: 40 })
  })

  it('rewrites every edge referencing the old id, both from and to', () => {
    const withExtra = applyAddEdge(SIMPLE, 'gate', 'whoami', 'failure')
    const renamed = applyRenameStep(withExtra, 'whoami', 'identity-check')
    const { result } = parseWorkflowYaml(renamed)
    expect(result!.edges.map(e => e.id).sort()).toEqual([
      'gate:failure:identity-check', 'identity-check:success:gate',
    ])
  })

  it('moves a view.edges route pin to the renamed key', () => {
    const pinned = applyEdgeRoutePatch(SIMPLE, 'whoami', 'success', 'gate', 'right', 'left')
    const renamed = applyRenameStep(pinned, 'whoami', 'identity-check')
    const { result } = parseWorkflowYaml(renamed)
    const edge = result!.edges.find(e => e.id === 'identity-check:success:gate')!
    expect(edge.sourceSide).toBe('right')
    expect(edge.targetSide).toBe('left')
  })

  it('rejects a duplicate id — no-op, not a silent collision', () => {
    expect(applyRenameStep(SIMPLE, 'whoami', 'gate')).toBe(SIMPLE)
  })

  it('rejects an id that fails the step-id pattern', () => {
    expect(applyRenameStep(SIMPLE, 'whoami', 'Not Valid!')).toBe(SIMPLE)
  })

  it('is a no-op renaming to the same id', () => {
    expect(applyRenameStep(SIMPLE, 'whoami', 'whoami')).toBe(SIMPLE)
  })

  it('is a no-op on an unknown step id', () => {
    expect(applyRenameStep(SIMPLE, 'nope', 'new-id')).toBe(SIMPLE)
  })
})

describe('Faza B — applyDuplicateStep', () => {
  it('copies type/config with a fresh id, offset position, and no edges', () => {
    const { yaml, newId } = applyDuplicateStep(SIMPLE, 'whoami')
    expect(newId).toBe('whoami_copy')
    const { result } = parseWorkflowYaml(yaml)
    const copy = result!.nodes.find(n => n.id === 'whoami_copy')!
    expect(copy.type).toBe('command')
    expect(copy.config).toEqual({ command: 'whoami' })
    expect(copy.position).toEqual({ x: 112, y: 72 })
    expect(result!.edges).toHaveLength(1) // unchanged — the copy isn't wired to anything
  })

  it('picks a non-colliding id when the first candidate is taken', () => {
    const once = applyDuplicateStep(SIMPLE, 'whoami').yaml
    const { newId } = applyDuplicateStep(once, 'whoami')
    expect(newId).toBe('whoami_copy2')
  })

  it('returns the input unchanged and newId null on an unknown step id', () => {
    const result = applyDuplicateStep(SIMPLE, 'nope')
    expect(result.yaml).toBe(SIMPLE)
    expect(result.newId).toBeNull()
  })
})

describe('every apply* is a no-op on invalid YAML', () => {
  const broken = 'spec:\n  steps: [\n'

  it.each([
    ['applyStepFieldPatch', () => applyStepFieldPatch(broken, 'x', 'name', 'y')],
    ['applyStepConfigPatch', () => applyStepConfigPatch(broken, 'x', 'k', 'v')],
    ['applyAddStep', () => applyAddStep(broken, { id: 'x', type: 'command', name: 'X', config: {} }, { x: 0, y: 0 })],
    ['applyRemoveStep', () => applyRemoveStep(broken, 'x')],
    ['applyAddEdge', () => applyAddEdge(broken, 'a', 'b', 'success')],
    ['applyRemoveEdge', () => applyRemoveEdge(broken, 'a', 'b', 'success')],
    ['applyEdgeRoutePatch', () => applyEdgeRoutePatch(broken, 'a', 'success', 'b', 'right', 'left')],
    ['applyUpdateEdge', () => applyUpdateEdge(broken, 'a', 'b', 'success', { on: 'failure' })],
    ['applyRenameStep', () => applyRenameStep(broken, 'a', 'b')],
  ])('%s returns the input unchanged', (_name, fn) => {
    expect(fn()).toBe(broken)
  })

  it('applyDuplicateStep returns the input unchanged and newId null', () => {
    const result = applyDuplicateStep(broken, 'a')
    expect(result.yaml).toBe(broken)
    expect(result.newId).toBeNull()
  })
})
