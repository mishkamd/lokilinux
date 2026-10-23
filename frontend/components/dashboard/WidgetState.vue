<script setup lang="ts">
import { RefreshCw } from 'lucide-vue-next'

/**
 * The three non-content states of a dashboard widget, in one place.
 *
 * Before this, every widget had its own copy: a different skeleton height, a
 * different empty message style, and an error state with no way back. The
 * point is not the markup — it is that the widget looks the same while it
 * loads and when it is empty, so the page does not jump.
 */
withDefaults(
  defineProps<{
    error?: string | null
    loading?: boolean
    /** Skeleton rows. */
    rows?: number
    /** Skeleton row height — match the real row height to avoid a jump. */
    rowClass?: string
    /** Optional retry action for the error state. */
    retry?: () => void
  }>(),
  { rows: 3, rowClass: 'h-8 rounded-md' },
)
</script>

<template>
  <div v-if="error" class="flex flex-col items-center gap-2 py-6 text-center">
    <Alert color="red" :title="error" />
    <button
      v-if="retry"
      type="button"
      class="focus-ring inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      @click="retry"
    >
      <RefreshCw class="size-3" />
      Retry
    </button>
  </div>
  <div v-else-if="loading" class="space-y-2">
    <Skeleton v-for="i in rows" :key="i" :class="rowClass" />
  </div>
  <slot />
</template>
