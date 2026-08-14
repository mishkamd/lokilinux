<script setup lang="ts" generic="Datum">
// Unovis has no Recharts-style content render-prop — VisCrosshair takes a
// single HTML-string template function, so the "tooltip content" half of
// shadcn's Tooltip/TooltipContent split is inlined here rather than split
// into a second file that would only ever have this one caller.
// Generic on Datum so callers can pass their concrete row type (e.g.
// JobTrendPoint) instead of widening every chart's x/y accessors to
// Record<string, unknown>.
import { inject } from 'vue'
import { VisCrosshair } from '@unovis/vue'
import { ChartConfigKey } from './context'

const props = withDefaults(defineProps<{
  x: (d: Datum, i: number) => number
  y?: ((d: Datum) => number) | ((d: Datum) => number)[]
  /** Accessors for stacked components (Area/StackedBar) — positions crosshair
   * circles at each band's cumulative height instead of its raw value. */
  yStacked?: ((d: Datum) => number)[]
  indicator?: 'dot' | 'line'
  labelKey?: string
  valueFormatter?: (v: number) => string
}>(), {
  indicator: 'dot',
  labelKey: 'date',
})

const config = inject(ChartConfigKey, {})

function formatValue(v: unknown): string {
  if (typeof v !== 'number') return String(v ?? '')
  return props.valueFormatter ? props.valueFormatter(v) : v.toLocaleString()
}

function template(datum: Datum): string {
  if (!datum) return ''
  const row = datum as Record<string, unknown>
  const shape = props.indicator === 'line'
    ? 'width:12px;height:2px;border-radius:1px;'
    : 'width:8px;height:8px;border-radius:9999px;'

  const rows = Object.entries(config)
    .filter(([key]) => row[key] !== undefined)
    .map(([key, series]) => `
      <div style="display:flex;align-items:center;gap:6px;font-size:12px;padding:2px 0;">
        <span style="${shape}background:${series.color};flex-shrink:0;"></span>
        <span style="color:var(--muted-foreground);">${series.label}</span>
        <span style="margin-left:auto;padding-left:12px;font-weight:600;font-variant-numeric:tabular-nums;">${formatValue(row[key])}</span>
      </div>
    `)
    .join('')

  const label = String(row[props.labelKey] ?? '')

  return `
    <div style="background:var(--popover);color:var(--popover-foreground);border:1px solid var(--border);border-radius:var(--radius-sm);padding:8px 10px;box-shadow:var(--shadow-overlay);min-width:150px;">
      ${label ? `<div style="font-size:11px;color:var(--muted-foreground);margin-bottom:4px;">${label}</div>` : ''}
      ${rows}
    </div>
  `
}
</script>

<template>
  <VisCrosshair :x="props.x" :y="props.y" :y-stacked="props.yStacked" :template="template" />
</template>
