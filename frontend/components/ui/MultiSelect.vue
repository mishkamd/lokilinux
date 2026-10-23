<script setup lang="ts">
import { cn } from '~/utils/cn'
import { Check, X } from 'lucide-vue-next'
import {
  ComboboxAnchor,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxItemIndicator,
  ComboboxPortal,
  ComboboxRoot,
  ComboboxViewport,
} from 'radix-vue'

defineOptions({ inheritAttrs: false })

type Option = string | { label: string; value: string }

const props = defineProps<{
  modelValue?: string[]
  options: Option[]
  placeholder?: string
  class?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [string[]]
  'change': []
}>()

const search = ref('')
const open = ref(false)

const normalized = computed(() =>
  props.options
    .map((o) =>
      typeof o === 'string' ? { label: o || props.placeholder || 'Option', value: o } : o,
    )
    // radix's ComboboxItem throws on an empty-string value — and an empty
    // option carries no meaning in a multi-select anyway.
    .filter((o) => o.value !== ''),
)

const selected = computed(() =>
  normalized.value.filter((o) => props.modelValue?.includes(o.value)),
)

const model = computed(() => props.modelValue ?? [])

// Radix narrows the navigable set through filterFunction; the full option
// list stays mounted and radix hides the non-matching rows (v-show).
function filterFunction(values: string[], term: string): string[] {
  const q = term.trim().toLowerCase()
  if (!q) return values
  return values.filter((v) => {
    const opt = normalized.value.find((o) => o.value === v)
    if (!opt) return false
    return opt.label.toLowerCase().includes(q) || v.toLowerCase().includes(q)
  })
}

function onModelUpdate(values: string | string[]) {
  // radix types the emit as a plain string; with `multiple` it is an array.
  emit('update:modelValue', Array.isArray(values) ? values : [])
  emit('change')
}

function removeValue(value: string) {
  onModelUpdate((props.modelValue ?? []).filter((v) => v !== value))
}
</script>

<template>
  <ComboboxRoot
    class="relative w-full"
    :model-value="model"
    :filter-function="filterFunction"
    multiple
    v-model:open="open"
    v-model:search-term="search"
    @update:model-value="onModelUpdate"
  >
    <ComboboxAnchor
      :class="cn(
        'flex min-h-8 w-full flex-wrap items-center gap-1 rounded-[var(--radius-sm)] border border-input bg-card px-2.5 py-1 text-sm ring-offset-background transition-all duration-[var(--duration-fast)] focus-within:outline-none focus-within:ring-2 focus-within:ring-ring focus-within:border-primary focus-within:shadow-[0_0_0_3px_color-mix(in_oklch,var(--ring)_15%,transparent)]',
        props.class,
      )"
    >
      <!-- Chips for selected values -->
      <span
        v-for="item in selected"
        :key="item.value"
        class="inline-flex items-center gap-1 rounded-[var(--radius-sm)] bg-muted px-2 py-0.5 text-xs"
      >
        <span>{{ item.label }}</span>
        <button
          type="button"
          class="focus-ring ml-0.5 rounded text-muted-foreground hover:text-foreground"
          :aria-label="`Remove ${item.label}`"
          @mousedown.prevent
          @click="removeValue(item.value)"
        >
          <X class="size-3" />
        </button>
      </span>

      <!-- Search / add input -->
      <ComboboxInput
        class="focus-ring min-w-24 flex-1 bg-transparent outline-none placeholder:text-muted-foreground"
        :placeholder="selected.length === 0 ? placeholder : ''"
        @focus="open = true"
      />
    </ComboboxAnchor>

    <ComboboxPortal>
      <ComboboxContent
        :side-offset="6"
        position="popper"
        class="z-50 max-h-64 w-[var(--radix-combobox-trigger-width)] overflow-hidden rounded-[var(--radius-md)] border border-input bg-popover text-popover-foreground shadow-[var(--shadow-overlay)] data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95"
      >
        <ComboboxViewport class="p-1">
          <ComboboxItem
            v-for="opt in normalized"
            :key="opt.value"
            :value="opt.value"
            class="relative flex h-8 cursor-pointer select-none items-center rounded-md pl-7 pr-2 text-field outline-none transition-colors data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground data-[state=checked]:text-primary-active"
          >
            <ComboboxItemIndicator class="absolute left-2 inline-flex items-center">
              <Check class="size-3.5" />
            </ComboboxItemIndicator>
            {{ opt.label }}
          </ComboboxItem>
          <ComboboxEmpty>
            <EmptyState class="py-2">No matching options.</EmptyState>
          </ComboboxEmpty>
        </ComboboxViewport>
      </ComboboxContent>
    </ComboboxPortal>
  </ComboboxRoot>
</template>
