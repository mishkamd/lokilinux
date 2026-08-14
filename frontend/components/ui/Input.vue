<script setup lang="ts">
import { cn } from '~/utils/cn'

defineOptions({ inheritAttrs: false })

const props = defineProps<{
  modelValue?: string | number
  class?: string
  readonly?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [string] }>()
const attrs = useAttrs()
</script>

<template>
  <input
    :value="modelValue"
    :readonly="readonly"
    :class="cn(
      'flex h-8 w-full rounded-[var(--radius-sm)] border border-input bg-card px-2.5 py-1 text-[14px] ring-offset-background placeholder:text-muted-foreground transition-all duration-[var(--duration-fast)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-primary focus-visible:shadow-[0_0_0_3px_color-mix(in_oklch,var(--ring)_15%,transparent)] disabled:cursor-not-allowed disabled:opacity-50',
      props.class
    )"
    v-bind="attrs"
    @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
  />
</template>
