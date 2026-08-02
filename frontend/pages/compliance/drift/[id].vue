<script setup lang="ts">
const route = useRoute()
const eventId = String(route.params.id)

const store = useComplianceStore()
const { selectedDriftEvent, driftDetails } = storeToRefs(store)
const { canEdit } = useCurrentUser()
const toast = useToast()

onMounted(async () => {
  await store.fetchDriftEvent(eventId)
  await store.fetchDriftDetails(eventId)
})

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'red', HIGH: 'red', MEDIUM: 'amber', LOW: 'gray',
}

const acknowledging = ref(false)
async function acknowledge() {
  acknowledging.value = true
  try {
    await store.acknowledgeDrift(eventId)
    toast.add({ title: 'Drift event acknowledged' })
  } catch {
    toast.add({ title: 'Failed to acknowledge', color: 'red' })
  } finally {
    acknowledging.value = false
  }
}
</script>

<template>
  <div v-if="selectedDriftEvent">
    <div class="flex items-center justify-between mb-4">
      <div>
        <h2 class="text-lg font-semibold">{{ selectedDriftEvent.summary }}</h2>
        <p class="text-sm text-muted-foreground font-mono">
          {{ selectedDriftEvent.domain }} · agent {{ selectedDriftEvent.agent_id }} · {{ new Date(selectedDriftEvent.time).toLocaleString() }}
        </p>
      </div>
      <div class="flex items-center gap-2">
        <Badge :color="SEVERITY_COLORS[selectedDriftEvent.severity] ?? 'gray'">{{ selectedDriftEvent.severity }}</Badge>
        <Badge v-if="selectedDriftEvent.acknowledged_at" color="green">Acknowledged</Badge>
        <Button v-else-if="canEdit" size="sm" :loading="acknowledging" @click="acknowledge">Acknowledge</Button>
      </div>
    </div>

    <dl class="grid grid-cols-2 gap-3 text-sm mb-6">
      <div><dt class="text-muted-foreground">Compared against</dt><dd>{{ selectedDriftEvent.compared_against }}</dd></div>
      <div><dt class="text-muted-foreground">Change type</dt><dd>{{ selectedDriftEvent.change_type }}</dd></div>
    </dl>

    <h3 class="text-sm font-semibold mb-2">Field-level diff</h3>
    <div class="space-y-2">
      <Card v-for="d in driftDetails" :key="d.field_path">
        <p class="font-mono text-xs font-semibold mb-2">{{ d.field_path }}</p>
        <div class="grid grid-cols-2 gap-3 text-xs font-mono">
          <div class="text-red-600 dark:text-red-400">- {{ JSON.stringify(d.old_value) }}</div>
          <div class="text-green-600 dark:text-green-400">+ {{ JSON.stringify(d.new_value) }}</div>
        </div>
      </Card>
      <p v-if="driftDetails.length === 0" class="text-sm text-muted-foreground text-center py-6">
        No field-level diff recorded for this event.
      </p>
    </div>
  </div>
  <Skeleton v-else class="h-64 w-full" />
</template>
