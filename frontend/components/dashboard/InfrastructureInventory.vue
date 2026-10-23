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
    <div v-else class="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>OS</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>IP</TableHead>
            <TableHead>Environment</TableHead>
            <TableHead>Last Seen</TableHead>
            <TableHead>CVEs</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="server in filteredServers" :key="server.id">
            <TableCell>
              <NuxtLink :to="`/servers/${server.id}`" class="focus-ring font-medium hover:text-primary-text dark:hover:text-primary-active transition-colors">
                {{ server.hostname }}
              </NuxtLink>
            </TableCell>
            <TableCell class="text-xs text-muted-foreground">{{ server.os_name ?? '—' }}</TableCell>
            <TableCell><Badge size="xs" :color="statusColor(server.status)">{{ server.status }}</Badge></TableCell>
            <TableCell class="font-mono text-xs text-muted-foreground">{{ server.ip_address ?? '—' }}</TableCell>
            <TableCell class="text-xs text-muted-foreground">{{ categoryName(server.category_id) }}</TableCell>
            <TableCell class="text-xs text-muted-foreground">{{ lastSeen(server.last_seen_at) }}</TableCell>
            <TableCell>
              <Badge v-if="server.cve_count > 0" size="xs" color="red">{{ server.cve_count }}</Badge>
              <span v-else class="text-xs text-muted-foreground">0</span>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>
  </div>
</template>
