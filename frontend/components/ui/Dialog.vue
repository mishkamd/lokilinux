<script setup lang="ts">
import {
  DialogRoot,
  DialogPortal,
  DialogOverlay,
  DialogContent,
  DialogTitle,
  DialogClose,
} from 'radix-vue'
import { X } from 'lucide-vue-next'

const props = withDefaults(
  defineProps<{
    modelValue?: boolean
    title?: string
    /** Content max-width. Defaults to 'lg' (32rem) — the size every existing
     * call site was implicitly built around before this prop existed. */
    size?: 'sm' | 'lg' | 'xl' | 'full'
  }>(),
  { size: 'lg' },
)

const emit = defineEmits<{ 'update:modelValue': [boolean] }>()

const SIZE_CLASSES: Record<string, string> = {
  sm: 'max-w-sm',
  lg: 'max-w-lg',
  xl: 'max-w-3xl',
  full: 'max-w-5xl',
}
</script>

<template>
  <DialogRoot :open="modelValue" @update:open="(v) => emit('update:modelValue', v)">
    <DialogPortal>
      <DialogOverlay
        class="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0"
      />
      <DialogContent
        :class="[SIZE_CLASSES[props.size], 'fixed left-1/2 top-1/2 z-50 flex max-h-[85vh] w-full flex-col -translate-x-1/2 -translate-y-1/2 rounded-[28px] border border-border bg-card shadow-[0_8px_32px_rgba(0,0,0,0.5)] duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-48% data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-48%']"
      >
        <div v-if="title" class="flex items-center justify-between px-6 py-4 border-b border-border shrink-0">
          <DialogTitle class="text-base font-semibold">{{ title }}</DialogTitle>
          <DialogClose class="rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2">
            <X class="size-4" />
          </DialogClose>
        </div>
        <div v-if="$slots.default && !$slots.body && !$slots.footer" class="overflow-y-auto">
          <slot />
        </div>
        <template v-else>
          <div class="min-h-0 flex-1 px-6 py-4 overflow-y-auto">
            <slot name="body" />
          </div>
          <div v-if="$slots.footer" class="flex items-center justify-end gap-2 px-6 py-4 border-t border-border shrink-0">
            <slot name="footer" />
          </div>
        </template>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
