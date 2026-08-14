<script setup lang="ts">
import { Activity } from 'lucide-vue-next'
import type { DashboardHealth } from '~/stores/dashboard'

const props = defineProps<{ health: DashboardHealth | null }>()

interface Metric { key: keyof DashboardHealth; label: string; unit: string; max: number }

const METRICS: Metric[] = [
  { key: 'cpu_usage', label: 'CPU', unit: '%', max: 100 },
  { key: 'memory_usage', label: 'Memory', unit: '%', max: 100 },
  { key: 'disk_usage', label: 'Disk', unit: '%', max: 100 },
  { key: 'network_latency_ms', label: 'Network', unit: 'ms', max: 200 },
]

function statusColor(pct: number): string {
  if (pct >= 90) return 'bg-destructive'
  if (pct >= 75) return 'bg-warning'
  return 'bg-primary'
}

const rows = computed(() => METRICS.map((m) => {
  const raw = props.health?.[m.key] ?? null
  const pct = raw === null ? 0 : Math.min(100, Math.round((raw / m.max) * 100))
  return { ...m, raw, pct }
}))

const hasData = computed(() => rows.value.some(r => r.raw !== null))
</script>

<template>
  <div class="surface-card rounded-[var(--radius-md)] p-3">
    <div class="flex items-center gap-1.5 text-muted-foreground mb-2.5">
      <span class="flex items-center justify-center size-5 rounded-md bg-[color-mix(in_oklch,var(--primary-active)_15%,transparent)] text-primary-active shrink-0">
        <Activity class="size-3" />
      </span>
      <h2 class="label-caps">Infrastructure Health</h2>
    </div>
    <div v-if="!hasData" class="text-xs text-muted-foreground py-4 text-center">No health data reported yet.</div>
    <div v-else class="space-y-2.5">
      <div v-for="row in rows" :key="row.key" class="space-y-1">
        <div class="flex items-center justify-between text-xs">
          <span class="text-muted-foreground">{{ row.label }}</span>
          <span class="font-medium tabular-nums">{{ row.raw !== null ? `${row.raw}${row.unit}` : '—' }}</span>
        </div>
        <Progress :model-value="row.pct" class="h-1.5" :indicator-class="statusColor(row.pct)" />
      </div>
    </div>
  </div>
</template>
