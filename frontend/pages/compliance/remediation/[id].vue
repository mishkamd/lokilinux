<script setup lang="ts">
import type { RemediationPlanStatus } from '~/stores/compliance'

const route = useRoute()
const planId = String(route.params.id)

const store = useComplianceStore()
const { selectedRemediationPlan, remediationActions } = storeToRefs(store)
const { isAdmin } = useCurrentUser()
const toast = useToast()

onMounted(async () => {
  await store.fetchRemediationPlan(planId)
  await store.fetchRemediationActions(planId)
})

const STATUS_COLORS: Record<RemediationPlanStatus, string> = {
  DRAFT: 'gray', PENDING_APPROVAL: 'amber', APPROVED: 'amber',
  EXECUTING: 'amber', COMPLETED: 'green', FAILED: 'red', ROLLED_BACK: 'gray',
}

const busy = ref(false)
async function submit() {
  busy.value = true
  try {
    await store.submitRemediationPlan(planId)
    toast.add({ title: 'Plan submitted for approval' })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to submit', color: 'red' })
  } finally {
    busy.value = false
  }
}
async function approve() {
  busy.value = true
  try {
    await store.approveRemediationPlan(planId)
    toast.add({ title: 'Plan approved — dispatching to the Job Engine' })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to approve', color: 'red' })
  } finally {
    busy.value = false
  }
}

const columns = [
  { key: 'sequence', label: '#' },
  { key: 'agent_id', label: 'Server' },
  { key: 'provider', label: 'Provider' },
  { key: 'rendered_body', label: 'Action' },
]
</script>

<template>
  <div v-if="selectedRemediationPlan">
    <div class="flex items-center justify-between mb-4">
      <div>
        <h2 class="text-lg font-semibold">{{ selectedRemediationPlan.name }}</h2>
        <p class="text-sm text-muted-foreground">Trigger: {{ selectedRemediationPlan.trigger_type }}</p>
      </div>
      <div class="flex items-center gap-2">
        <Badge v-if="selectedRemediationPlan.is_emergency" color="red">Emergency</Badge>
        <Badge :color="STATUS_COLORS[selectedRemediationPlan.status]">{{ selectedRemediationPlan.status }}</Badge>
        <Button v-if="isAdmin && selectedRemediationPlan.status === 'DRAFT'" size="sm" :loading="busy" @click="submit">
          Submit for approval
        </Button>
        <Button v-if="isAdmin && selectedRemediationPlan.status === 'PENDING_APPROVAL'" size="sm" :loading="busy" @click="approve">
          Approve &amp; dispatch
        </Button>
      </div>
    </div>

    <h3 class="text-sm font-semibold mb-2">Actions</h3>
    <DataTable :rows="remediationActions" :columns="columns">
      <template #provider-data="{ row }"><Badge color="gray" size="xs">{{ row.provider }}</Badge></template>
      <template #rendered_body-data="{ row }">
        <pre class="font-mono text-xs whitespace-pre-wrap max-w-xl">{{ row.rendered_body }}</pre>
      </template>
    </DataTable>
  </div>
  <Skeleton v-else class="h-64 w-full" />
</template>
