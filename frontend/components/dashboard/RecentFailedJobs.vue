<script setup lang="ts">
import { XCircle, ArrowRight } from 'lucide-vue-next'
import type { RecentFailedJob } from '~/stores/dashboard'

const props = defineProps<{ jobs: RecentFailedJob[]; loading?: boolean; error?: boolean }>()

function relativeTime(iso: string | null): string {
  if (!iso) return '—'
  const diffSec = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (diffSec < 60) return 'now'
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h`
  return `${Math.floor(diffSec / 86400)}d`
}
</script>

<template>
  <div class="surface-card rounded-[var(--radius-md)] p-3 flex flex-col">
    <div class="flex items-center justify-between mb-2.5">
      <div class="flex items-center gap-1.5 text-muted-foreground">
        <span class="flex items-center justify-center size-5 rounded-md bg-[color-mix(in_oklch,var(--destructive)_15%,transparent)] text-destructive shrink-0">
          <XCircle class="size-3" />
        </span>
        <h2 class="label-caps">Recent Failed Jobs</h2>
      </div>
      <NuxtLink to="/jobs" class="focus-ring flex items-center gap-1 text-[12px] font-medium text-primary-text dark:text-primary-active shrink-0">
        View all
        <ArrowRight class="size-3" />
      </NuxtLink>
    </div>

    <WidgetState
      v-if="props.error || props.loading"
      :error="props.error ? 'Failed to load recent jobs.' : null"
      :loading="props.loading"
      :rows="3"
      row-class="h-10 rounded-md"
    />
    <template v-else-if="!props.jobs.length">
      <EmptyState>No failed jobs — automation is healthy.</EmptyState>
    </template>
    <div v-else class="space-y-2">
      <NuxtLink
        v-for="job in props.jobs.slice(0, 5)" :key="job.id"
        to="/jobs"
        class="focus-ring flex items-center gap-2.5 rounded-[var(--radius-sm)] border border-border/60 p-2 text-xs group"
      >
        <span class="flex size-7 shrink-0 items-center justify-center rounded-full bg-[color-mix(in_oklch,var(--destructive)_15%,transparent)] text-destructive">
          <XCircle class="size-3.5" />
        </span>
        <div class="min-w-0 flex-1 flex items-center justify-between gap-2">
          <div class="min-w-0">
            <p class="min-w-0 truncate font-medium group-hover:text-primary-text dark:group-hover:text-primary-active transition-colors">{{ job.name }}</p>
            <p class="text-[11px] text-muted-foreground">{{ job.job_type }}</p>
          </div>
          <span class="shrink-0 text-muted-foreground">{{ relativeTime(job.completed_at) }}</span>
        </div>
      </NuxtLink>
    </div>
  </div>
</template>
