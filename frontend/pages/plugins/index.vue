<script setup lang="ts">
const { canEdit } = useCurrentUser()
const store = usePluginsStore()

await store.fetchPlugins()

const statusColor = (s: string): string =>
  ({ ENABLED: 'green', INSTALLED: 'green', DISABLED: 'gray', INSTALLING: 'gray', INSTALLING_FAILED: 'red', ERROR: 'red' } as Record<string, string>)[s] ?? 'gray'

// Poll while an install is in flight — agents report back on their next
// heartbeat (~60s), so the page refreshes itself instead of showing a
// frozen INSTALLING badge.
const hasInstalling = computed(() => store.plugins.some(p => p.installation_status === 'INSTALLING'))
let poll: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  poll = setInterval(() => { if (hasInstalling.value) store.fetchPlugins() }, 5000)
})
onUnmounted(() => clearInterval(poll))
</script>

<template>
  <div>
    <PageHeader description="Agent-side plugins reported via heartbeat.">
      <div class="flex flex-wrap items-center gap-3">
        <Badge color="gray">{{ store.total }} plugins</Badge>
      </div>
    </PageHeader>

    <Alert v-if="store.error" color="red" title="Failed to load plugins" :description="store.error" class="mb-4" />

    <EmptyState v-else-if="!store.plugins.length && !store.loading" class="mb-4">No plugins available</EmptyState>

    <div class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
      <Card v-for="plugin in store.plugins" :key="plugin.id">
        <template #header>
          <div class="flex items-center justify-between">
            <h3 class="section-title">{{ plugin.display_name ?? plugin.name }}</h3>
            <Badge
              :color="statusColor(plugin.installation_status)"
              :class="plugin.installation_status === 'INSTALLING' ? 'animate-pulse' : ''"
            >
              {{ plugin.installation_status }}
            </Badge>
          </div>
        </template>

        <p class="text-sm text-muted-foreground">{{ plugin.description }}</p>
        <p class="text-xs text-muted-foreground mt-1">by {{ plugin.author }} · v{{ plugin.version }}</p>

        <Alert v-if="plugin.installation_status === 'INSTALLING'" color="blue" title="Installing on agents — completes on their next heartbeat…" />
        <Alert v-else-if="plugin.installation_status === 'INSTALLING_FAILED'" color="red" title="Installation failed on one or more agents — check job results, then retry." />

        <template #footer>
          <div class="flex gap-2">
            <Button
              v-if="['INSTALLED', 'DISABLED'].includes(plugin.installation_status) && canEdit"
              size="sm"
              @click="store.enablePlugin(plugin.id)"
            >Enable</Button>
            <Button
              v-if="plugin.installation_status === 'ENABLED' && canEdit"
              size="sm"
              variant="secondary"
              @click="store.disablePlugin(plugin.id)"
            >Disable</Button>
            <Button
              v-if="!['INSTALLING', 'INSTALLED', 'ENABLED', 'DISABLED'].includes(plugin.installation_status) && canEdit"
              size="sm"
              @click="store.installPlugin(plugin.id)"
            >Install</Button>
          </div>
        </template>
      </Card>
    </div>
  </div>
</template>
