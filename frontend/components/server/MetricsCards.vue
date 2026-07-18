<script setup lang="ts">
import type { ServerMetrics } from '~/stores/servers'

const props = defineProps<{
  metrics: ServerMetrics | null
  loading: boolean
}>()

function pct(v: number | null): number | null {
  return v === null || v === undefined ? null : Math.round(v)
}

function formatBytes(bytes: number | null): string {
  if (bytes === null || bytes === undefined) return ''
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit++
  }
  return `${value.toFixed(value < 10 && unit > 0 ? 1 : 0)}${units[unit]}`
}

function usedOfTotal(used: number | null, total: number | null): string {
  if (!total) return ''
  return `${formatBytes(used)} / ${formatBytes(total)}`
}

const cpuPercent = computed(() => pct(props.metrics?.cpu_usage ?? null))
const ramPercent = computed(() => pct(props.metrics?.memory_usage ?? null))
const diskPercent = computed(() => pct(props.metrics?.disk_usage ?? null))
const swapPercent = computed(() => pct(props.metrics?.swap_usage ?? null))

const cpuDetail = computed(() => {
  const count = props.metrics?.cpu_count
  return count ? `${count} cores` : ''
})
const ramDetail = computed(() => usedOfTotal(props.metrics?.memory_used_bytes ?? null, props.metrics?.memory_total_bytes ?? null))
const diskDetail = computed(() => usedOfTotal(props.metrics?.disk_used_bytes ?? null, props.metrics?.disk_total_bytes ?? null))
const swapDetail = computed(() => usedOfTotal(props.metrics?.swap_used_bytes ?? null, props.metrics?.swap_total_bytes ?? null))
const hasSwap = computed(() => !!props.metrics?.swap_total_bytes)

function colorFor(v: number | null, threshold: number): string {
  return v && v > threshold ? 'var(--destructive)' : 'inherit'
}
</script>

<template>
  <template v-if="loading">
    <div v-for="label in ['CPU Usage', 'RAM Usage', 'Disk Usage', 'Swap Usage']" :key="label">
      <dt class="text-xs text-muted-foreground">{{ label }}</dt>
      <dd class="font-medium text-[13px] mt-0.5">
        <Skeleton class="h-4 w-10" />
      </dd>
    </div>
  </template>

  <template v-else>
    <div>
      <dt class="text-xs text-muted-foreground">CPU Usage</dt>
      <dd class="font-medium text-[13px] mt-0.5" :style="{ color: colorFor(cpuPercent, 80) }">
        {{ cpuPercent ?? '—' }}{{ cpuPercent !== null ? '%' : '' }}
      </dd>
      <dd v-if="cpuDetail" class="text-[11px] text-muted-foreground mt-0.5">{{ cpuDetail }}</dd>
    </div>
    <div>
      <dt class="text-xs text-muted-foreground">RAM Usage</dt>
      <dd class="font-medium text-[13px] mt-0.5" :style="{ color: colorFor(ramPercent, 85) }">
        {{ ramPercent ?? '—' }}{{ ramPercent !== null ? '%' : '' }}
      </dd>
      <dd v-if="ramDetail" class="text-[11px] text-muted-foreground mt-0.5">{{ ramDetail }}</dd>
    </div>
    <div>
      <dt class="text-xs text-muted-foreground">Disk Usage</dt>
      <dd class="font-medium text-[13px] mt-0.5" :style="{ color: colorFor(diskPercent, 90) }">
        {{ diskPercent ?? '—' }}{{ diskPercent !== null ? '%' : '' }}
      </dd>
      <dd v-if="diskDetail" class="text-[11px] text-muted-foreground mt-0.5">{{ diskDetail }}</dd>
    </div>
    <div v-if="hasSwap">
      <dt class="text-xs text-muted-foreground">Swap Usage</dt>
      <dd class="font-medium text-[13px] mt-0.5" :style="{ color: colorFor(swapPercent, 50) }">
        {{ swapPercent ?? '—' }}{{ swapPercent !== null ? '%' : '' }}
      </dd>
      <dd v-if="swapDetail" class="text-[11px] text-muted-foreground mt-0.5">{{ swapDetail }}</dd>
    </div>
  </template>
</template>
