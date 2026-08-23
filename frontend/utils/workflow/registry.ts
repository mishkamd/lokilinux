import {
  Play, Flag, Terminal, Bot, Package, Settings, FileText, Server,
  GitBranch, UserCheck, Clock, ShieldCheck, Bell, Webhook,
} from 'lucide-vue-next'
import type { Component } from 'vue'
import type { WorkflowNodeType } from '~/types/workflow'

// Tone follows the same red/green/blue/amber/orange/gray vocabulary as the
// rest of the app (DESIGN.md's "One Accent Rule" — every non-brand color on
// screen is load-bearing status information). A node's tone here is about
// its ROLE (control-flow vs. execution vs. human-gate), not live run status
// — run status painting (SUCCEEDED/FAILED/RUNNING) is a separate concern
// layered on top by the node component, not baked into the registry.
export type NodeTone = 'green' | 'red' | 'blue' | 'amber' | 'orange' | 'gray'

export type NodeCategory = 'flow' | 'execution' | 'linux' | 'control' | 'validation' | 'integration'

export const CATEGORY_LABEL: Record<NodeCategory, string> = {
  flow: 'Flow',
  execution: 'Execution',
  linux: 'Linux',
  control: 'Control',
  validation: 'Validation',
  integration: 'Integration',
}

export type FieldType = 'text' | 'textarea' | 'number' | 'select' | 'json' | 'playbook' | 'list'

export interface FieldSpec {
  /** Dot path under the step's `config` — WorkflowNodeConfigForm.vue reads
   * and writes config[key] directly, never spec.steps[i] itself (those are
   * step-level fields — name/timeout/retry/on_failure/disabled — handled
   * once, generically, by WorkflowProperties.vue for every node type). */
  key: string
  label: string
  type: FieldType
  help?: string
  placeholder?: string
  options?: { label: string; value: string }[]
  /** Shown only when another field in the SAME config currently holds one
   * of these values. Evaluated against the form's local (unsaved) state so
   * the panel reacts instantly when `action`/`type`/`mode` changes. */
  showIf?: { key: string; equals: string[] }
  required?: boolean
}

export interface NodeDefinition {
  type: WorkflowNodeType
  category: NodeCategory
  label: string
  tone: NodeTone
  icon: Component
  description: string
  /** True once services/workflow_engine.py can actually execute this type.
   * Notification/webhook stay false until Etapa 4 wires real dispatch —
   * the Honest Palette Rule extends to compiled operations too. */
  executable: boolean
  /** validation/wait_for_agent — permanent backend aliases for check/wait,
   * kept only so a PUBLISHED workflow referencing them still renders.
   * Never shown in the palette (WorkflowPalette.vue filters these out). */
  legacy?: boolean
  /** Drives WorkflowNodeConfigForm.vue — one generic renderer for all 14
   * types (The One Node Shell Rule's form-side counterpart). A new node
   * type needs a registry entry + a compile-down translation, never a new
   * .vue component. */
  fields: FieldSpec[]
}

const CHECK_TYPE_OPTIONS = [
  { label: 'Command', value: 'command' },
  { label: 'Service', value: 'service' },
  { label: 'Port', value: 'port' },
  { label: 'Package', value: 'package' },
  { label: 'File', value: 'file' },
  { label: 'Process', value: 'process' },
  { label: 'OS', value: 'os' },
  { label: 'Disk', value: 'disk' },
  { label: 'Network', value: 'network' },
]

