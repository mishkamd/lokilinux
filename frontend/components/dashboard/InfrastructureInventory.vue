<script setup lang="ts">
import { Server, ArrowRight } from 'lucide-vue-next'
import type { InventoryServer } from '~/stores/dashboard'
import type { Category } from '~/stores/servers'

const props = defineProps<{
  servers: InventoryServer[]
  categories: Category[]
  loading?: boolean
  error?: boolean
}>()

const { statusColor } = useServers()

const categoryFilter = ref('')
const categoryOptions = computed(() => [
  { label: 'All environments', value: '' },
  ...props.categories.map((c) => ({ label: c.name, value: c.id })),
])

const filteredServers = computed(() =>
  categoryFilter.value ? props.servers.filter((s) => s.category_id === categoryFilter.value) : props.servers,
)

function categoryName(categoryId: string | null): string {
  if (!categoryId) return '—'
  return props.categories.find((c) => c.id === categoryId)?.name ?? '—'
}

function lastSeen(iso: string | null): string {
  if (!iso) return 'Never'
  const diffSec = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (diffSec < 60) return 'Just now'
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`
  return `${Math.floor(diffSec / 86400)}d ago`
}

// The widget lives in a half-width grid column — a 578px card. All seven
// columns do not fit in it, and a table wider than its card grows a scrollbar
// of its own. IP and Environment start hidden; the Columns menu brings them
// back and /servers carries the whole inventory.
const columns: { key: string; label: string; noSort?: boolean }[] = [
  { key: 'hostname', label: 'Name' },
  { key: 'os_name', label: 'OS' },
  { key: 'status', label: 'Status' },
  { key: 'ip_address', label: 'IP' },
  // The cell shows the category name, so sorting by the raw id would sort by
  // the wrong thing.
  { key: 'category_id', label: 'Environment', noSort: true },
  { key: 'last_seen_at', label: 'Last Seen' },
  { key: 'cve_count', label: 'CVEs' },
]

const hiddenColumns = ['ip_address', 'category_id']
</script>

<template>
  <div class="surface-card rounded-[var(--radius-md)] p-3">
    <div class="flex items-center justify-between mb-2.5 gap-2">
      <div class="flex items-center gap-1.5 text-muted-foreground min-w-0">
        <span class="flex items-center justify-center size-5 rounded-md bg-[color-mix(in_oklch,var(--primary-active)_15%,transparent)] text-primary-active shrink-0">
          <Server class="size-3" />
        </span>
        <h2 class="label-caps truncate">Infrastructure Inventory</h2>
      </div>
      <div class="flex items-center gap-2 shrink-0">
        <Select v-model="categoryFilter" :options="categoryOptions" class="w-36 h-7 text-xs" />
        <NuxtLink to="/servers" class="focus-ring flex items-center gap-1 text-xs font-medium text-primary-text dark:text-primary-active shrink-0 py-1 -my-1">
          View all
          <ArrowRight class="size-3" />
        </NuxtLink>
      </div>
    </div>

    <WidgetState
      v-if="props.error || props.loading"
      :error="props.error ? 'Failed to load inventory.' : null"
      :loading="props.loading"
      :rows="4"
      row-class="h-8 rounded-md"
    />
    <template v-else-if="!filteredServers.length">
      <EmptyState>No servers match this filter.</EmptyState>
    </template>
    <DataTable
      v-else
      class="widget-table"
      :rows="filteredServers"
      :columns="columns"
      :hidden-columns="hiddenColumns"
      preferences-key="dashboard-inventory"
      sortable
      caption="Infrastructure inventory"
    >
      <template #hostname-data="{ row }">
        <NuxtLink
          :to="`/servers/${row.id}`"
          class="focus-ring font-medium hover:text-primary-text dark:hover:text-primary-active transition-colors py-1 -my-1"
        >
          {{ row.hostname }}
        </NuxtLink>
      </template>
      <template #status-data="{ row }">
        <Badge size="xs" :color="statusColor(row.status)">{{ row.status }}</Badge>
      </template>
      <template #os_name-data="{ row }">
        <span class="text-xs text-muted-foreground">{{ row.os_name ?? '—' }}</span>
      </template>
      <template #ip_address-data="{ row }">
        <span class="font-mono text-xs text-muted-foreground">{{ row.ip_address ?? '—' }}</span>
      </template>
      <template #category_id-data="{ row }">
        <span class="text-xs text-muted-foreground">{{ categoryName(row.category_id) }}</span>
      </template>
      <template #last_seen_at-data="{ row }">
        <span class="text-xs text-muted-foreground">{{ lastSeen(row.last_seen_at) }}</span>
      </template>
      <template #cve_count-data="{ row }">
        <Badge v-if="row.cve_count > 0" size="xs" color="red">{{ row.cve_count }}</Badge>
        <span v-else class="text-xs text-muted-foreground">0</span>
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
