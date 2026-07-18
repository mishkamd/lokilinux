<script setup lang="ts">
import { CheckboxRoot, CheckboxIndicator } from 'radix-vue'
import { Check } from 'lucide-vue-next'
import { cn } from '~/utils/cn'

const props = defineProps<{
  modelValue?: boolean
  label?: string
  disabled?: boolean
  class?: string
}>()

const emit = defineEmits<{ 'update:modelValue': [boolean] }>()
</script>

<template>
  <label class="flex items-center gap-2 cursor-pointer">
    <CheckboxRoot
      :checked="modelValue"
      :disabled="disabled"
      :class="cn(
        'peer size-4 shrink-0 rounded-sm border border-primary ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground',
        props.class
      )"
      @update:checked="emit('update:modelValue', $event)"
    >
      <CheckboxIndicator class="flex items-center justify-center text-current">
        <Check class="size-3" />
      </CheckboxIndicator>
    </CheckboxRoot>
    <span v-if="label" class="text-sm">{{ label }}</span>
  </label>
</template>
