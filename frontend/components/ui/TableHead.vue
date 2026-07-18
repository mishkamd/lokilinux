<script setup lang="ts">
import { cn } from '~/utils/cn'
defineProps<{ class?: string }>()
</script>

<template>
  <th :class="cn('h-8 px-3 text-left align-middle text-[12px] font-semibold uppercase tracking-wide text-muted-foreground', $props.class)">
    <slot />
  </th>
</template>
