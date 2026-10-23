<script setup lang="ts">
import { Server } from 'lucide-vue-next'
import { VisDonut, VisSingleContainer, VisTooltip } from '@unovis/vue'
import { VisDonutSelectors } from '@unovis/vue/components/donut'
import { donutTooltipTemplate, type DonutSegment } from './donutTooltip'

const props = defineProps<{ byStatus: Record<string, number> }>()

interface Segment extends DonutSegment { color: string }

const total = computed(() => Object.values(props.byStatus).reduce((a, b) => a + b, 0))

const segments = computed<Segment[]>(() => {
  const online = props.byStatus.ACTIVE ?? 0
  const offline = total.value - online
  return [
    { name: 'Online', count: online, pct: total.value > 0 ? Math.round((online / total.value) * 100) : 0, color: 'var(--success)' },
    { name: 'Offline', count: offline, pct: total.value > 0 ? Math.round((offline / total.value) * 100) : 0, color: 'var(--muted-foreground)' },
  ].filter(s => s.count > 0)
})

const value = (d: Segment) => d.count
const color = (d: Segment) => d.color

const triggers = { [VisDonutSelectors.segment]: donutTooltipTemplate }
</script>

<template>
  <div class="surface-card rounded-[var(--radius-md)] p-3">
    <div class="flex items-center gap-1.5 text-muted-foreground mb-2.5">
      <span class="flex items-center justify-center size-5 rounded-md bg-[color-mix(in_oklch,var(--primary-active)_15%,transparent)] text-primary-active shrink-0">
        <Server class="size-3" />
      </span>
      <h2 class="label-caps">Agent Status</h2>
    </div>
    <EmptyState v-if="total === 0" class="py-4">No agents registered.</EmptyState>
    <div v-else class="flex flex-col sm:flex-row items-center gap-3">
      <div class="donut-center relative shrink-0 size-24">
        <VisSingleContainer :data="segments" :height="96" :width="96">
          <VisDonut :value="value" :color="color" :arc-width="16" :corner-radius="2" :central-label="String(total)" />
          <VisTooltip :triggers="triggers" />
        </VisSingleContainer>
      </div>
      <div class="flex-1 w-full space-y-1">
        <div v-for="seg in segments" :key="seg.name" class="flex items-center justify-between text-xs">
          <div class="flex items-center gap-1.5 min-w-0">
            <span class="size-2 rounded-full shrink-0" :style="{ backgroundColor: seg.color }" />
            <span class="truncate">{{ seg.name }}</span>
          </div>
          <div class="flex items-center gap-2 text-muted-foreground shrink-0">
            <span class="font-medium tabular-nums">{{ seg.count }}</span>
            <span class="text-label w-8 text-right tabular-nums">{{ seg.pct }}%</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* The donut's centre total is a widget stat (DESIGN.md §Widget Stat: 18px/700)
   and the app's data font is mono with tabular digits (The Tabular Numerals
   Rule). Unovis draws the centre as SVG <text>, so its typography comes from
   Unovis's CSS variables — not from a Tailwind class. */
.donut-center {
  --vis-donut-central-label-font-size: 1.125rem;
  --vis-donut-central-label-font-weight: 700;
  --vis-donut-central-label-font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
</style>
