<script setup lang="ts">
import { cn } from '~/utils/cn'
import {
  SelectRoot,
  SelectTrigger,
  SelectValue,
  SelectIcon,
  SelectPortal,
  SelectContent,
  SelectViewport,
  SelectItem,
  SelectItemText,
  SelectItemIndicator,
  SelectScrollUpButton,
  SelectScrollDownButton,
} from 'radix-vue'
import { Check, ChevronDown, ChevronUp } from 'lucide-vue-next'

defineOptions({ inheritAttrs: false })

type Option = string | { label: string; value: string }

const props = defineProps<{
  modelValue?: string
  options: Option[]
  placeholder?: string
  class?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [string]
  'change': []
}>()

const EMPTY = '__empty__'

const normalized = computed(() =>
  props.options.map((o) => {
    const { label, value } = typeof o === 'string' ? { label: o || props.placeholder || 'All', value: o } : o
    return { label, value: value === '' ? EMPTY : value }
  }),
)

const internalValue = computed(() => (props.modelValue === '' ? EMPTY : props.modelValue))

const currentLabel = computed(
  () => normalized.value.find((o) => o.value === internalValue.value)?.label,
)

function onChange(value: string) {
  emit('update:modelValue', value === EMPTY ? '' : value)
  emit('change')
}

const attrs = useAttrs()
</script>

<template>
  <SelectRoot :model-value="internalValue" @update:model-value="onChange">
    <SelectTrigger
      :class="cn(
        'group flex h-8 w-full items-center justify-between gap-2 rounded-[var(--radius-sm)] border border-input bg-card px-2.5 py-1 text-[14px] ring-offset-background transition-all duration-[var(--duration-fast)] hover:border-ring/50 focus:outline-none focus:ring-2 focus:ring-ring focus:border-primary focus:shadow-[0_0_0_3px_color-mix(in_oklch,var(--ring)_15%,transparent)] disabled:cursor-not-allowed disabled:opacity-50 data-[placeholder]:text-muted-foreground',
        props.class,
      )"
      v-bind="attrs"
    >
      <span class="truncate">
        <SelectValue :placeholder="placeholder ?? 'Select…'">{{ currentLabel }}</SelectValue>
      </span>
      <SelectIcon as-child>
        <ChevronDown class="size-3.5 shrink-0 text-muted-foreground transition-transform duration-200 group-data-[state=open]:rotate-180" />
      </SelectIcon>
    </SelectTrigger>

    <SelectPortal>
      <SelectContent
        :side-offset="6"
        position="popper"
        class="z-50 max-h-64 w-[var(--radix-select-trigger-width)] overflow-hidden rounded-[var(--radius-md)] border border-input bg-popover text-popover-foreground shadow-[var(--shadow-overlay)] data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95"
      >
        <SelectScrollUpButton class="flex h-6 items-center justify-center bg-popover text-muted-foreground">
          <ChevronUp class="size-3.5" />
        </SelectScrollUpButton>

        <SelectViewport class="p-1">
          <SelectItem
            v-for="opt in normalized"
            :key="opt.value"
            :value="opt.value"
            class="relative flex h-8 cursor-pointer select-none items-center rounded-md pl-7 pr-2 text-[13px] outline-none transition-colors data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground data-[state=checked]:text-primary-active data-[disabled]:pointer-events-none data-[disabled]:opacity-40"
          >
            <SelectItemIndicator class="absolute left-2 inline-flex items-center">
              <Check class="size-3.5" />
            </SelectItemIndicator>
            <SelectItemText>{{ opt.label }}</SelectItemText>
          </SelectItem>
        </SelectViewport>

        <SelectScrollDownButton class="flex h-6 items-center justify-center bg-popover text-muted-foreground">
          <ChevronDown class="size-3.5" />
        </SelectScrollDownButton>
      </SelectContent>
    </SelectPortal>
  </SelectRoot>
</template>
