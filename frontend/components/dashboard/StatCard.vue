<script setup lang="ts">
import { ArrowRight } from 'lucide-vue-next'
import type { Component } from 'vue'

interface StatBadge { label: string; color?: string }

const props = withDefaults(defineProps<{
  icon: Component
  label: string
  value: number | string
  subtitle?: string
  to: string
  badges?: StatBadge[]
  emptyBadgesText?: string
  viewAllLabel?: string
}>(), {
  viewAllLabel: 'Vezi tot',
})

// Badges are the richer signal — show them alone when present instead of
// stacking a generic subtitle on top of the same information twice.
const hasBadges = computed(() => !!props.badges?.length)
</script>

<template>
  <NuxtLink
    :to="props.to"
    class="group relative flex min-h-[104px] flex-col gap-2 overflow-hidden rounded-[var(--radius-md)] border border-[color-mix(in_oklch,var(--foreground)_6%,transparent)] bg-card p-4 shadow-[var(--shadow-surface)] transition-all duration-[var(--duration-normal)] ease-[var(--ease-out-expo)] hover:-translate-y-0.5 hover:shadow-[var(--shadow-raised)] hover:border-[color-mix(in_oklch,var(--border),var(--primary)_20%)]"
  >
    <div class="relative flex items-center justify-between gap-2">
      <div class="flex min-w-0 items-center gap-2 text-muted-foreground">
        <span class="flex size-6 shrink-0 items-center justify-center rounded-md bg-[color-mix(in_oklch,var(--primary-active)_15%,transparent)] text-primary-active transition-transform duration-200 ease-out group-hover:scale-110 group-hover:rotate-6">
          <component :is="props.icon" class="size-3.5" />
        </span>
        <span class="label-caps truncate text-[12px]">{{ props.label }}</span>
      </div>
      <span class="flex shrink-0 items-center gap-1 text-[12px] font-medium text-primary">
        {{ props.viewAllLabel }}
        <ArrowRight class="size-3 transition-transform duration-200 ease-out group-hover:translate-x-0.5" />
      </span>
    </div>

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
      <span v-else-if="props.subtitle" class="shrink-0 text-[12px] text-muted-foreground">
        {{ props.subtitle }}
      </span>
      <span v-else-if="props.emptyBadgesText" class="shrink-0 text-[12px] text-muted-foreground">
        {{ props.emptyBadgesText }}
      </span>
    </div>
  </NuxtLink>
</template>
