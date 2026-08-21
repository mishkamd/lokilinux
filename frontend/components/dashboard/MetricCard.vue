<script setup lang="ts">
import { ArrowRight } from 'lucide-vue-next'
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
  /** Large, low-opacity brand icon in the card's empty corner — reuses
   * `icon` by default rather than requiring every caller to pass a second one. */
  decor?: boolean
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
    class="group relative flex min-h-[104px] flex-col gap-2 overflow-hidden rounded-[var(--radius-md)] border border-[color-mix(in_oklch,var(--foreground)_6%,transparent)] bg-card p-3 shadow-[var(--shadow-surface)] transition-all duration-[var(--duration-normal)] ease-[var(--ease-out-expo)] hover:-translate-y-0.5 hover:shadow-[var(--shadow-raised)] hover:border-[color-mix(in_oklch,var(--border),var(--primary)_20%)]"
  >
    <component
      :is="props.icon" v-if="props.decor"
      class="pointer-events-none absolute -right-2 top-1/2 size-16 -translate-y-1/2 text-primary-active opacity-[0.07]"
      aria-hidden="true"
    />
    <div class="relative flex items-center justify-between gap-2">
      <div class="flex min-w-0 items-center gap-2 text-muted-foreground">
        <span class="flex size-6 shrink-0 items-center justify-center rounded-md bg-[color-mix(in_oklch,var(--primary-active)_15%,transparent)] text-primary-active transition-transform duration-200 ease-out group-hover:scale-110 group-hover:rotate-6">
          <component :is="props.icon" class="size-3.5" />
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
        <span v-else-if="hasTrend" class="shrink-0 text-[12px]" :class="props.trendUp === false ? 'text-destructive' : 'text-success'">
          {{ props.trend }}
          <span v-if="props.trendLabel" class="text-muted-foreground">{{ props.trendLabel }}</span>
        </span>
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

      <MetricAreaChart v-if="hasChart" :data="props.chartData!" :color="CHART_COLOR_VAR[props.chartColor]" class="-mx-1" />
    </template>
  </NuxtLink>
</template>
