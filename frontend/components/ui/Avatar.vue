<script setup lang="ts">
import { cn } from '~/utils/cn'

defineProps<{
  class?: string
  fallback?: string
  size?: 'sm' | 'md' | 'lg'
}>()
</script>

<template>
  <span
    :class="cn(
      'inline-flex items-center justify-center rounded-full bg-muted text-muted-foreground font-medium',
      $props.size === 'lg' ? 'size-12 text-lg' : $props.size === 'sm' ? 'size-8 text-xs' : 'size-10 text-sm',
      $props.class
    )"
  >
    <slot>{{ fallback ?? '?' }}</slot>
  </span>
</template>
