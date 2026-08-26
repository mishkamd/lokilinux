<script setup lang="ts">
import { SEVERITY_COLORS, DRIFT_STATUS_COLORS } from '~/utils/complianceColors'
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

const isOpenOrAcked = computed(() =>
  ['OPEN', 'ACKNOWLEDGED'].includes(String(selectedDriftEvent.value?.status)),
)

const acting = ref(false)
async function acknowledge() {
  acting.value = true
  try {
    await store.acknowledgeDrift(eventId)
    toast.add({ title: 'Drift event acknowledged' })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to acknowledge', color: 'red' })
  } finally {
    acting.value = false
  }
}
async function resolve() {
  acting.value = true
  try {
    await store.resolveDrift(eventId)
    toast.add({ title: 'Drift event resolved' })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to resolve', color: 'red' })
  } finally {
    acting.value = false
  }
}
async function suppress() {
  acting.value = true
  try {
    await store.suppressDrift(eventId)
    toast.add({ title: 'Drift event suppressed' })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to suppress', color: 'red' })
  } finally {
    acting.value = false
  }
}
</script>

<template>
  <div v-if="selectedDriftEvent">
    <PageHeader
      :title="selectedDriftEvent.summary"
      :description="`${selectedDriftEvent.domain} · ${selectedDriftEvent.hostname || selectedDriftEvent.agent_id} · ${new Date(selectedDriftEvent.time).toLocaleString()}`"
      :back="{ to: '/compliance/drift', label: 'Back to drift' }"
    >
      <template #badges>
        <Badge :color="SEVERITY_COLORS[selectedDriftEvent.severity] ?? 'gray'">{{ selectedDriftEvent.severity }}</Badge>
        <Badge :color="DRIFT_STATUS_COLORS[selectedDriftEvent.status] ?? 'gray'">{{ selectedDriftEvent.status }}</Badge>
      </template>
      <template #actions>
        <template v-if="canEdit && isOpenOrAcked">
          <Button v-if="selectedDriftEvent.status === 'OPEN'" size="sm" variant="outline" :loading="acting" @click="acknowledge">Acknowledge</Button>
          <Button size="sm" variant="outline" :loading="acting" @click="resolve">Resolve</Button>
          <Button size="sm" variant="outline" :loading="acting" @click="suppress">Suppress</Button>
        </template>
      </template>
    </PageHeader>

    <dl class="grid grid-cols-2 gap-3 text-sm mb-6">
      <div><dt class="text-muted-foreground">Compared against</dt><dd>{{ selectedDriftEvent.compared_against }}</dd></div>
      <div><dt class="text-muted-foreground">Change type</dt><dd>{{ selectedDriftEvent.change_type }}</dd></div>
      <div><dt class="text-muted-foreground">Occurrences</dt><dd class="font-mono">{{ selectedDriftEvent.occurrences }}×</dd></div>
      <div v-if="selectedDriftEvent.first_seen"><dt class="text-muted-foreground">First seen</dt><dd class="font-mono">{{ new Date(selectedDriftEvent.first_seen).toLocaleString() }}</dd></div>
      <div v-if="selectedDriftEvent.last_seen"><dt class="text-muted-foreground">Last seen</dt><dd class="font-mono">{{ new Date(selectedDriftEvent.last_seen).toLocaleString() }}</dd></div>
      <div v-if="selectedDriftEvent.resolved_at"><dt class="text-muted-foreground">Resolved at</dt><dd class="font-mono">{{ new Date(selectedDriftEvent.resolved_at).toLocaleString() }}</dd></div>
    </dl>

    <h3 class="text-sm font-semibold mb-2">Field-level diff</h3>
    <div class="space-y-2">
      <Card v-for="d in driftDetails" :key="d.field_path">
        <p class="font-mono text-xs font-semibold mb-2">{{ d.field_path }}</p>
        <div class="grid grid-cols-2 gap-3 text-xs font-mono">
          <div class="text-destructive">- {{ JSON.stringify(d.old_value) }}</div>
          <div class="text-success">+ {{ JSON.stringify(d.new_value) }}</div>
        </div>
      </Card>
      <EmptyState v-if="driftDetails.length === 0">
        No field-level diff recorded for this event.
      </EmptyState>
    </div>
  </div>
  <Skeleton v-else class="h-64 w-full" />
</template>