const CHECK_FIELDS: FieldSpec[] = [
  { key: 'type', label: 'Check type', type: 'select', options: CHECK_TYPE_OPTIONS, required: true },
  { key: 'command', label: 'Command', type: 'textarea', showIf: { key: 'type', equals: ['command'] } },
  { key: 'service', label: 'Service name', type: 'text', showIf: { key: 'type', equals: ['service'] } },
  { key: 'host', label: 'Host', type: 'text', placeholder: 'localhost', showIf: { key: 'type', equals: ['port', 'network'] } },
  { key: 'port', label: 'Port', type: 'number', showIf: { key: 'type', equals: ['port'] } },
  { key: 'name', label: 'Package/process name', type: 'text', showIf: { key: 'type', equals: ['package', 'process'] } },
  { key: 'path', label: 'Path', type: 'text', showIf: { key: 'type', equals: ['file'] } },
  { key: 'state', label: 'Expected state', type: 'select', showIf: { key: 'type', equals: ['file'] }, options: [
    { label: 'Exists', value: 'exists' }, { label: 'Is a file', value: 'file' }, { label: 'Is a directory', value: 'directory' },
  ] },
  { key: 'distro', label: 'Distro', type: 'text', showIf: { key: 'type', equals: ['os'] } },
  { key: 'version', label: 'Version', type: 'text', showIf: { key: 'type', equals: ['os'] } },
  { key: 'min_free_gb', label: 'Minimum free GB', type: 'number', showIf: { key: 'type', equals: ['disk'] } },
  { key: 'expect_exit_code', label: 'Expected exit code', type: 'number' },
]

