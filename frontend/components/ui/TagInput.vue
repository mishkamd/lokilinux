<script setup lang="ts">
import { cn } from '~/utils/cn'
import { X } from 'lucide-vue-next'

defineOptions({ inheritAttrs: false })

// Freeform string[] input — MultiSelect.vue's chip visual, but for values
// with no fixed option set (package names, tags). Enter/comma/blur commits
// the current text as a chip; Backspace on an empty field pops the last one.
const props = defineProps<{
  modelValue?: string[]
  placeholder?: string
  class?: string
}>()

const emit = defineEmits<{ 'update:modelValue': [string[]] }>()

const draft = ref('')

function commitDraft() {
  const value = draft.value.trim()
  draft.value = ''
  if (!value) return
  const current = props.modelValue ?? []
  if (current.includes(value)) return
  emit('update:modelValue', [...current, value])
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' || event.key === ',') {
    event.preventDefault()
    commitDraft()
  } else if (event.key === 'Backspace' && draft.value === '' && (props.modelValue?.length ?? 0) > 0) {
    emit('update:modelValue', props.modelValue!.slice(0, -1))
  }
}

function removeAt(index: number) {
  emit('update:modelValue', (props.modelValue ?? []).filter((_, i) => i !== index))
}
</script>

<template>
  <div
    :class="cn(
      'flex min-h-8 w-full flex-wrap items-center gap-1 rounded-[var(--radius-sm)] border border-input bg-card px-2.5 py-1 text-[14px] ring-offset-background transition-all duration-[var(--duration-fast)] focus-within:outline-none focus-within:ring-2 focus-within:ring-ring focus-within:border-primary focus-within:shadow-[0_0_0_3px_color-mix(in_oklch,var(--ring)_15%,transparent)]',
      props.class,
    )"
  >
    <span
      v-for="(item, index) in modelValue ?? []" :key="item"
      class="inline-flex items-center gap-1 rounded bg-muted px-2 py-0.5 text-xs"
    >
      <span>{{ item }}</span>
      <button type="button" class="ml-0.5 text-muted-foreground hover:text-foreground" @click="removeAt(index)">
        <X class="size-3" />
      </button>
    </span>
    <input
      v-model="draft"
      :placeholder="(modelValue ?? []).length === 0 ? placeholder : ''"
      class="min-w-24 flex-1 bg-transparent outline-none placeholder:text-muted-foreground"
      @keydown="onKeydown"
      @blur="commitDraft"
    >
  </div>
</template>
