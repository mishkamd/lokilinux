<script setup lang="ts">
import { Users, Settings, Server, ClipboardList, FileText, Activity, ArrowRight } from 'lucide-vue-next'

interface AuditLog {
  id: string
  timestamp: string
  actor_name: string | null
  action: string
  resource_type: string | null
  resource_id: string | null
  status: string
}

const api = useApi()

const { data, pending, error } = await useAsyncData('dashboard-recent-activity', () =>
  api.get<{ items: AuditLog[]; next_cursor: number | null; total: number }>(
    '/admin/audit',
    { params: { limit: 6 } },
  ),
)

const RESOURCE_ICON: Record<string, typeof Server> = {
  user: Users, setting: Settings, agent: Server, job: ClipboardList, policy: FileText,
}

function iconFor(resourceType: string | null) {
  return (resourceType && RESOURCE_ICON[resourceType]) ?? Activity
}

function relativeTime(iso: string): string {
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
        <span class="flex items-center justify-center size-5 rounded-md bg-[color-mix(in_oklch,var(--primary-active)_15%,transparent)] text-primary-active shrink-0">
          <Activity class="size-3" />
        </span>
        <h2 class="label-caps">Recent Activity</h2>
      </div>
      <NuxtLink to="/admin/audit" class="flex items-center gap-1 text-[12px] font-medium text-primary dark:text-primary-active shrink-0">
        View all
        <ArrowRight class="size-3" />
      </NuxtLink>
    </div>

    <div v-if="error" class="text-xs text-destructive">Failed to load recent activity.</div>
    <div v-else-if="pending" class="space-y-1.5">
      <Skeleton v-for="i in 4" :key="i" class="h-7 rounded-md" />
    </div>
    <div v-else-if="!data?.items.length" class="text-xs text-muted-foreground py-2 text-center">
      No activity recorded.
    </div>
    <div v-else class="relative">
      <div class="absolute left-[7px] top-1 bottom-1 w-px bg-border" />
      <div
        v-for="log in data.items" :key="log.id"
        class="relative flex items-start gap-3 py-2 first:pt-0 last:pb-0"
      >
        <span class="relative z-10 flex size-3.5 shrink-0 items-center justify-center rounded-full bg-[color-mix(in_oklch,var(--primary-active)_15%,transparent)] text-primary-active mt-0.5">
          <component :is="iconFor(log.resource_type)" class="size-2.5" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <span class="min-w-0 truncate text-xs font-medium">{{ log.action }}</span>
            <Badge v-if="log.resource_type" size="xs" color="gray" class="shrink-0">{{ log.resource_type }}</Badge>
          </div>
          <span class="text-[11px] text-muted-foreground">{{ log.actor_name ?? 'system' }} · {{ relativeTime(log.timestamp) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
