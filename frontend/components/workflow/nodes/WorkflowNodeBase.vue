<script setup lang="ts">
import { Handle, Position } from '@vue-flow/core'
import { AlertTriangle, CheckCircle2, XCircle, Loader2, UserCheck2, MinusCircle, Ban } from 'lucide-vue-next'
import { nodeDefinition, TONE_BG, TONE_BORDER } from '~/utils/workflow/registry'
import type { WorkflowNode, WorkflowStepRunStatus } from '~/types/workflow'

// The One Node Shell Rule (plan §7): every step type renders through this
// one component, driven entirely by its NodeDefinition. A dedicated shape
// (WorkflowNodeCondition's two labeled outputs, WorkflowNodeApproval's gate
// visual) is a later, additive split — not required for the canvas itself
// to render correctly.
const props = defineProps<{
  id: string
  data: { step: WorkflowNode; runStatus?: WorkflowStepRunStatus }
  selected?: boolean
}>()

const def = computed(() => nodeDefinition(props.data.step.type))

const RUN_STATUS_BADGE: Partial<Record<WorkflowStepRunStatus, { icon: typeof CheckCircle2; class: string; spin?: boolean }>> = {
  RUNNING: { icon: Loader2, class: 'text-info', spin: true },
  WAITING_APPROVAL: { icon: UserCheck2, class: 'text-warning' },
  SUCCEEDED: { icon: CheckCircle2, class: 'text-success' },
  FAILED: { icon: XCircle, class: 'text-destructive' },
  SKIPPED: { icon: MinusCircle, class: 'text-muted-foreground' },
  CANCELLED: { icon: Ban, class: 'text-muted-foreground' },
}
const runBadge = computed(() => props.data.runStatus ? RUN_STATUS_BADGE[props.data.runStatus] : undefined)

const RUN_STATUS_RING: Partial<Record<WorkflowStepRunStatus, string>> = {
  RUNNING: 'border-info ring-2 ring-info/30',
  WAITING_APPROVAL: 'border-warning ring-2 ring-warning/30',
  FAILED: 'border-destructive ring-2 ring-destructive/30',
  SUCCEEDED: 'border-success',
}

// Faza B — connect on any of the 4 sides (plan Partea II, D1). One handle
// per side, each usable as both drag origin and drag target
// (connectable-start/-end both true) — `type` itself is close to
// meaningless once WorkflowCanvas sets `connectionMode: Loose`, but a value
// is still required by the prop type, so `source` for all four is as
// arbitrary and as correct as any other choice.
const SIDES = [
  { id: 'top', position: Position.Top },
  { id: 'right', position: Position.Right },
  { id: 'bottom', position: Position.Bottom },
  { id: 'left', position: Position.Left },
] as const
</script>

<template>
  <div
    class="group relative flex min-w-[200px] items-center gap-2.5 rounded-[var(--radius-md)] border bg-card px-3 py-2.5 shadow-[var(--shadow-surface)] transition-colors"
    :class="[
      selected ? 'border-primary-active ring-2 ring-primary-active/30'
        : (data.runStatus && RUN_STATUS_RING[data.runStatus]) || TONE_BORDER[def.tone],
      data.step.disabled ? 'opacity-50' : '',
    ]"
  >
    <Handle
      v-for="side in SIDES" :key="side.id"
      :id="side.id" type="source" :position="side.position"
      :connectable-start="true" :connectable-end="true"
      class="!size-2 !border-none !bg-border opacity-0 transition-opacity group-hover:opacity-100"
      :class="selected ? '!opacity-100' : ''"
    />

    <span
      v-if="runBadge"
      class="absolute -right-1.5 -top-1.5 flex size-4 items-center justify-center rounded-full bg-card"
      :class="runBadge.class"
    >
      <component :is="runBadge.icon" class="size-3.5" :class="runBadge.spin ? 'animate-spin' : ''" />
    </span>

    <span class="flex size-8 shrink-0 items-center justify-center rounded-[var(--radius-sm)]" :class="TONE_BG[def.tone]">
      <component :is="def.icon" class="size-4" />
    </span>

    <div class="min-w-0 flex-1">
      <div class="flex items-center gap-1.5">
        <span class="truncate text-[13px] font-medium">{{ data.step.name }}</span>
        <AlertTriangle v-if="!def.executable" class="size-3 shrink-0 text-warning" :aria-label="`${def.label} is not executable yet`" />
      </div>
      <span class="label-caps text-[10px] text-muted-foreground">{{ def.label }}</span>
    </div>
  </div>
</template>
