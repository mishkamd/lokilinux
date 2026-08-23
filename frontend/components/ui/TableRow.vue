<script setup lang="ts">
import { cn } from '~/utils/cn'
defineProps<{ class?: string }>()
</script>

<template>
  <tr :class="cn('h-10 border-b border-border transition-colors hover:bg-accent', $props.class)">
    <slot />
  </tr>
</template>
