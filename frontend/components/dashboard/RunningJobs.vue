<script setup lang="ts">
import { Loader, ArrowRight } from 'lucide-vue-next'
import type { RunningJob } from '~/stores/dashboard'

const props = defineProps<{ jobs: RunningJob[]; loading?: boolean; error?: boolean }>()

function elapsed(startedAt: string | null): string {
  if (!startedAt) return '—'
  const diffSec = Math.max(0, (Date.now() - new Date(startedAt).getTime()) / 1000)
  if (diffSec < 60) return `${Math.floor(diffSec)}s`
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m`
  return `${Math.floor(diffSec / 3600)}h ${Math.floor((diffSec % 3600) / 60)}m`
}
</script>

<template>
  <div class="surface-card rounded-[var(--radius-md)] p-3">
    <div class="flex items-center justify-between mb-2.5">
      <div class="flex items-center gap-1.5 text-muted-foreground">
        <span class="flex items-center justify-center size-5 rounded-md bg-[color-mix(in_oklch,var(--info)_15%,transparent)] text-info shrink-0">
          <Loader class="size-3" />
        </span>
        <h2 class="label-caps">Running Jobs</h2>
      </div>
      <NuxtLink to="/jobs" class="focus-ring flex items-center gap-1 text-xs font-medium text-primary-text dark:text-primary-active shrink-0">
        View all
        <ArrowRight class="size-3" />
      </NuxtLink>
    </div>

    <WidgetState
      v-if="props.error || props.loading"
      :error="props.error ? 'Failed to load running jobs.' : null"
      :loading="props.loading"
      :rows="3"
      row-class="h-10 rounded-md"
    />
    <template v-else-if="!props.jobs.length">
      <EmptyState>No jobs currently running.</EmptyState>
    </template>
    <div v-else class="space-y-3">
      <div v-for="job in props.jobs" :key="job.id" class="text-xs">
        <div class="flex items-center justify-between gap-2 mb-1">
          <span class="min-w-0 truncate font-medium">{{ job.name }}</span>
          <span class="shrink-0 text-muted-foreground">
            {{ job.target_servers.agent_ids.length }} servers · {{ elapsed(job.started_at) }}
          </span>
        </div>
        <Progress v-if="job.progress !== null" :model-value="job.progress" class="h-1.5" />
        <p v-else class="text-label text-muted-foreground">Progress unavailable</p>
      </div>
    </div>
  </div>
</template>
