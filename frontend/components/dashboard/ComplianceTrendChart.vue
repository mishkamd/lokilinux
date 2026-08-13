<script setup lang="ts">
import { TrendingUp } from 'lucide-vue-next'
import type { TrendPoint } from '~/stores/compliance'

const props = defineProps<{ points: TrendPoint[]; loading: boolean; range: string }>()
const emit = defineEmits<{ 'update:range': [value: string] }>()

const RANGES = [
  { label: '7d', value: '7d' },
  { label: '30d', value: '30d' },
  { label: '90d', value: '90d' },
  { label: '1y', value: '1y' },
]

const WIDTH = 600
const HEIGHT = 120
const PAD = 8

// min/max clamp keeps a flat 100%-everywhere trend from collapsing to a
// zero-height line — a few points of vertical range are still legible.
const bounds = computed(() => {
  const values = props.points.map((p) => p.compliance_pct)
  if (values.length === 0) return { min: 0, max: 100 }
  const min = Math.min(...values)
  const max = Math.max(...values)
  return max - min < 5 ? { min: Math.max(0, min - 5), max: Math.min(100, max + 5) } : { min, max }
})

const linePath = computed(() => {
  const n = props.points.length
  if (n < 2) return ''
  const { min, max } = bounds.value
  const span = max - min || 1
  return props.points
    .map((p, i) => {
      const x = PAD + (i / (n - 1)) * (WIDTH - PAD * 2)
      const y = HEIGHT - PAD - ((p.compliance_pct - min) / span) * (HEIGHT - PAD * 2)
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
})

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
    <svg v-else :viewBox="`0 0 ${WIDTH} ${HEIGHT}`" class="w-full h-24" preserveAspectRatio="none">
      <path :d="linePath" fill="none" stroke="var(--chart-1)" stroke-width="2" vector-effect="non-scaling-stroke" />
    </svg>
  </div>
</template>
