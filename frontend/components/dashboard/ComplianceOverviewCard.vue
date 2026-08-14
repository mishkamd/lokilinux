<script setup lang="ts">
import { ShieldCheck } from 'lucide-vue-next'
import type { ComplianceOverview, TrendPoint } from '~/stores/compliance'

const props = defineProps<{
  overview: ComplianceOverview | null
  trend: TrendPoint[]
}>()

const sparkline = computed(() => props.trend.map(p => ({ date: p.day, value: p.compliance_pct })))
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
      <NuxtLink to="/compliance" class="text-[12px] font-medium text-primary shrink-0">View full report →</NuxtLink>
    </div>

    <div v-if="!overview" class="space-y-2">
      <Skeleton class="h-6 w-20" />
      <Skeleton class="h-16 w-full" />
    </div>
    <template v-else>
      <div class="flex items-center justify-between mb-3">
        <span class="text-xs text-muted-foreground">Overall Score</span>
        <span class="text-lg font-bold font-mono tabular-nums text-primary-active">{{ overview.overall_compliance_pct }}%</span>
      </div>

      <div class="space-y-1.5 mb-3 text-xs">
        <div class="flex items-center justify-between">
          <span class="text-muted-foreground">Servers evaluated</span>
          <span class="font-medium tabular-nums">{{ overview.servers_evaluated }}</span>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-muted-foreground">Non-compliant</span>
          <span class="font-medium tabular-nums text-destructive">{{ overview.servers_non_compliant }}</span>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-muted-foreground">Exceptions</span>
          <span class="font-medium tabular-nums">{{ overview.exceptions_active }}</span>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-muted-foreground">Remediation</span>
          <span class="font-medium tabular-nums">{{ overview.remediation_pct }}% ({{ overview.resolved_controls }} resolved)</span>
        </div>
      </div>

      <MetricAreaChart v-if="sparkline.length >= 2" :data="sparkline" color="var(--chart-1)" :height="40" />
    </template>
  </div>
</template>
