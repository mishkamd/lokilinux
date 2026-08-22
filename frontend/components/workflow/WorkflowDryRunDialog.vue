<script setup lang="ts">
import { CheckCircle2, AlertTriangle, Clock, UserCheck2 } from 'lucide-vue-next'
import type { DryRunResponse } from '~/types/workflow'

const props = defineProps<{ modelValue: boolean; result: DryRunResponse | null }>()
defineEmits<{ 'update:modelValue': [boolean] }>()

function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  const m = Math.round(seconds / 60)
  return `${m} minute${m === 1 ? '' : 's'}`
}

const approvalSet = computed(() => new Set(props.result?.requires_approval_at ?? []))
</script>

<template>
  <Dialog :model-value="modelValue" title="Dry Run" size="lg" @update:model-value="$emit('update:modelValue', $event)">
    <template #body>
      <div v-if="!result" class="py-6 text-center text-sm text-muted-foreground">No result yet.</div>
      <div v-else class="space-y-4">
        <div class="grid grid-cols-2 gap-3">
          <div class="surface-card rounded-[var(--radius-md)] p-3">
            <p class="label-caps text-muted-foreground">Targets matched</p>
            <p class="font-mono text-2xl font-bold">{{ result.targets_matched }}</p>
          </div>
          <div class="surface-card rounded-[var(--radius-md)] p-3">
            <p class="label-caps text-muted-foreground">Estimated dispatch time</p>
            <p class="font-mono text-2xl font-bold flex items-center gap-1.5">
              <Clock class="size-4 text-muted-foreground" />
              {{ fmtDuration(result.estimated_dispatch_seconds) }}
            </p>
          </div>
        </div>

        <p v-if="result.targets_matched === 0" class="flex items-center gap-2 rounded-[var(--radius-sm)] border border-warning/30 bg-[color-mix(in_oklch,var(--warning)_8%,var(--background))] px-2.5 py-1.5 text-xs text-warning">
          <AlertTriangle class="size-4 shrink-0" />
          No agents match this workflow's targets — Run would fail the same way.
        </p>

        <div class="space-y-1.5">
          <div v-for="step in result.steps" :key="step.id" class="flex items-center gap-2.5 rounded-[var(--radius-sm)] border border-border/60 px-2.5 py-2 text-xs">
            <CheckCircle2 v-if="step.blocked === 0" class="size-4 shrink-0 text-success" />
            <AlertTriangle v-else class="size-4 shrink-0 text-destructive" />
            <span class="min-w-0 flex-1 truncate font-medium">{{ step.id }}</span>
            <UserCheck2 v-if="approvalSet.has(step.id)" class="size-3.5 shrink-0 text-warning" aria-label="Requires approval" />
            <span class="shrink-0 text-muted-foreground">{{ step.eligible }} eligible</span>
            <span v-if="step.blocked > 0" class="shrink-0 text-destructive">{{ step.blocked }} blocked</span>
          </div>
        </div>

        <p v-if="result.requires_approval_at.length" class="text-xs text-muted-foreground">
          Will pause for approval at: <span class="font-medium text-foreground">{{ result.requires_approval_at.join(', ') }}</span>
        </p>
      </div>
    </template>
    <template #footer>
      <Button variant="outline" @click="$emit('update:modelValue', false)">Close</Button>
    </template>
  </Dialog>
</template>
