<script setup lang="ts">
import { cn } from '~/utils/cn'

const COLOR: Record<string, Record<string, string>> = {
  red:    { soft: 'bg-red-50 text-red-700 dark:bg-[color-mix(in_oklch,var(--destructive)_16%,transparent)] dark:text-red-400', solid: 'bg-destructive text-white', plain: 'text-destructive' },
  green:  { soft: 'bg-green-50 text-green-700 dark:bg-[color-mix(in_oklch,var(--success)_16%,transparent)] dark:text-green-400', solid: 'bg-success text-white', plain: 'text-success' },
  gray:   { soft: 'bg-muted text-muted-foreground', solid: 'bg-secondary text-secondary-foreground', plain: 'text-muted-foreground' },
  // Compliance module (docs/compliance/11-FRONTEND.md D9): medium-severity
  // findings need a distinct color — gray reads as "no severity", not "medium".
  amber:  { soft: 'bg-amber-50 text-amber-700 dark:bg-[color-mix(in_oklch,var(--warning)_16%,transparent)] dark:text-amber-400', solid: 'bg-warning text-white', plain: 'text-warning' },
  orange: { soft: 'bg-orange-50 text-orange-700 dark:bg-orange-500/15 dark:text-orange-400', solid: 'bg-orange-600 text-white', plain: 'text-[var(--severity-high)]' },
  // LOW severity's real color is Recon Blue (matches the donut's --info) —
  // previously missing, so LOW badges fell back to gray.
  blue:   { soft: 'bg-blue-50 text-blue-700 dark:bg-[color-mix(in_oklch,var(--info)_16%,transparent)] dark:text-blue-400', solid: 'bg-info text-white', plain: 'text-info' },
}

const props = withDefaults(defineProps<{
  color?: string
  variant?: 'soft' | 'solid' | 'plain'
  size?: 'xs' | 'sm' | 'md'
  class?: string
}>(), { color: 'gray', variant: 'soft', size: 'sm' })

const cls = computed(() => {
  const cv = COLOR[props.color] ?? COLOR.gray
  const colorCls = cv[props.variant!] ?? cv.soft
  const sizeCls = props.size === 'md' ? 'px-2.5 py-1 text-sm' : props.size === 'xs' ? 'px-1.5 py-px text-[10px]' : 'px-2 py-0.5 text-xs'
  const shapeCls = props.variant === 'plain' ? 'font-semibold' : 'rounded-full'
  return cn('inline-flex items-center font-mono font-medium tracking-tight', shapeCls, colorCls, sizeCls, props.class)
})
</script>

<template>
  <span :class="cls"><slot /></span>
</template>
