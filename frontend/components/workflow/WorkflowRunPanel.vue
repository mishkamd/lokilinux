<script setup lang="ts">
import { Check, X, Ban, CheckCircle2, XCircle, Loader2, UserCheck2, MinusCircle, Clock } from 'lucide-vue-next'
import { nodeDefinition } from '~/utils/workflow/registry'
import type { WorkflowNode, WorkflowRunDetail, WorkflowStepRunStatus } from '~/types/workflow'

const props = defineProps<{
  run: WorkflowRunDetail | null
  nodes: WorkflowNode[]
  actionPending?: boolean
}>()

const emit = defineEmits<{
  cancel: []
  approve: [stepId: string]
  reject: [stepId: string]
}>()

const RUN_STATUS_COLOR: Record<string, string> = {
  PENDING: 'gray', RUNNING: 'blue', WAITING_APPROVAL: 'amber',
  SUCCEEDED: 'green', FAILED: 'red', CANCELLED: 'gray',
}

const STEP_STATUS_ICON: Record<WorkflowStepRunStatus, { icon: typeof CheckCircle2; class: string; spin?: boolean }> = {
  PENDING: { icon: Clock, class: 'text-muted-foreground' },
  RUNNING: { icon: Loader2, class: 'text-info', spin: true },
  WAITING_APPROVAL: { icon: UserCheck2, class: 'text-warning' },
  SUCCEEDED: { icon: CheckCircle2, class: 'text-success' },
  FAILED: { icon: XCircle, class: 'text-destructive' },
  SKIPPED: { icon: MinusCircle, class: 'text-muted-foreground' },
  CANCELLED: { icon: Ban, class: 'text-muted-foreground' },
}

function nodeName(stepId: string): string {
  return props.nodes.find(n => n.id === stepId)?.name ?? stepId
}

function nodeIcon(stepId: string) {
  const node = props.nodes.find(n => n.id === stepId)
  return node ? nodeDefinition(node.type).icon : Clock
}

function fmt(v: string | null): string {
  return v ? new Date(v).toLocaleTimeString() : '—'
}

const ACTIVE = ['PENDING', 'RUNNING', 'WAITING_APPROVAL']
</script>

<template>
  <div class="h-full overflow-y-auto p-3 sm:p-4">
    <div v-if="!run" class="flex h-full items-center justify-center text-sm text-muted-foreground">
      No runs yet — use Run in the toolbar to start one.
    </div>
    <template v-else>
      <div class="surface-card mb-3 flex items-center gap-3 rounded-[var(--radius-md)] p-3">
        <Badge size="sm" :color="RUN_STATUS_COLOR[run.status] ?? 'gray'">{{ run.status }}</Badge>
        <div class="min-w-0 flex-1 text-xs text-muted-foreground">
          <span class="font-medium text-foreground">{{ run.trigger_type }}</span>
          · started {{ fmt(run.started_at) }}
          <span v-if="run.completed_at">· completed {{ fmt(run.completed_at) }}</span>
          <span v-if="run.is_dry_run"> · dry run</span>
        </div>
        <Button v-if="ACTIVE.includes(run.status)" size="xs" variant="outline" :loading="actionPending" @click="emit('cancel')">
          <Ban class="size-3.5" />
          Cancel
        </Button>
      </div>

      <p v-if="run.error" class="mb-3 rounded-[var(--radius-sm)] border border-destructive/30 bg-[color-mix(in_oklch,var(--destructive)_8%,var(--background))] px-2.5 py-1.5 text-xs text-destructive">
        {{ run.error }}
      </p>

      <div class="space-y-1.5">
        <div
          v-for="sr in run.step_runs" :key="sr.id"
          class="flex items-center gap-2.5 rounded-[var(--radius-sm)] border border-border/60 px-2.5 py-2"
        >
          <component :is="STEP_STATUS_ICON[sr.status].icon" class="size-4 shrink-0" :class="[STEP_STATUS_ICON[sr.status].class, STEP_STATUS_ICON[sr.status].spin ? 'animate-spin' : '']" />
          <component :is="nodeIcon(sr.step_id)" class="size-3.5 shrink-0 text-muted-foreground" />
          <span class="min-w-0 flex-1 truncate text-xs font-medium">{{ nodeName(sr.step_id) }}</span>
          <span v-if="sr.error" class="min-w-0 max-w-[40%] truncate text-[11px] text-destructive" :title="sr.error">{{ sr.error }}</span>

          <template v-if="sr.status === 'WAITING_APPROVAL'">
            <Button size="xs" variant="outline" :loading="actionPending" @click="emit('reject', sr.step_id)">
              <X class="size-3.5" />
              Reject
            </Button>
            <Button size="xs" :loading="actionPending" @click="emit('approve', sr.step_id)">
              <Check class="size-3.5" />
              Approve
            </Button>
          </template>
          <Badge v-else size="xs" :color="RUN_STATUS_COLOR[sr.status] ?? 'gray'">{{ sr.status }}</Badge>
        </div>
      </div>
    </template>
  </div>
</template>
