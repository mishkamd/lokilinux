<script setup lang="ts">
import { cn } from '~/utils/cn'

const props = defineProps<{ class?: string }>()
</script>

<template>
  <div :class="cn('rounded-[var(--radius-md)] border border-border bg-card text-card-foreground shadow-[var(--shadow-surface)] transition-all duration-[var(--duration-normal)] ease-[var(--ease-out-expo)] hover:-translate-y-0.5 hover:shadow-[var(--shadow-raised)] hover:border-[color-mix(in_oklch,var(--border),var(--primary)_20%)]', props.class)">
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
