<script setup lang="ts">
import { SEVERITY_COLORS } from '~/utils/complianceColors'

const route = useRoute()
const findingId = String(route.params.id)

const store = useComplianceStore()
const { selectedFinding } = storeToRefs(store)
const { canEdit } = useCurrentUser()
const toast = useToast()
const { format: fmtDateTime } = useDateTime()

onMounted(() => store.fetchFinding(findingId))

const RESULT_COLORS: Record<string, string> = {
  FAIL: 'red',
  ERROR: 'red',
  UNKNOWN: 'amber',
  PASS: 'green',
  NOT_APPLICABLE: 'gray',
  NOT_EVALUATED: 'gray',
}

const acting = ref(false)
async function acknowledge() {
  acting.value = true
  try {
    await store.acknowledgeFinding(findingId)
    toast.add({ title: 'Finding acknowledged' })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to acknowledge', color: 'red' })
  } finally {
    acting.value = false
  }
}
</script>

<template>
  <div v-if="selectedFinding">
    <PageHeader
      :title="selectedFinding.title"
      :description="`${selectedFinding.domain} · ${selectedFinding.hostname || selectedFinding.agent_id} · ${new Date(selectedFinding.time).toLocaleString()}`"
      :back="{ to: '/compliance/findings', label: 'Back to findings' }"
    >
      <template #badges>
        <Badge :color="SEVERITY_COLORS[selectedFinding.severity] ?? 'gray'">{{ selectedFinding.severity }}</Badge>
        <Badge :color="RESULT_COLORS[selectedFinding.result] ?? 'gray'">{{ selectedFinding.result }}</Badge>
      </template>
      <template #actions>
        <Button v-if="canEdit && !selectedFinding.acknowledged_at" size="sm" variant="outline" :loading="acting" @click="acknowledge">
          Acknowledge
        </Button>
        <NuxtLink v-if="selectedFinding.open_drift_event_id" :to="`/compliance/drift/${selectedFinding.open_drift_event_id}`">
          <Button size="sm" variant="outline">View configuration drift</Button>
        </NuxtLink>
      </template>
    </PageHeader>

    <dl class="grid grid-cols-2 gap-3 text-sm mb-6">
      <div><dt class="text-muted-foreground">Rule</dt><dd class="font-mono text-xs">{{ selectedFinding.rule_key }}</dd></div>
      <div><dt class="text-muted-foreground">Source</dt><dd>{{ selectedFinding.source || '—' }}</dd></div>
      <div v-if="selectedFinding.acknowledged_at"><dt class="text-muted-foreground">Acknowledged</dt><dd class="font-mono">{{ fmtDateTime(selectedFinding.acknowledged_at) }}</dd></div>
      <div v-if="selectedFinding.exception_id"><dt class="text-muted-foreground">Exception</dt><dd>Covered by an active exception</dd></div>
      <div v-if="selectedFinding.snapshot_taken_at"><dt class="text-muted-foreground">Snapshot</dt><dd class="font-mono text-xs">{{ fmtDateTime(selectedFinding.snapshot_taken_at) }}</dd></div>
      <div v-if="selectedFinding.error_message"><dt class="text-muted-foreground">Error</dt><dd class="text-destructive">{{ selectedFinding.error_message }}</dd></div>
    </dl>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <Card>
        <p class="text-xs font-semibold text-muted-foreground mb-2">Expected</p>
        <pre class="text-xs font-mono whitespace-pre-wrap">{{ JSON.stringify(selectedFinding.expected_value, null, 2) }}</pre>
      </Card>
      <Card>
        <p class="text-xs font-semibold text-muted-foreground mb-2">Observed (actual)</p>
        <pre class="text-xs font-mono whitespace-pre-wrap">{{ JSON.stringify(selectedFinding.actual_value, null, 2) }}</pre>
      </Card>
    </div>

    <Card class="mt-4">
      <p class="text-xs font-semibold text-muted-foreground mb-2">Evidence</p>
      <pre class="text-xs font-mono whitespace-pre-wrap">{{ JSON.stringify(selectedFinding.evidence, null, 2) }}</pre>
      <p v-if="selectedFinding.evidence_hash" class="mt-2 font-mono text-xs text-muted-foreground">
        blake3: {{ selectedFinding.evidence_hash }}
      </p>
    </Card>
  </div>
  <Skeleton v-else class="h-64 w-full" />
</template>
