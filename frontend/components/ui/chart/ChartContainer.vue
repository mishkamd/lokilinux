<script setup lang="ts">
import { provide } from 'vue'
import { VisXYContainer } from '@unovis/vue'
import { cn } from '~/utils/cn'
import { ChartConfigKey } from './context'
import type { ChartConfig } from './types'

const props = withDefaults(defineProps<{
  config: ChartConfig
  data: unknown[]
  height?: number
  class?: string
}>(), { height: 160 })

provide(ChartConfigKey, props.config)
</script>

<template>
  <div
    :class="cn('aspect-auto w-full', props.class)"
    :style="{
      height: `${props.height}px`,
      '--vis-axis-grid-color': 'var(--border)',
      '--vis-dark-axis-grid-color': 'var(--border)',
      '--vis-axis-tick-color': 'var(--border)',
      '--vis-dark-axis-tick-color': 'var(--border)',
    }"
  >
    <VisXYContainer :data="props.data" :height="props.height">
      <slot />
    </VisXYContainer>
  </div>
</template>
