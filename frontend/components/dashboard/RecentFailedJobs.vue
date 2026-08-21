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
      <NuxtLink to="/jobs" class="flex items-center gap-1 text-[12px] font-medium text-primary dark:text-primary-active shrink-0">
        View all
        <ArrowRight class="size-3" />
      </NuxtLink>
    </div>

    <div v-if="props.error" class="flex-1 flex items-center justify-center text-xs text-red-500">
      Failed to load recent jobs.
    </div>
    <div v-else-if="props.loading" class="space-y-3">
      <Skeleton v-for="i in 3" :key="i" class="h-10 rounded-md" />
    </div>
    <div v-else-if="!props.jobs.length" class="flex-1 flex items-center justify-center text-xs text-muted-foreground">
      No failed jobs — automation is healthy.
    </div>
    <div v-else class="space-y-2.5">
      <NuxtLink
        v-for="job in props.jobs.slice(0, 5)" :key="job.id"
        to="/jobs"
        class="flex items-center justify-between gap-2 text-xs group"
      >
        <div class="min-w-0">
          <p class="min-w-0 truncate font-medium group-hover:text-primary dark:group-hover:text-primary-active transition-colors">{{ job.name }}</p>
          <p class="text-[11px] text-muted-foreground">{{ job.job_type }}</p>
        </div>
        <span class="shrink-0 text-muted-foreground">{{ relativeTime(job.completed_at) }}</span>
      </NuxtLink>
    </div>
  </div>
</template>
