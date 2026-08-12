<script setup lang="ts">
import { cn } from '~/utils/cn'

const COLOR: Record<string, Record<string, string>> = {
  red:    { soft: 'bg-red-50 text-red-700 dark:bg-[color-mix(in_oklch,var(--destructive)_16%,transparent)] dark:text-red-400', solid: 'bg-destructive text-white' },
  green:  { soft: 'bg-green-50 text-green-700 dark:bg-[color-mix(in_oklch,var(--success)_16%,transparent)] dark:text-green-400', solid: 'bg-success text-white' },
  gray:   { soft: 'bg-muted text-muted-foreground', solid: 'bg-secondary text-secondary-foreground' },
  // Compliance module (docs/compliance/11-FRONTEND.md D9): medium-severity
  // findings need a distinct color — gray reads as "no severity", not "medium".
  amber:  { soft: 'bg-amber-50 text-amber-700 dark:bg-[color-mix(in_oklch,var(--warning)_16%,transparent)] dark:text-amber-400', solid: 'bg-warning text-white' },
  orange: { soft: 'bg-orange-50 text-orange-700 dark:bg-orange-500/15 dark:text-orange-400', solid: 'bg-orange-600 text-white' },
}

const props = withDefaults(defineProps<{
  color?: string
  variant?: 'soft' | 'solid'
  size?: 'xs' | 'sm' | 'md'
  class?: string
}>(), { color: 'gray', variant: 'soft', size: 'sm' })

const cls = computed(() => {
  const cv = COLOR[props.color] ?? COLOR.gray
  const colorCls = cv[props.variant!] ?? cv.soft
  const sizeCls = props.size === 'md' ? 'px-2.5 py-1 text-sm' : 'px-2 py-0.5 text-xs'
  return cn('inline-flex items-center rounded-full font-mono font-medium tracking-tight', colorCls, sizeCls, props.class)
})
</script>

<template>
  <span :class="cls"><slot /></span>
</template>
