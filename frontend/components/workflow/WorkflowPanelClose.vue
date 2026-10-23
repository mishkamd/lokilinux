<script setup lang="ts">
import { X } from 'lucide-vue-next'

// One close control for both canvas inspectors (node + edge). They used to
// carry byte-identical copies of this button, so the focus treatment and the
// hit target drifted apart whenever one of them was touched.
defineEmits<{ close: [] }>()
</script>

<template>
  <button
    type="button"
    class="focus-ring inline-flex min-h-6 min-w-6 items-center justify-center rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
    aria-label="Close"
    @click="$emit('close')"
  >
    <X class="size-4" />
  </button>
</template>
