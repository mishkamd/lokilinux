<script setup lang="ts">
import { cn } from '~/utils/cn'
import { X } from 'lucide-vue-next'

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
const isOpen = ref(false)

const normalized = computed(() =>
  props.options.map((o) =>
    typeof o === 'string' ? { label: o || props.placeholder || 'Option', value: o } : o,
  ),
)

const selected = computed(() =>
  normalized.value.filter((o) => props.modelValue?.includes(o.value)),
)

const filtered = computed(() => {
  if (!search.value) return normalized.value.filter((o) => !props.modelValue?.includes(o.value))
  return normalized.value.filter(
    (o) =>
      !props.modelValue?.includes(o.value) &&
      (o.label.toLowerCase().includes(search.value.toLowerCase()) ||
        o.value.toLowerCase().includes(search.value.toLowerCase())),
  )
})

function addValue(value: string) {
  const newValues = [...(props.modelValue || []), value]
  emit('update:modelValue', newValues)
  emit('change')
  search.value = ''
}

function removeValue(value: string) {
  const newValues = (props.modelValue || []).filter((v) => v !== value)
  emit('update:modelValue', newValues)
  emit('change')
}

function selectOption(value: string) {
  addValue(value)
  isOpen.value = false
}

const containerRef = ref(null)

onClickOutside(containerRef, () => {
  isOpen.value = false
})
</script>

<template>
  <div ref="containerRef" class="relative w-full">
    <!-- Selected chips -->
    <div
      :class="cn(
        'flex min-h-8 w-full flex-wrap gap-1 rounded-lg border border-input bg-card px-2.5 py-1 text-[14px] ring-offset-background transition-colors focus-within:outline-none focus-within:ring-2 focus-within:ring-ring focus-within:border-primary',
        props.class,
      )"
    >
      <!-- Chips for selected values -->
      <div
        v-for="item in selected"
        :key="item.value"
        class="inline-flex items-center gap-1 rounded bg-muted px-2 py-0.5 text-xs"
      >
        <span>{{ item.label }}</span>
        <button
          type="button"
          @click="removeValue(item.value)"
          class="ml-0.5 text-muted-foreground hover:text-foreground"
        >
          <X class="size-3" />
        </button>
      </div>

      <!-- Input for search/add -->
      <input
        v-model="search"
        :placeholder="selected.length === 0 ? placeholder : ''"
        @focus="isOpen = true"
        @keydown.escape="isOpen = false"
        class="flex-1 min-w-24 bg-transparent outline-none placeholder:text-muted-foreground"
      />
    </div>

    <!-- Dropdown menu -->
    <div
      v-if="isOpen && filtered.length > 0"
      class="absolute top-full left-0 right-0 z-50 mt-1 max-h-48 overflow-y-auto rounded-lg border border-input bg-card shadow-lg"
    >
      <button
        v-for="opt in filtered"
        :key="opt.value"
        type="button"
        @click="selectOption(opt.value)"
        class="block w-full px-3 py-2 text-left text-sm hover:bg-muted focus:bg-muted focus:outline-none"
      >
        {{ opt.label }}
      </button>
    </div>
  </div>
</template>
