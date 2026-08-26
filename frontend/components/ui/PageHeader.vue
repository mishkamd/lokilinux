<script setup lang="ts">
import { ArrowLeft } from 'lucide-vue-next'

defineProps<{
  title?: string
  description?: string
  back?: { to: string; label: string }
}>()
</script>

<template>
  <div class="mb-4">
    <div v-if="title" class="flex flex-wrap items-center justify-between gap-3">
      <div class="flex flex-wrap items-center gap-3 min-w-0">
        <NuxtLink
          v-if="back"
          :to="back.to"
          class="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground shrink-0"
        >
          <ArrowLeft class="size-3.5" />
          {{ back.label }}
        </NuxtLink>
        <div v-if="$slots.badges" class="flex items-center gap-2 shrink-0">
          <slot name="badges" />
        </div>
        <h1 class="text-lg font-semibold tracking-tight truncate">{{ title }}</h1>
      </div>
      <div v-if="$slots.actions" class="flex items-center gap-1.5 shrink-0">
        <slot name="actions" />
      </div>
    </div>
    <p v-if="title && description" class="text-xs text-muted-foreground mt-1">{{ description }}</p>

    <div v-else-if="!title" class="flex flex-wrap items-center justify-between gap-3">
      <slot />
    </div>
  </div>
</template>
