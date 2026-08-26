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
    <PageHeader title="Plugins" :description="'Agent-side plugins reported via heartbeat.'">
      <template #actions>
        <Badge color="gray">{{ store.total }} plugins</Badge>
      </template>
    </PageHeader>

    <div v-if="store.error" class="rounded-md border border-destructive p-4 text-sm text-destructive mb-4">
      Failed to load plugins: {{ store.error }}
    </div>

    <Alert v-else-if="!store.plugins.length && !store.loading" title="No plugins available" color="gray" class="mb-4" />

    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <Card v-for="plugin in store.plugins" :key="plugin.id">
        <template #header>
          <div class="flex items-center justify-between">
            <h3 class="font-semibold">{{ plugin.display_name ?? plugin.name }}</h3>
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

        <p v-if="plugin.installation_status === 'INSTALLING'" class="text-xs text-muted-foreground mt-2">
          Installing on agents — completes on their next heartbeat…
        </p>
        <p v-else-if="plugin.installation_status === 'INSTALLING_FAILED'" class="text-xs text-destructive mt-2">
          Installation failed on one or more agents — check job results, then retry.
        </p>

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
