<script setup lang="ts">
import { cn } from '~/utils/cn'

// Semantic tokens only — the old Tailwind palette (red-50/red-800) sat outside
// the app's color system and broke in dark mode. A 14% tint of the status
// color as surface, full strength as text: the same treatment Badge uses.
const COLOR: Record<string, string> = {
  red: 'border-destructive/30 bg-destructive/10 text-destructive',
  green: 'border-success/30 bg-success/10 text-success',
  yellow: 'border-warning/30 bg-warning/10 text-warning',
  blue: 'border-info/30 bg-info/10 text-info',
  gray: 'border-border bg-muted text-foreground',
}

const props = defineProps<{
  title?: string
  description?: string
  color?: string
  class?: string
}>()
</script>

<template>
  <div :class="cn('rounded-[var(--radius-md)] border p-4', COLOR[props.color ?? 'gray'], props.class)">
    <p v-if="title" class="font-medium text-sm">{{ title }}</p>
    <p v-if="description" class="text-sm mt-1 opacity-80">{{ description }}</p>
    <slot />
  </div>
</template>
