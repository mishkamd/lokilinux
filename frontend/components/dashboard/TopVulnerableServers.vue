<script setup lang="ts">
import { ServerCog, ArrowRight } from 'lucide-vue-next'
import type { TopVulnerableResource } from '~/stores/vulnerabilities'

const props = defineProps<{ resources: TopVulnerableResource[]; loading?: boolean; error?: boolean }>()
const { severityColor, severityLabel } = useSeverity()

const maxTotal = computed(() => Math.max(1, ...props.resources.map(r => r.total)))

// Worst severity actually present on the resource — same precedence as the
// dashboard's own severity badges, just derived per-row instead of from a summary.
function worstSeverity(r: TopVulnerableResource): { label: string; color: string } {
  const sev = r.critical > 0 ? 'CRITICAL' : r.high > 0 ? 'HIGH' : r.medium > 0 ? 'MEDIUM' : 'LOW'
  return { label: severityLabel(sev), color: severityColor(sev) }
}
</script>

<template>
  <div class="surface-card rounded-[var(--radius-md)] p-3">
    <div class="flex items-center justify-between mb-2.5">
      <div class="flex items-center gap-1.5 text-muted-foreground">
        <span class="flex items-center justify-center size-5 rounded-md bg-[color-mix(in_oklch,var(--destructive)_15%,transparent)] text-destructive shrink-0">
          <ServerCog class="size-3" />
        </span>
        <h2 class="label-caps">Top Vulnerable Servers</h2>
      </div>
      <NuxtLink to="/vulnerabilities" class="flex items-center gap-1 text-[12px] font-medium text-primary dark:text-primary-active shrink-0">
        View all
        <ArrowRight class="size-3" />
      </NuxtLink>
    </div>

    <div v-if="props.error" class="text-xs text-destructive py-4 text-center">
      Failed to load vulnerable servers.
    </div>
    <div v-else-if="props.loading" class="space-y-3">
      <Skeleton v-for="i in 3" :key="i" class="h-10 rounded-md" />
    </div>
    <div v-else-if="!props.resources.length" class="text-xs text-muted-foreground py-4 text-center">
      No vulnerable servers detected.
    </div>
    <div v-else class="space-y-2">
      <NuxtLink
        v-for="r in props.resources.slice(0, 5)" :key="r.agent_id"
        :to="`/servers/${r.agent_id}`"
        class="flex items-center gap-2.5 rounded-[var(--radius-sm)] border border-border/60 p-2 group"
      >
        <span class="flex size-7 shrink-0 items-center justify-center rounded-md bg-[color-mix(in_oklch,var(--destructive)_15%,transparent)] text-destructive">
          <ServerCog class="size-3.5" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="flex items-center justify-between gap-2 text-xs mb-1">
            <span class="min-w-0 truncate font-medium group-hover:text-primary dark:group-hover:text-primary-active transition-colors">{{ r.hostname ?? r.agent_id }}</span>
            <span class="flex shrink-0 items-center gap-2">
              <span class="text-muted-foreground">{{ r.total }} vulnerabilities</span>
              <Badge size="xs" :color="worstSeverity(r).color">{{ worstSeverity(r).label }}</Badge>
            </span>
          </div>
          <Progress :model-value="r.total" :max="maxTotal" class="h-1.5" indicator-class="bg-destructive" />
        </div>
      </NuxtLink>
    </div>
  </div>
</template>
