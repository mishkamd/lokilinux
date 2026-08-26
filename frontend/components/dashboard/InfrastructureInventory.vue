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
        <NuxtLink to="/servers" class="flex items-center gap-1 text-[12px] font-medium text-primary dark:text-primary-active shrink-0">
          View all
          <ArrowRight class="size-3" />
        </NuxtLink>
      </div>
    </div>

    <div v-if="props.error" class="text-xs text-destructive py-4 text-center">
      Failed to load inventory.
    </div>
    <div v-else-if="props.loading" class="space-y-2">
      <Skeleton v-for="i in 4" :key="i" class="h-8 rounded-md" />
    </div>
    <div v-else-if="!filteredServers.length" class="text-xs text-muted-foreground py-4 text-center">
      No servers match this filter.
    </div>
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
              <NuxtLink :to="`/servers/${server.id}`" class="font-medium hover:text-primary dark:hover:text-primary-active transition-colors">
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
