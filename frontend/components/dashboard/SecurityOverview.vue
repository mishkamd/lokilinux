<script setup lang="ts">
// Risk score is derived client-side from severity counts — the backend has
// no dedicated risk-scoring endpoint and doesn't need one for a simple
// worst-severity-present heuristic.
import { ShieldAlert } from 'lucide-vue-next'
import type { VulnerabilitySummary, VulnerabilityTrendPoint } from '~/stores/vulnerabilities'

const props = defineProps<{
  summary: VulnerabilitySummary | null
  trend: VulnerabilityTrendPoint[]
}>()

const RISK_LEVELS = [
  { key: 'critical', label: 'Critical', color: 'text-destructive' },
  { key: 'high', label: 'High', color: 'text-destructive' },
  { key: 'medium', label: 'Medium', color: 'text-warning' },
  { key: 'low', label: 'Low', color: 'text-info' },
] as const

const riskLevel = computed(() => {
  const s = props.summary
  if (!s) return null
  if (s.critical > 0) return RISK_LEVELS[0]
  if (s.high > 0) return RISK_LEVELS[1]
  if (s.medium > 0) return RISK_LEVELS[2]
  if (s.low > 0) return RISK_LEVELS[3]
  return { key: 'minimal', label: 'Minimal', color: 'text-success' } as const
})

const trendDeltaPct = computed(() => {
  const firstPoint = props.trend.at(0)
  const lastPoint = props.trend.at(-1)
  if (props.trend.length < 2 || !firstPoint || !lastPoint) return null
  const totalAt = (p: VulnerabilityTrendPoint) => p.critical + p.high + p.medium + p.low
  const first = totalAt(firstPoint)
  const last = totalAt(lastPoint)
  if (first === 0) return null
  return Math.round(((last - first) / first) * 100)
})

const sparkline = computed(() => props.trend.map(p => ({
  date: p.day,
  value: p.critical + p.high + p.medium + p.low,
})))

const rows = computed(() => RISK_LEVELS.map(level => ({
  ...level,
  count: props.summary?.[level.key] ?? 0,
})))
</script>

<template>
  <div class="surface-card rounded-[var(--radius-md)] p-3">
    <div class="flex items-center justify-between mb-2.5">
      <div class="flex items-center gap-1.5 text-muted-foreground">
        <span class="flex items-center justify-center size-5 rounded-md bg-[color-mix(in_oklch,var(--destructive)_15%,transparent)] text-destructive shrink-0">
          <ShieldAlert class="size-3" />
        </span>
        <h2 class="label-caps">Security Overview</h2>
      </div>
      <NuxtLink to="/vulnerabilities" class="text-[12px] font-medium text-primary shrink-0">View full report →</NuxtLink>
    </div>

    <div v-if="!summary" class="space-y-2">
      <Skeleton class="h-6 w-20" />
      <Skeleton class="h-16 w-full" />
    </div>
    <template v-else>
      <div class="flex items-center justify-between mb-3">
        <span class="text-xs text-muted-foreground">Risk Score</span>
        <span class="text-sm font-semibold" :class="riskLevel?.color">{{ riskLevel?.label }}</span>
      </div>

      <div class="space-y-1.5 mb-3">
        <div v-for="row in rows" :key="row.key" class="flex items-center justify-between text-xs">
          <span class="text-muted-foreground">{{ row.label }} CVEs</span>
          <span class="font-medium tabular-nums" :class="row.color">{{ row.count }}</span>
        </div>
      </div>

      <MetricAreaChart v-if="sparkline.length >= 2" :data="sparkline" color="var(--destructive)" :height="40" />
      <p v-if="trendDeltaPct !== null" class="text-[11px] text-muted-foreground mt-1">
        <span :class="trendDeltaPct <= 0 ? 'text-success' : 'text-destructive'">{{ trendDeltaPct > 0 ? '+' : '' }}{{ trendDeltaPct }}%</span>
        from start of period
      </p>
    </template>
  </div>
</template>
