<script setup lang="ts">
import {
  DialogRoot,
  DialogPortal,
  DialogOverlay,
  DialogContent,
  DialogClose,
} from 'radix-vue'
import { X } from 'lucide-vue-next'

const props = defineProps<{ modelValue?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean] }>()
</script>

<template>
  <DialogRoot :open="modelValue" @update:open="emit('update:modelValue', $event)">
    <DialogPortal>
      <DialogOverlay class="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
      <DialogContent
        class="fixed inset-y-0 right-0 z-50 h-full w-3/4 max-w-sm border-l border-border bg-card shadow-[var(--shadow-dialog)] transition ease-in-out data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right duration-[var(--duration-slow)] ease-[var(--ease-out-expo)] overflow-y-auto"
      >
        <DialogClose class="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2">
          <X class="size-4" />
        </DialogClose>
        <slot />
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
