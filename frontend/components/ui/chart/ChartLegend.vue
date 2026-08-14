<script setup lang="ts">
// Same rationale as ChartTooltip — shadcn's Legend/LegendContent split
// exists so Legend can be positioned independently of what renders inside
// it; we only ever render it directly under the chart, so one file covers it.
import { inject } from 'vue'
import { ChartConfigKey } from './context'

const config = inject(ChartConfigKey, {})
</script>

<template>
  <div class="flex flex-wrap items-center gap-3 mt-2">
    <div v-for="(series, key) in config" :key="key" class="flex items-center gap-1.5 text-xs text-muted-foreground">
      <span class="size-2 rounded-full shrink-0" :style="{ backgroundColor: series.color }" />
      {{ series.label }}
    </div>
  </div>
</template>
