<script setup lang="ts">
import { TrendingUp } from 'lucide-vue-next'
import { CurveType } from '@unovis/ts'
import { VisArea } from '@unovis/vue'
import type { TrendPoint } from '~/stores/compliance'
import type { ChartConfig } from '~/components/ui/chart/types'

const props = defineProps<{ points: TrendPoint[]; loading: boolean; range: string }>()
const emit = defineEmits<{ 'update:range': [value: string] }>()

const RANGES = [
  { label: '7d', value: '7d' },
  { label: '30d', value: '30d' },
  { label: '90d', value: '90d' },
  { label: '1y', value: '1y' },
]

const chartConfig: ChartConfig = {
  compliance_pct: { label: 'Compliance', color: 'var(--chart-1)' },
}

const x = (_d: TrendPoint, i: number) => i
const y = (d: TrendPoint) => d.compliance_pct

const latest = computed(() => props.points.at(-1)?.compliance_pct ?? null)
</script>

<template>
  <div class="surface-card rounded-[var(--radius-md)] p-3">
    <div class="flex items-center justify-between mb-2.5">
      <div class="flex items-center gap-1.5 text-muted-foreground">
        <span class="flex items-center justify-center size-5 rounded-md bg-[color-mix(in_oklch,var(--primary-active)_15%,transparent)] text-primary-active shrink-0">
          <TrendingUp class="size-3" />
        </span>
        <h2 class="label-caps">Compliance trend</h2>
        <span v-if="latest !== null" class="text-xs font-mono text-foreground ml-1">{{ latest.toFixed(1) }}%</span>
      </div>
      <div class="flex items-center gap-1">
        <button
          v-for="r in RANGES" :key="r.value"
          class="px-2 py-0.5 text-xs rounded-md transition-colors"
          :class="range === r.value ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'"
          @click="emit('update:range', r.value)"
        >
          {{ r.label }}
        </button>
      </div>
    </div>
    <Skeleton v-if="loading" class="h-24 w-full" />
    <p v-else-if="points.length < 2" class="text-xs text-muted-foreground py-8 text-center">
      Not enough history yet — trend appears once compliance scores accumulate.
    </p>
    <ChartContainer v-else :config="chartConfig" :data="props.points" :height="96">
      <VisArea :x="x" :y="y" color="var(--chart-1)" :opacity="0.12" :line="true" line-color="var(--chart-1)" :line-width="2" :curve-type="CurveType.Natural" />
      <ChartTooltip :x="x" label-key="day" :value-formatter="(v) => `${v.toFixed(1)}%`" />
    </ChartContainer>
  </div>
</template>
