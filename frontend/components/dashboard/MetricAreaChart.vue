<script setup lang="ts">
// Sparkline for MetricCard — no axes, no grid, just a smooth filled area
// with a hover tooltip. Deliberately not ChartContainer/ChartTooltip: those
// assume a multi-series chartConfig; a sparkline is always a single
// unlabeled series, so the setup here stays a few lines instead of forcing
// a config object through provide/inject for one key.
import { CurveType } from '@unovis/ts'
import { VisArea, VisCrosshair, VisXYContainer } from '@unovis/vue'
import type { ChartDataPoint } from '~/components/ui/chart/types'

const props = withDefaults(defineProps<{
  data: ChartDataPoint[]
  color?: string
  height?: number
}>(), {
  color: 'var(--chart-1)',
  height: 48,
})

const x = (_d: ChartDataPoint, i: number) => i
const y = (d: ChartDataPoint) => d.value

function template(d: ChartDataPoint): string {
  if (!d) return ''
  return `
    <div style="background:var(--popover);color:var(--popover-foreground);border:1px solid var(--border);border-radius:var(--radius-sm);padding:6px 8px;box-shadow:var(--shadow-overlay);font-size:12px;">
      <div style="color:var(--muted-foreground);">${d.date}</div>
      <div style="font-weight:600;font-variant-numeric:tabular-nums;">${d.value.toLocaleString()}</div>
    </div>
  `
}
</script>

<template>
  <div class="w-full" :style="{ height: `${props.height}px` }">
    <VisXYContainer :data="props.data" :height="props.height" :padding="{ top: 4, bottom: 4 }">
      <VisArea :x="x" :y="y" :color="props.color" :opacity="0.15" :line="true" :line-color="props.color" :line-width="2" :curve-type="CurveType.Natural" />
      <VisCrosshair :x="x" :y="y" :template="template" :color="props.color" />
    </VisXYContainer>
  </div>
</template>
