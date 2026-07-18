<script setup lang="ts">
import { cn } from '~/utils/cn'

const props = defineProps<{ class?: string }>()
</script>

<template>
  <div :class="cn('rounded-xl border border-border bg-card text-card-foreground shadow-[0_0_0_1px_rgba(255,255,255,0.01)] transition-all duration-200 hover:-translate-y-0.5', props.class)">
    <div v-if="$slots.header" class="px-4 py-2.5 border-b border-border text-sm font-medium">
      <slot name="header" />
    </div>
    <div class="p-4">
      <slot name="body" />
      <slot />
    </div>
    <div v-if="$slots.footer" class="px-4 py-2.5 border-t border-border">
      <slot name="footer" />
    </div>
  </div>
</template>
