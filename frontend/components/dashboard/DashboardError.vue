<script setup lang="ts">
import { TriangleAlert } from 'lucide-vue-next'

withDefaults(defineProps<{
  title?: string
  message?: string
}>(), {
  title: 'Unable to load dashboard data',
  message: 'The LokiLinux API did not respond.',
})

const emit = defineEmits<{ retry: [] }>()
</script>

<template>
  <div class="surface-card rounded-[var(--radius-md)] p-8 flex flex-col items-center justify-center text-center gap-3">
    <span class="flex items-center justify-center size-10 rounded-full bg-[color-mix(in_oklch,var(--destructive)_15%,transparent)] text-destructive">
      <TriangleAlert class="size-5" />
    </span>
    <div>
      <p class="text-sm font-medium">{{ title }}</p>
      <p class="text-xs text-muted-foreground mt-1">{{ message }}</p>
    </div>
    <Button size="sm" variant="outline" @click="emit('retry')">Retry</Button>
  </div>
</template>
