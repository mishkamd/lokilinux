<script setup lang="ts">
import { PieChart } from 'lucide-vue-next'

const props = defineProps<{ distribution: Record<string, number> }>()

const RADIUS = 60
const STROKE = 20
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

interface Segment { name: string; count: number; pct: number; color: string; dashArray: string; dashOffset: number }

const total = computed(() => Object.values(props.distribution).reduce((a, b) => a + b, 0))

const segments = computed<Segment[]>(() => {
  const entries = Object.entries(props.distribution).filter(([, count]) => count > 0)
  // "Unknown" (agents with no heartbeat yet) always rendered last, muted color —
  // keeps real OS diversity readable instead of blending into the color cycle.
  entries.sort((a, b) => (a[0] === 'Unknown' ? 1 : b[0] === 'Unknown' ? -1 : b[1] - a[1]))

  let cumulative = 0
  return entries.map(([name, count], i) => {
    const pct = total.value > 0 ? count / total.value : 0
    const dashArray = `${pct * CIRCUMFERENCE} ${CIRCUMFERENCE}`
    const dashOffset = -cumulative * CIRCUMFERENCE
    cumulative += pct
    return {
      name, count, pct,
      color: name === 'Unknown' ? 'var(--muted-foreground)' : `var(--chart-${(i % 5) + 1})`,
      dashArray, dashOffset,
    }
  })
})
</script>

<template>
  <div class="glass-card rounded-xl p-3">
    <div class="flex items-center gap-1.5 text-muted-foreground mb-2.5">
      <span class="flex items-center justify-center size-5 rounded-md bg-[color-mix(in_oklch,var(--primary-active)_15%,transparent)] text-primary-active shrink-0">
        <PieChart class="size-3" />
      </span>
      <h2 class="label-caps">Distribuție OS</h2>
    </div>
    <div v-if="total === 0" class="text-xs text-muted-foreground py-4 text-center">Niciun server înregistrat.</div>
    <div v-else class="flex flex-col sm:flex-row items-center gap-3">
      <div class="relative shrink-0 size-16">
        <svg viewBox="0 0 160 160" class="size-16 -rotate-90">
          <circle cx="80" cy="80" :r="RADIUS" fill="none" stroke="var(--border)" :stroke-width="STROKE" />
          <circle
            v-for="seg in segments"
            :key="seg.name"
            cx="80" cy="80" :r="RADIUS" fill="none"
            :stroke="seg.color"
            :stroke-width="STROKE"
            :stroke-dasharray="seg.dashArray"
            :stroke-dashoffset="seg.dashOffset"
            stroke-linecap="butt"
          />
        </svg>
        <div class="absolute inset-0 flex flex-col items-center justify-center">
          <span class="text-xs font-bold leading-none">{{ total }}</span>
        </div>
      </div>
      <div class="flex-1 w-full space-y-1">
        <div v-for="seg in segments" :key="seg.name" class="flex items-center justify-between text-xs">
          <div class="flex items-center gap-1.5 min-w-0">
            <span class="size-2 rounded-full shrink-0" :style="{ backgroundColor: seg.color }" />
            <span class="truncate">{{ seg.name }}</span>
          </div>
          <div class="flex items-center gap-2 text-muted-foreground shrink-0">
            <span>{{ seg.count }}</span>
            <span class="text-[11px] w-8 text-right">{{ Math.round(seg.pct * 100) }}%</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
