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
    class="group relative flex min-h-[136px] flex-col gap-3 overflow-hidden rounded-xl border border-white/[0.06] bg-card p-5 transition-all duration-200 ease-out hover:-translate-y-0.5 hover:border-primary-active/40"
  >
    <div class="relative flex items-center justify-between gap-2">
      <div class="flex min-w-0 items-center gap-2 text-muted-foreground">
        <span class="flex size-7 shrink-0 items-center justify-center rounded-md bg-[color-mix(in_oklch,var(--primary-active)_15%,transparent)] text-primary-active transition-transform duration-200 ease-out group-hover:scale-110 group-hover:rotate-6">
          <component :is="props.icon" class="size-4" />
        </span>
        <span class="label-caps truncate text-[13px]">{{ props.label }}</span>
      </div>
      <span class="flex shrink-0 items-center gap-1 text-[13px] font-medium text-primary">
        {{ props.viewAllLabel }}
        <ArrowRight class="size-3 transition-transform duration-200 ease-out group-hover:translate-x-0.5" />
      </span>
    </div>

    <div class="relative flex flex-1 flex-wrap items-end justify-between gap-x-3 gap-y-1">
      <div class="font-mono text-4xl font-bold leading-none tabular-nums transition-colors duration-200 group-hover:text-primary-active">
        {{ props.value }}
      </div>
      <div v-if="hasBadges" class="flex min-w-0 flex-wrap justify-end gap-1">
        <Badge v-for="badge in props.badges" :key="badge.label" size="sm" :color="badge.color ?? 'gray'">
          {{ badge.label }}
        </Badge>
      </div>
      <span v-else-if="props.subtitle" class="shrink-0 text-[13px] text-muted-foreground">
        {{ props.subtitle }}
      </span>
      <span v-else-if="props.emptyBadgesText" class="shrink-0 text-[13px] text-muted-foreground">
        {{ props.emptyBadgesText }}
      </span>
    </div>
  </NuxtLink>
</template>
