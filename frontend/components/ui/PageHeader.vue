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
    <NuxtLink
      v-if="back"
      :to="back.to"
      class="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-4"
    >
      <ArrowLeft class="size-3.5" />
      {{ back.label }}
    </NuxtLink>

    <div v-if="title" class="flex flex-wrap items-start justify-between gap-3" :class="{ 'mb-4': $slots.default }">
      <div>
        <div v-if="$slots.badges" class="flex items-center gap-2 mb-1">
          <slot name="badges" />
        </div>
        <h1 class="text-lg font-semibold tracking-tight">{{ title }}</h1>
        <p v-if="description" class="text-xs text-muted-foreground mt-0.5">{{ description }}</p>
      </div>
      <div v-if="$slots.actions" class="flex items-center gap-1.5 shrink-0">
        <slot name="actions" />
      </div>
    </div>

    <div v-else class="flex flex-wrap items-center justify-between gap-3">
      <slot />
    </div>
  </div>
</template>
