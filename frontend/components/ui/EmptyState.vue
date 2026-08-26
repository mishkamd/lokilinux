<script setup lang="ts">
import type { Component } from 'vue'
import { cn } from '~/utils/cn'

const props = defineProps<{
  icon?: Component
  class?: string
}>()
</script>

<template>
  <div :class="cn('py-6 text-center text-sm text-muted-foreground', props.class)">
    <component :is="icon" v-if="icon" class="size-5 mx-auto mb-2 text-muted-foreground/60" />
    <slot />
  </div>
</template>
