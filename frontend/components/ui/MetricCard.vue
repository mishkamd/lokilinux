<script setup lang="ts">
import { ArrowRight, ArrowUp, ArrowDown } from 'lucide-vue-next'
import type { Component } from 'vue'
import type { ChartDataPoint } from '~/components/ui/chart/types'

interface StatBadge { label: string; color?: string }

const CHART_COLOR_VAR: Record<string, string> = {
  green: 'var(--chart-1)',
  red: 'var(--destructive)',
  blue: 'var(--info)',
  yellow: 'var(--warning)',
}

const DOT_COLOR_VAR: Record<string, string> = {
  green: 'var(--success)',
  red: 'var(--destructive)',
  blue: 'var(--info)',
  yellow: 'var(--warning)',
}

// The icon tint follows the same green/red/blue/yellow palette as
// chartColor/subtitleDot — every caller already picks one of these per
// card, so the icon tone reuses chartColor rather than a redundant prop.
const TONE_BG: Record<string, string> = {
  green: 'bg-[color-mix(in_oklch,var(--success)_15%,transparent)] text-success',
  red: 'bg-[color-mix(in_oklch,var(--destructive)_15%,transparent)] text-destructive',
  blue: 'bg-[color-mix(in_oklch,var(--info)_15%,transparent)] text-info',
  yellow: 'bg-[color-mix(in_oklch,var(--warning)_15%,transparent)] text-warning',
}

const props = withDefaults(defineProps<{
  icon: Component
  label: string
  value: number | string
  subtitle?: string
  subtitleDot?: 'green' | 'red' | 'blue' | 'yellow'
  to: string
  badges?: StatBadge[]
  emptyBadgesText?: string
  viewAllLabel?: string
  trend?: string
  trendUp?: boolean
  trendLabel?: string
  chartData?: ChartDataPoint[]
  chartColor?: 'green' | 'red' | 'blue' | 'yellow'
  loading?: boolean
}>(), {
  viewAllLabel: 'View all',
  chartColor: 'green',
})

// Badges are the richer signal — show them alone when present instead of
// stacking a generic subtitle on top of the same information twice.
const hasBadges = computed(() => !!props.badges?.length)
const hasTrend = computed(() => !hasBadges.value && !!props.trend)
const hasChart = computed(() => !!props.chartData?.length)
</script>

<template>
  <NuxtLink
    :to="props.to"
    class="surface-card group relative flex min-h-[104px] flex-col gap-2 overflow-hidden rounded-[var(--radius-md)] p-3"
  >
    <div class="relative flex items-center justify-between gap-2">
      <div class="flex min-w-0 items-center gap-2.5 text-muted-foreground">
        <span
          class="flex size-10 shrink-0 items-center justify-center rounded-[var(--radius-sm)] transition-transform duration-200 ease-out group-hover:scale-110 group-hover:rotate-6"
          :class="TONE_BG[props.chartColor]"
        >
          <component :is="props.icon" class="size-5" />
        </span>
        <span class="label-caps truncate">{{ props.label }}</span>
      </div>
      <span class="flex shrink-0 items-center gap-1 text-[12px] font-medium text-primary dark:text-primary-active">
        {{ props.viewAllLabel }}
        <ArrowRight class="size-3 transition-transform duration-200 ease-out group-hover:translate-x-0.5" />
      </span>
    </div>

    <template v-if="props.loading">
      <Skeleton class="h-8 w-16" />
      <Skeleton class="h-3 w-24" />
    </template>
    <template v-else>
      <div class="relative flex flex-1 flex-wrap items-end justify-between gap-x-2 gap-y-1">
        <div class="font-mono text-3xl font-bold leading-none tabular-nums transition-colors duration-200 group-hover:text-primary-active">
          {{ props.value }}
        </div>
        <div v-if="hasBadges" class="flex min-w-0 flex-wrap justify-end gap-1">
          <Badge
            v-for="badge in props.badges"
            :key="badge.label"
            size="sm"
            :color="badge.color ?? 'gray'"
            class="px-1.5 py-px text-[10px] leading-[1.4] whitespace-nowrap"
          >
            {{ badge.label }}
          </Badge>
        </div>
        <span v-else-if="props.subtitle" class="flex shrink-0 items-center gap-1.5 text-[12px] text-muted-foreground">
          <span
            v-if="props.subtitleDot"
            class="size-1.5 shrink-0 rounded-full"
            :style="{ backgroundColor: DOT_COLOR_VAR[props.subtitleDot] }"
          />
          {{ props.subtitle }}
        </span>
        <span v-else-if="props.emptyBadgesText" class="shrink-0 text-[12px] text-muted-foreground">
          {{ props.emptyBadgesText }}
        </span>
      </div>

      <span v-if="hasTrend" class="relative flex items-center gap-1 text-[12px]" :class="props.trendUp === false ? 'text-destructive' : 'text-success'">
        <ArrowDown v-if="props.trendUp === false" class="size-3" />
        <ArrowUp v-else class="size-3" />
        <span class="font-medium">{{ props.trend }}</span>
        <span v-if="props.trendLabel" class="text-muted-foreground">{{ props.trendLabel }}</span>
      </span>

      <MetricAreaChart v-if="hasChart" :data="props.chartData!" :color="CHART_COLOR_VAR[props.chartColor]" class="-mx-1" />
    </template>
  </NuxtLink>
</template>
