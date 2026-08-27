// Partea III of the migration plan — 14 capability-based node types across
// 6 categories, plus 2 permanent legacy aliases (validation/wait_for_agent)
// kept because PUBLISHED workflow_versions.yaml_source is immutable — see
// schemas/workflow.py's WorkflowNodeType docstring for the full rationale.
export type WorkflowNodeType =
  // Flow
  | 'start' | 'end'
  // Execution
  | 'command' | 'ansible'
  // Linux
  | 'package' | 'service' | 'file' | 'system'
  // Control
  | 'condition' | 'approval' | 'wait'
  // Validation
  | 'check'
  // Integration
  | 'notification' | 'webhook'
  // Legacy aliases — permanent
  | 'validation' | 'wait_for_agent'

export interface WorkflowNodeRetry {
  attempts: number
  delay: number
}

export interface WorkflowNode {
  id: string
  type: WorkflowNodeType
  name: string
  config: Record<string, unknown>
  disabled?: boolean
  timeout?: number
  retry?: WorkflowNodeRetry
  on_failure?: 'stop' | 'continue' | 'branch'
  // Canvas position — lives under `layout:` in the YAML, never under `spec:`
  // (The Layout-Is-Cosmetic Rule, plan §6). Absent until an auto-layout or
  // a drag has placed it.
  position?: { x: number; y: number }
}

export type WorkflowEdgeCondition = 'success' | 'failure' | 'always'

export type WorkflowHandleSide = 'top' | 'right' | 'bottom' | 'left'

export interface WorkflowEdge {
  id: string
  from: string
  to: string
  on: WorkflowEdgeCondition
  label?: string
  // Manual routing pin (Faza B, plan Partea II §D2), from `view.edges` in
  // the YAML. Undefined for any edge nobody has re-pinned — the canvas
  // falls back to bottom→top, today's only behavior, so an old workflow
  // renders identically before and after this feature.
  sourceSide?: WorkflowHandleSide
  targetSide?: WorkflowHandleSide
}

export type WorkflowStepRunStatus =
  | 'PENDING' | 'RUNNING' | 'WAITING_APPROVAL'
  | 'SUCCEEDED' | 'FAILED' | 'SKIPPED' | 'CANCELLED'

export interface WorkflowStepRun {
  id: string
  run_id: string
  step_id: string
  status: WorkflowStepRunStatus
  attempt: number
  job_id: string | null
  started_at: string | null
  completed_at: string | null
  output: Record<string, unknown> | null
  error: string | null
}

export type WorkflowRunStatus = 'PENDING' | 'RUNNING' | 'WAITING_APPROVAL' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED'

export interface WorkflowRun {
  id: string
  workflow_id: string
  workflow_version_id: string
  status: WorkflowRunStatus
  trigger_type: string
  triggered_by: string | null
  targets: { agent_ids: string[] }
  vars: Record<string, unknown>
  is_dry_run: boolean
  started_at: string | null
  completed_at: string | null
  error: string | null
  created_at: string
}

export interface WorkflowRunDetail extends WorkflowRun {
  step_runs: WorkflowStepRun[]
}

export interface WorkflowVersion {
  id: string
  workflow_id: string
  version: number
  yaml_source: string
  graph: CompiledGraph
  content_hash: string
  status: 'DRAFT' | 'PUBLISHED' | 'ARCHIVED'
  change_summary: string | null
  created_by: string | null
  created_at: string
  published_at: string | null
}

export interface Workflow {
  id: string
  name: string
  slug: string
  description: string | null
  is_enabled: boolean
  current_version_id: string | null
  trigger_type: 'MANUAL' | 'SCHEDULE'
  cron_expr: string | null
  next_run_at: string | null
  last_run_at: string | null
  priority: number
  severity: string | null
  tags: string[]
  migrated_from_policy_id: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface WorkflowDetail extends Workflow {
  current_version: WorkflowVersion | null
}

// The parsed spec.steps/spec.edges shape the backend compiler produces
// (CompiledGraph, schemas/workflow.py) — what workflow_versions.graph holds.
export interface CompiledGraph {
  targets: Record<string, unknown>
  strategy: { mode: string; batch_size?: number | null }
  defaults: { timeout?: number | null; on_failure?: string | null }
  vars: Record<string, unknown>
  steps: Array<{
    id: string
    type: WorkflowNodeType
    name: string
    config: Record<string, unknown>
    disabled?: boolean
    timeout?: number | null
    retry?: WorkflowNodeRetry | null
    on_failure?: string | null
  }>
  edges: Array<{ from: string; to: string; on: WorkflowEdgeCondition; label?: string | null }>
  entry_ids: string[]
  layout: Record<string, { x: number; y: number }>
}

export interface ValidationIssue {
  code: string
  message: string
  path: string
  line?: number | null
  column?: number | null
  step_id?: string | null
}

export interface DryRunStepResult {
  id: string
  type: string
  eligible: number
  blocked: number
  reasons: Record<string, number>
}

export interface DryRunResponse {
  targets_matched: number
  targets: string[]
  steps: DryRunStepResult[]
  estimated_dispatch_seconds: number
  requires_approval_at: string[]
}
