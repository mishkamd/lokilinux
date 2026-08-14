<script setup lang="ts">
import { ProgressIndicator, ProgressRoot } from 'radix-vue'
import { cn } from '~/utils/cn'

const props = withDefaults(defineProps<{
  modelValue: number
  max?: number
  class?: string
  indicatorClass?: string
}>(), { max: 100 })
</script>

<template>
  <ProgressRoot
    :model-value="props.modelValue"
    :max="props.max"
    :class="cn('relative h-1.5 w-full overflow-hidden rounded-full bg-muted', props.class)"
  >
    <ProgressIndicator
      :class="cn('h-full w-full flex-1 bg-primary transition-transform duration-[var(--duration-normal)] ease-[var(--ease-out-expo)]', props.indicatorClass)"
      :style="{ transform: `translateX(-${100 - (100 * props.modelValue) / props.max}%)` }"
    />
  </ProgressRoot>
</template>
