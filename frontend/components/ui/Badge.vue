<script setup lang="ts">
import { cn } from '~/utils/cn'

const COLOR: Record<string, Record<string, string>> = {
  // One rule for every status: a 14% tint of the status color as surface, the
  // status color itself as text (both themes are >= 5.2:1 on that tint), and
  // the matching foreground token for the solid variant. The Tailwind palette
  // (bg-red-50 / text-red-700) is gone — it never followed the theme.
  red:    { soft: 'bg-[color-mix(in_oklch,var(--destructive)_14%,transparent)] text-destructive', solid: 'bg-destructive text-destructive-foreground', plain: 'text-destructive' },
  green:  { soft: 'bg-[color-mix(in_oklch,var(--success)_14%,transparent)] text-success', solid: 'bg-success text-success-foreground', plain: 'text-success' },
  gray:   { soft: 'bg-muted text-muted-foreground', solid: 'bg-secondary text-secondary-foreground', plain: 'text-muted-foreground' },
  // Compliance module (docs/compliance/11-FRONTEND.md D9): medium-severity
  // findings need a distinct color — gray reads as "no severity", not "medium".
  amber:  { soft: 'bg-[color-mix(in_oklch,var(--warning)_14%,transparent)] text-warning', solid: 'bg-warning text-warning-foreground', plain: 'text-warning' },
  orange: { soft: 'bg-[color-mix(in_oklch,var(--severity-high)_14%,transparent)] text-severity-high', solid: 'bg-severity-high text-severity-high-foreground', plain: 'text-severity-high' },
  // LOW severity's real color is Recon Blue (matches the donut's --info) —
  // previously missing, so LOW badges fell back to gray.
  blue:   { soft: 'bg-[color-mix(in_oklch,var(--info)_14%,transparent)] text-info', solid: 'bg-info text-info-foreground', plain: 'text-info' },
}

const props = withDefaults(defineProps<{
  color?: string
  variant?: 'soft' | 'solid' | 'plain'
  size?: 'xs' | 'sm' | 'md'
  class?: string
}>(), { color: 'gray', variant: 'soft', size: 'sm' })

const cls = computed(() => {
  const cv = COLOR[props.color] ?? COLOR.gray!
  const colorCls = cv[props.variant!] ?? cv.soft ?? ''
  const sizeCls = props.size === 'md' ? 'px-2.5 py-1 text-sm' : props.size === 'xs' ? 'px-1.5 py-px text-micro' : 'px-2 py-0.5 text-xs'
  const shapeCls = props.variant === 'plain' ? 'font-semibold' : 'rounded-full'
  return cn('inline-flex items-center font-mono font-medium tracking-tight', shapeCls, colorCls, sizeCls, props.class)
})
</script>

<template>
  <span :class="cls"><slot /></span>
</template>