export const NODE_REGISTRY: Record<WorkflowNodeType, NodeDefinition> = {
  // ── Flow ──────────────────────────────────────────────────────────────
  start: {
    type: 'start', category: 'flow', label: 'Start', tone: 'gray', icon: Play,
    description: 'Entry point. Always succeeds immediately — no Job, no agent.',
    executable: true,
    fields: [],
  },
  end: {
    type: 'end', category: 'flow', label: 'End', tone: 'gray', icon: Flag,
    description: 'Terminal marker for a branch. Outcome decides whether the run reads as succeeded or failed.',
    executable: true,
    fields: [
      { key: 'outcome', label: 'Outcome', type: 'select', options: [
        { label: 'Success', value: 'success' }, { label: 'Failure', value: 'failure' }, { label: 'Cancelled', value: 'cancelled' },
      ] },
    ],
  },

  // ── Execution ─────────────────────────────────────────────────────────
  command: {
    type: 'command', category: 'execution', label: 'Command', tone: 'blue', icon: Terminal,
    description: 'Runs a shell command on each target agent.',
    executable: true,
    fields: [
      { key: 'command', label: 'Command', type: 'textarea', placeholder: 'systemctl restart nginx', required: true },
    ],
  },
  ansible: {
    type: 'ansible', category: 'execution', label: 'Ansible', tone: 'blue', icon: Bot,
    description: 'Runs a playbook on each target agent (--connection=local).',
    executable: true,
    fields: [
      { key: 'playbook_id', label: 'Playbook', type: 'playbook', required: true },
      { key: 'extra_vars', label: 'Extra vars', type: 'json', help: 'JSON object merged over the playbook’s own defaults.' },
    ],
  },

  // ── Linux ─────────────────────────────────────────────────────────────
  package: {
    type: 'package', category: 'linux', label: 'Package', tone: 'blue', icon: Package,
    description: 'Install/update dispatch to the native package module; remove compiles to shell.',
    executable: true,
    fields: [
      { key: 'action', label: 'Action', type: 'select', required: true, options: [
        { label: 'Install', value: 'install' }, { label: 'Update', value: 'update' }, { label: 'Remove', value: 'remove' },
      ] },
      { key: 'packages', label: 'Packages', type: 'list', placeholder: 'nginx' },
    ],
  },
  service: {
    type: 'service', category: 'linux', label: 'Service', tone: 'blue', icon: Settings,
    description: 'systemctl start/stop/restart/reload/enable/disable a unit.',
    executable: true,
    fields: [
      { key: 'action', label: 'Action', type: 'select', required: true, options: [
        { label: 'Start', value: 'start' }, { label: 'Stop', value: 'stop' }, { label: 'Restart', value: 'restart' },
        { label: 'Reload', value: 'reload' }, { label: 'Enable', value: 'enable' }, { label: 'Disable', value: 'disable' },
      ] },
      { key: 'name', label: 'Service name', type: 'text', placeholder: 'nginx', required: true },
    ],
  },
  file: {
    type: 'file', category: 'linux', label: 'File', tone: 'blue', icon: FileText,
    description: 'Create, copy, delete, or change ownership/mode of a file on each target agent.',
    executable: true,
    fields: [
      { key: 'action', label: 'Action', type: 'select', required: true, options: [
        { label: 'Create', value: 'create' }, { label: 'Template', value: 'template' }, { label: 'Copy', value: 'copy' },
        { label: 'Delete', value: 'delete' }, { label: 'Chmod', value: 'chmod' }, { label: 'Chown', value: 'chown' },
      ] },
      { key: 'path', label: 'Path', type: 'text', required: true },
      { key: 'content', label: 'Content', type: 'textarea', showIf: { key: 'action', equals: ['create', 'template'] } },
      { key: 'source', label: 'Source path', type: 'text', showIf: { key: 'action', equals: ['copy'] } },
      { key: 'mode', label: 'Mode', type: 'text', placeholder: '0644', showIf: { key: 'action', equals: ['chmod', 'create', 'template'] } },
      { key: 'owner', label: 'Owner', type: 'text', showIf: { key: 'action', equals: ['chown'] } },
      { key: 'group', label: 'Group', type: 'text', showIf: { key: 'action', equals: ['chown'] } },
    ],
  },
  system: {
    type: 'system', category: 'linux', label: 'System', tone: 'blue', icon: Server,
    description: 'Reboot, shutdown, hostname, timezone, or a single sysctl key.',
    executable: true,
    fields: [
      { key: 'action', label: 'Action', type: 'select', required: true, options: [
        { label: 'Reboot', value: 'reboot' }, { label: 'Shutdown', value: 'shutdown' }, { label: 'Set hostname', value: 'hostname' },
        { label: 'Set timezone', value: 'timezone' }, { label: 'Set sysctl key', value: 'sysctl' },
      ] },
      { key: 'delay_seconds', label: 'Delay before action (seconds)', type: 'number', placeholder: '5', showIf: { key: 'action', equals: ['reboot', 'shutdown'] } },
      { key: 'value', label: 'Value', type: 'text', showIf: { key: 'action', equals: ['hostname', 'timezone'] } },
      { key: 'key', label: 'sysctl key', type: 'text', placeholder: 'net.ipv4.ip_forward', showIf: { key: 'action', equals: ['sysctl'] } },
    ],
  },

  // ── Control ───────────────────────────────────────────────────────────
  condition: {
    type: 'condition', category: 'control', label: 'Condition', tone: 'orange', icon: GitBranch,
    description: 'Evaluates an AST-whitelisted expression (no Job, no agent) — true takes the on: success edge, false takes on: failure.',
    executable: true,
    fields: [
      { key: 'expression', label: 'Expression', type: 'text', placeholder: 'steps.upgrade.status == "SUCCEEDED"', required: true },
    ],
  },
  approval: {
    type: 'approval', category: 'control', label: 'Approval', tone: 'amber', icon: UserCheck,
    description: 'Pauses the run for a human decision before continuing.',
    executable: true,
    fields: [
      { key: 'message', label: 'Message shown to the approver', type: 'textarea' },
    ],
  },
  wait: {
    type: 'wait', category: 'control', label: 'Wait', tone: 'gray', icon: Clock,
    description: 'Waits on a fixed duration, or for a fresh agent heartbeat — e.g. after a reboot step.',
    executable: true,
    fields: [
      { key: 'mode', label: 'Mode', type: 'select', required: true, options: [
        { label: 'Agent heartbeat', value: 'agent' }, { label: 'Fixed duration', value: 'duration' },
      ] },
      { key: 'seconds', label: 'Duration (seconds)', type: 'number', showIf: { key: 'mode', equals: ['duration'] } },
      { key: 'min_heartbeats', label: 'Minimum heartbeat intervals', type: 'number', showIf: { key: 'mode', equals: ['agent'] } },
      { key: 'timeout_seconds', label: 'Timeout (seconds)', type: 'number', showIf: { key: 'mode', equals: ['agent'] } },
    ],
  },

  // ── Validation ────────────────────────────────────────────────────────
  check: {
    type: 'check', category: 'validation', label: 'Check', tone: 'green', icon: ShieldCheck,
    description: 'One extensible node for every state assertion — command, service, port, package, file, process, OS, disk, network.',
    executable: true,
    fields: CHECK_FIELDS,
  },

  // ── Integration ───────────────────────────────────────────────────────
  notification: {
    type: 'notification', category: 'integration', label: 'Notification', tone: 'gray', icon: Bell,
    description: 'Creates an Alert, delivered by email/Slack via NotificationWorker if configured under Settings.',
    executable: true,
    fields: [
      { key: 'subject', label: 'Subject', type: 'text' },
      { key: 'message', label: 'Message', type: 'textarea' },
    ],
  },
  webhook: {
    type: 'webhook', category: 'integration', label: 'Webhook', tone: 'gray', icon: Webhook,
    description: 'POSTs synchronously to an external URL.',
    executable: true,
    fields: [
      { key: 'url', label: 'URL', type: 'text', placeholder: 'https://example.com/hook' },
      { key: 'method', label: 'Method', type: 'select', options: [
        { label: 'POST', value: 'POST' }, { label: 'PUT', value: 'PUT' }, { label: 'GET', value: 'GET' },
      ] },
      { key: 'headers', label: 'Headers', type: 'json' },
      { key: 'body', label: 'Body', type: 'json' },
      { key: 'timeout', label: 'Timeout (seconds)', type: 'number' },
    ],
  },

  // ── Legacy aliases — never shown in the palette, only ever loaded from
  // an existing PUBLISHED workflow. See WorkflowNodeType's own comment.
  validation: {
    type: 'validation', category: 'validation', label: 'Validation', tone: 'green', icon: ShieldCheck,
    description: 'Legacy alias for Check (type: command) — kept so published workflows keep rendering.',
    executable: true, legacy: true,
    fields: [
      { key: 'command', label: 'Command', type: 'textarea' },
      { key: 'expect_exit_code', label: 'Expected exit code', type: 'number' },
    ],
  },
  wait_for_agent: {
    type: 'wait_for_agent', category: 'control', label: 'Wait for Agent', tone: 'gray', icon: Clock,
    description: 'Legacy alias for Wait (mode: agent) — kept so published workflows keep rendering.',
    executable: true, legacy: true,
    fields: [
      { key: 'timeout_seconds', label: 'Timeout (seconds)', type: 'number' },
      { key: 'min_heartbeats', label: 'Minimum consecutive heartbeats', type: 'number' },
    ],
  },
}

export function nodeDefinition(type: WorkflowNodeType): NodeDefinition {
  return NODE_REGISTRY[type] ?? NODE_REGISTRY.command
}

export const TONE_BG: Record<NodeTone, string> = {
  green: 'bg-[color-mix(in_oklch,var(--success)_15%,transparent)] text-success',
  red: 'bg-[color-mix(in_oklch,var(--destructive)_15%,transparent)] text-destructive',
  blue: 'bg-[color-mix(in_oklch,var(--info)_15%,transparent)] text-info',
  amber: 'bg-[color-mix(in_oklch,var(--warning)_15%,transparent)] text-warning',
  orange: 'bg-orange-500/15 text-[var(--severity-high)]',
  gray: 'bg-muted text-muted-foreground',
}

export const TONE_BORDER: Record<NodeTone, string> = {
  green: 'border-success/40',
  red: 'border-destructive/40',
  blue: 'border-info/40',
  amber: 'border-warning/40',
  orange: 'border-[var(--severity-high)]/40',
  gray: 'border-border',
}
