<script setup lang="ts">
import { ShieldCheck } from 'lucide-vue-next'
import { VisDonut, VisSingleContainer } from '@unovis/vue'
import type { ComplianceOverview } from '~/stores/compliance'

const props = defineProps<{
  overview: ComplianceOverview | null
}>()

interface Segment { name: string; count: number }

// A single-metric ring (compliant share vs remainder) — same VisDonut
// primitive AgentStatusDonut uses, just with one derived pair instead of
// a real by-status breakdown, since overall_compliance_pct is the only
// aggregate the backend exposes (no per-framework split — see index.vue notes).
const segments = computed<Segment[]>(() => {
  const pct = props.overview?.overall_compliance_pct ?? 0
  return [{ name: 'Compliant', count: pct }, { name: 'Remaining', count: 100 - pct }]
})
const value = (d: Segment) => d.count
const color = (d: Segment) => d.name === 'Compliant' ? 'var(--success)' : 'var(--muted-foreground)'
</script>

<template>
  <div class="surface-card rounded-[var(--radius-md)] p-3">
    <div class="flex items-center justify-between mb-2.5">
      <div class="flex items-center gap-1.5 text-muted-foreground">
        <span class="flex items-center justify-center size-5 rounded-md bg-[color-mix(in_oklch,var(--primary-active)_15%,transparent)] text-primary-active shrink-0">
          <ShieldCheck class="size-3" />
        </span>
        <h2 class="label-caps">Compliance</h2>
      </div>
      <NuxtLink to="/compliance" class="text-[12px] font-medium text-primary dark:text-primary-active shrink-0">View full report →</NuxtLink>
    </div>

    <div v-if="!overview" class="flex flex-col sm:flex-row items-center gap-3">
      <Skeleton class="size-24 rounded-full shrink-0" />
      <Skeleton class="h-16 w-full" />
    </div>
    <div v-else class="flex flex-col sm:flex-row items-center gap-3">
      <div class="relative shrink-0 size-24">
        <VisSingleContainer :data="segments" :height="96" :width="96">
          <VisDonut :value="value" :color="color" :arc-width="16" :corner-radius="2" :central-label="`${Math.round(overview.overall_compliance_pct)}%`" />
        </VisSingleContainer>
      </div>
      <div class="flex-1 w-full space-y-1.5 text-xs">
        <div class="flex items-center justify-between gap-2">
          <span class="min-w-0 truncate text-muted-foreground">Servers evaluated</span>
          <span class="shrink-0 font-medium tabular-nums">{{ overview.servers_evaluated }}</span>
        </div>
        <div class="flex items-center justify-between gap-2">
          <span class="min-w-0 truncate text-muted-foreground">Non-compliant</span>
          <span class="shrink-0 font-medium tabular-nums text-destructive">{{ overview.servers_non_compliant }}</span>
        </div>
        <div class="flex items-center justify-between gap-2">
          <span class="min-w-0 truncate text-muted-foreground">Exceptions</span>
          <span class="shrink-0 font-medium tabular-nums">{{ overview.exceptions_active }}</span>
        </div>
        <div class="flex items-center justify-between gap-2">
          <span class="min-w-0 truncate text-muted-foreground">Remediation</span>
          <span class="shrink-0 font-medium tabular-nums" :title="`${overview.resolved_controls} resolved`">{{ overview.remediation_pct }}%</span>
        </div>
      </div>
    </div>
  </div>
</template>
