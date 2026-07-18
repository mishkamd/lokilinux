<script setup lang="ts">
import { cn } from '~/utils/cn'
defineProps<{ class?: string; colspan?: number }>()
</script>

<template>
  <td :colspan="colspan" :class="cn('px-3 py-1.5 align-middle text-[14px]', $props.class)">
    <slot />
  </td>
</template>
