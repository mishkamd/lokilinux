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
const STATUS_COLORS: Record<string, string> = {
  OPEN: 'red', ACKNOWLEDGED: 'amber', IN_REMEDIATION: 'amber',
  RESOLVED: 'green', SUPPRESSED: 'gray', EXCEPTION: 'gray',
}
const isOpenOrAcked = computed(() =>
  ['OPEN', 'ACKNOWLEDGED'].includes(String(selectedDriftEvent.value?.status)),
)

const acting = ref(false)
async function acknowledge() {
  acting.value = true
  try {
    await store.acknowledgeDrift(eventId)
    toast.add({ title: 'Drift event acknowledged' })
  } catch {
    toast.add({ title: 'Failed to acknowledge', color: 'red' })
  } finally {
    acting.value = false
  }
}
async function resolve() {
  acting.value = true
  try {
    await store.resolveDrift(eventId)
    toast.add({ title: 'Drift event resolved' })
  } catch {
    toast.add({ title: 'Failed to resolve', color: 'red' })
  } finally {
    acting.value = false
  }
}
async function suppress() {
  acting.value = true
  try {
    await store.suppressDrift(eventId)
    toast.add({ title: 'Drift event suppressed' })
  } catch {
    toast.add({ title: 'Failed to suppress', color: 'red' })
  } finally {
    acting.value = false
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
        <Badge :color="STATUS_COLORS[selectedDriftEvent.status] ?? 'gray'">{{ selectedDriftEvent.status }}</Badge>
        <template v-if="canEdit && isOpenOrAcked">
          <Button v-if="selectedDriftEvent.status === 'OPEN'" size="sm" variant="outline" :loading="acting" @click="acknowledge">Acknowledge</Button>
          <Button size="sm" variant="outline" :loading="acting" @click="resolve">Resolve</Button>
          <Button size="sm" variant="outline" :loading="acting" @click="suppress">Suppress</Button>
        </template>
      </div>
    </div>

    <dl class="grid grid-cols-2 gap-3 text-sm mb-6">
      <div><dt class="text-muted-foreground">Compared against</dt><dd>{{ selectedDriftEvent.compared_against }}</dd></div>
      <div><dt class="text-muted-foreground">Change type</dt><dd>{{ selectedDriftEvent.change_type }}</dd></div>
      <div><dt class="text-muted-foreground">Occurrences</dt><dd>{{ selectedDriftEvent.occurrences }}×</dd></div>
      <div v-if="selectedDriftEvent.first_seen"><dt class="text-muted-foreground">First seen</dt><dd>{{ new Date(selectedDriftEvent.first_seen).toLocaleString() }}</dd></div>
      <div v-if="selectedDriftEvent.last_seen"><dt class="text-muted-foreground">Last seen</dt><dd>{{ new Date(selectedDriftEvent.last_seen).toLocaleString() }}</dd></div>
      <div v-if="selectedDriftEvent.resolved_at"><dt class="text-muted-foreground">Resolved at</dt><dd>{{ new Date(selectedDriftEvent.resolved_at).toLocaleString() }}</dd></div>
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
