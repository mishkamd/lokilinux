<script setup lang="ts">
import { ClipboardList } from 'lucide-vue-next'
import { CurveType } from '@unovis/ts'
import { VisAxis, VisLine } from '@unovis/vue'
import type { JobTrendPoint } from '~/stores/dashboard'
import type { ChartConfig } from '~/components/ui/chart/types'

const props = defineProps<{ points: JobTrendPoint[]; loading?: boolean }>()

const chartConfig: ChartConfig = {
  successful: { label: 'Successful', color: 'var(--chart-1)' },
  failed: { label: 'Failed', color: 'var(--destructive)' },
  running: { label: 'Running', color: 'var(--info)' },
}

const x = (_d: JobTrendPoint, i: number) => i
const ySuccessful = (d: JobTrendPoint) => d.successful
const yFailed = (d: JobTrendPoint) => d.failed
const yRunning = (d: JobTrendPoint) => d.running

function tickFormat(i: number) {
  const day = props.points[i]?.day
  if (!day) return ''
  return new Date(day).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
</script>

<template>
  <div class="surface-card rounded-[var(--radius-md)] p-3">
    <div class="flex items-center justify-between mb-2.5">
      <div class="flex items-center gap-1.5 text-muted-foreground">
        <span class="flex items-center justify-center size-5 rounded-md bg-[color-mix(in_oklch,var(--info)_15%,transparent)] text-info shrink-0">
          <ClipboardList class="size-3" />
        </span>
        <h2 class="label-caps">Job Execution</h2>
      </div>
      <NuxtLink to="/jobs" class="text-[12px] font-medium text-primary shrink-0">View All</NuxtLink>
    </div>

    <Skeleton v-if="props.loading" class="h-40 w-full" />
    <p v-else-if="points.length < 2" class="text-xs text-muted-foreground py-8 text-center">
      Not enough history yet — trend appears once jobs run.
    </p>
    <template v-else>
      <ChartContainer :config="chartConfig" :data="props.points" :height="180">
        <VisLine :x="x" :y="ySuccessful" color="var(--chart-1)" :curve-type="CurveType.MonotoneX" :line-width="2" />
        <VisLine :x="x" :y="yFailed" color="var(--destructive)" :curve-type="CurveType.MonotoneX" :line-width="2" />
        <VisLine :x="x" :y="yRunning" color="var(--info)" :curve-type="CurveType.MonotoneX" :line-width="2" />
        <VisAxis type="x" :tick-format="tickFormat" :num-ticks="5" />
        <ChartTooltip :x="x" label-key="day" />
      </ChartContainer>
      <ChartLegend />
    </template>
  </div>
</template>
