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
      <NuxtLink to="/alerts" class="focus-ring flex items-center gap-1 text-xs font-medium text-primary-text dark:text-primary-active shrink-0">
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
    <Table v-else>
      <TableHeader>
        <TableRow>
          <TableHead>Severity</TableHead>
          <TableHead>Incident</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Duration</TableHead>
          <TableHead>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        <TableRow v-for="incident in props.incidents" :key="incident.id">
          <TableCell><Badge size="xs" :color="severityColor(incident.severity)">{{ severityLabel(incident.severity) }}</Badge></TableCell>
          <TableCell>
            <p class="font-medium leading-tight">{{ incident.title }}</p>
            <p class="text-xs text-muted-foreground">{{ hostname(incident) }}</p>
          </TableCell>
          <TableCell class="text-xs text-muted-foreground">{{ incident.alert_type ?? '—' }}</TableCell>
          <TableCell class="font-mono text-xs text-muted-foreground">{{ duration(incident.triggered_at) }}</TableCell>
          <TableCell><Badge size="xs" :color="STATUS_COLOR[incident.status] ?? 'gray'">{{ incident.status }}</Badge></TableCell>
        </TableRow>
      </TableBody>
    </Table>
  </div>
</template>
