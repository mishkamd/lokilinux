<script setup lang="ts">
import { Siren, ArrowRight } from 'lucide-vue-next'
import type { Alert, InventoryServer } from '~/stores/dashboard'

const props = defineProps<{
  incidents: Alert[]
  inventory: InventoryServer[]
  loading?: boolean
  error?: boolean
}>()

const { severityColor, severityLabel } = useSeverity()

const STATUS_COLOR: Record<string, string> = {
  ACTIVE: 'red', ACKNOWLEDGED: 'gray', RESOLVED: 'green', EXPIRED: 'gray',
}

// Alert carries hostname from the backend; when it's null, resolve from the
// Inventory widget's already-loaded list via agent_id. Falls back to the raw
// id when the agent isn't in the (top-10) inventory slice.
function hostname(alert: Alert): string {
  if (alert.hostname) return alert.hostname
  if (!alert.agent_id) return '—'
  return props.inventory.find((s) => s.id === alert.agent_id)?.hostname ?? alert.agent_id
}

function duration(triggeredAt: string): string {
  const diffSec = Math.max(0, (Date.now() - new Date(triggeredAt).getTime()) / 1000)
  if (diffSec < 3600) return `${Math.max(1, Math.floor(diffSec / 60))}m`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ${Math.floor((diffSec % 3600) / 60)}m`
  return `${Math.floor(diffSec / 86400)}d`
}

// The widget lives in a half-width grid column — a 578px card. The alert type
// is the widest column and the title already spells the type out, so it
// starts hidden; the Columns menu brings it back and /alerts carries every
// alert.
const columns: { key: string; label: string; noSort?: boolean }[] = [
  // Severity has its own order (critical > high > medium > low) — sorting the
  // raw value alphabetically would rank it wrongly.
  { key: 'severity', label: 'Severity', noSort: true },
  { key: 'title', label: 'Incident' },
  { key: 'alert_type', label: 'Type' },
  { key: 'triggered_at', label: 'Duration' },
  { key: 'status', label: 'Status' },
]

const hiddenColumns = ['alert_type']
</script>

<template>
  <div class="surface-card rounded-[var(--radius-md)] p-3">
    <div class="flex items-center justify-between mb-2.5">
      <div class="flex items-center gap-1.5 text-muted-foreground">
        <span class="flex items-center justify-center size-5 rounded-md bg-[color-mix(in_oklch,var(--destructive)_15%,transparent)] text-destructive shrink-0">
          <Siren class="size-3" />
        </span>
        <h2 class="label-caps">Active Alerts</h2>
      </div>
      <NuxtLink to="/alerts" class="focus-ring flex items-center gap-1 text-xs font-medium text-primary-text dark:text-primary-active shrink-0 py-1 -my-1">
        View all
        <ArrowRight class="size-3" />
      </NuxtLink>
    </div>

    <WidgetState
      v-if="props.error || props.loading"
      :error="props.error ? 'Failed to load active alerts.' : null"
      :loading="props.loading"
      :rows="3"
      row-class="h-8 rounded-md"
    />
    <template v-else-if="!props.incidents.length">
      <EmptyState>No active alerts.</EmptyState>
    </template>
    <DataTable
      v-else
      class="widget-table"
      :rows="props.incidents"
      :columns="columns"
      :hidden-columns="hiddenColumns"
      preferences-key="dashboard-alerts"
      sortable
      caption="Active alerts"
    >
      <template #severity-data="{ row }">
        <Badge size="xs" :color="severityColor(row.severity)">{{ severityLabel(row.severity) }}</Badge>
      </template>
      <template #title-data="{ row }">
        <div>
          <p class="font-medium leading-tight">{{ row.title }}</p>
          <p class="text-xs text-muted-foreground">{{ hostname(row) }}</p>
        </div>
      </template>
      <template #triggered_at-data="{ row }">
        <span class="font-mono text-xs text-muted-foreground">{{ duration(row.triggered_at) }}</span>
      </template>
      <template #status-data="{ row }">
        <Badge size="xs" :color="STATUS_COLOR[row.status] ?? 'gray'">{{ row.status }}</Badge>
      </template>
    </DataTable>
  </div>
</template>

<style scoped>
/* The DataTable ships its own card chrome, and the widget is already a card —
   the table panel drops the second border and shadow so the widget reads as
   one surface instead of a card inside a card. */
.widget-table {
  border: 0;
  border-radius: 0;
  box-shadow: none;
  background: transparent;
}
</style>
