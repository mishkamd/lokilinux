<script setup lang="ts">
import { cn } from '~/utils/cn'

defineOptions({ inheritAttrs: false })

const props = defineProps<{
  modelValue?: string
  class?: string
  rows?: number
}>()

const emit = defineEmits<{ 'update:modelValue': [string] }>()
const attrs = useAttrs()
</script>

<template>
  <textarea
    :value="modelValue"
    :rows="rows ?? 4"
    :class="cn(
      'flex w-full rounded-lg border border-input bg-card px-2.5 py-1.5 text-[14px] ring-offset-background placeholder:text-muted-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-primary disabled:cursor-not-allowed disabled:opacity-50 font-mono',
      props.class
    )"
    v-bind="attrs"
    @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
  />
</template>
