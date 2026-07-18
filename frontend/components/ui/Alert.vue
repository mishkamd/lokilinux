<script setup lang="ts">
import { cn } from '~/utils/cn'

const COLOR: Record<string, string> = {
  red: 'border-red-200 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300',
  green: 'border-green-200 bg-green-50 text-green-800 dark:border-green-800 dark:bg-green-950/30 dark:text-green-300',
  yellow: 'border-yellow-200 bg-yellow-50 text-yellow-800 dark:border-yellow-800 dark:bg-yellow-950/30 dark:text-yellow-300',
  blue: 'border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-300',
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
  <div :class="cn('rounded-lg border p-4', COLOR[props.color ?? 'gray'], props.class)">
    <p v-if="title" class="font-medium text-sm">{{ title }}</p>
    <p v-if="description" class="text-sm mt-1 opacity-80">{{ description }}</p>
    <slot />
  </div>
</template>
