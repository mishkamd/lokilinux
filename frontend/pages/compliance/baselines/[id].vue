<script setup lang="ts">
import { Plus } from 'lucide-vue-next'
import type { BaselineVersionStatus } from '~/stores/compliance'

const route = useRoute()
const baselineId = String(route.params.id)

const store = useComplianceStore()
const { selectedBaseline, versions, versionsLoading } = storeToRefs(store)
const { canEdit, isAdmin } = useCurrentUser()
const toast = useToast()

onMounted(async () => {
  await store.fetchBaseline(baselineId)
  await store.fetchVersions(baselineId)
})

const STATUS_COLOR: Record<BaselineVersionStatus, string> = {
  DRAFT: 'gray',
  PENDING_APPROVAL: 'amber',
  APPROVED: 'amber',
  PUBLISHED: 'green',
  DEPRECATED: 'gray',
}

const tabs = [
  { label: 'Versions', slot: 'versions' },
  { label: 'Details', slot: 'details' },
]

const showNewVersion = ref(false)
const newVersionForm = ref({ expected_state: '{}', change_summary: '' })
const savingVersion = ref(false)
const versionFormError = ref<string | null>(null)

async function submitNewVersion() {
  versionFormError.value = null
  let expectedState: Record<string, unknown>
  try {
    expectedState = JSON.parse(newVersionForm.value.expected_state || '{}')
  } catch {
    versionFormError.value = 'Expected state must be valid JSON.'
    return
  }
  savingVersion.value = true
  try {
    await store.createVersion(baselineId, {
      expected_state: expectedState,
      change_summary: newVersionForm.value.change_summary || undefined,
    })
    toast.add({ title: 'New draft version created' })
    showNewVersion.value = false
    newVersionForm.value = { expected_state: '{}', change_summary: '' }
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to create version', color: 'red' })
  } finally {
    savingVersion.value = false
  }
}

const busyVersionId = ref<string | null>(null)

async function runAction(action: 'submit' | 'approve' | 'publish' | 'rollback', versionId: string) {
  busyVersionId.value = versionId
  try {
    if (action === 'submit') await store.submitVersion(baselineId, versionId)
    else if (action === 'approve') await store.approveVersion(baselineId, versionId)
    else if (action === 'publish') await store.publishVersion(baselineId, versionId)
    else await store.rollbackVersion(baselineId, versionId)
    toast.add({ title: `Version ${action === 'rollback' ? 'rolled back' : action + 'ted'}` })
  } catch (err) {
    const message = (err as { data?: { detail?: string } })?.data?.detail ?? `Failed to ${action}`
    toast.add({ title: message, color: 'red' })
  } finally {
    busyVersionId.value = null
  }
}
</script>

<template>
  <div v-if="selectedBaseline">
    <PageHeader
      :title="selectedBaseline.name"
      :description="selectedBaseline.description || 'No description'"
      :back="{ to: '/compliance/baselines', label: 'Back to baselines' }"
    >
      <template #badges><Badge color="gray">{{ selectedBaseline.scope_type }}</Badge></template>
    </PageHeader>

    <AppTabs :items="tabs">
      <template #versions>
        <div class="flex justify-end mb-3">
          <Button v-if="canEdit" size="sm" @click="showNewVersion = true">
            <Plus class="size-4" /> New version
          </Button>
        </div>
        <Skeleton v-if="versionsLoading" class="h-32 w-full" />
        <div v-else class="space-y-2">
          <Card v-for="v in versions" :key="v.id">
            <div class="flex items-center justify-between">
              <div>
                <p class="font-mono text-sm font-semibold">v{{ v.version }}</p>
                <p class="text-xs text-muted-foreground">{{ v.change_summary || 'No summary' }}</p>
                <p class="text-xs font-mono text-muted-foreground mt-1">{{ v.content_hash.slice(0, 16) }}…</p>
              </div>
              <div class="flex items-center gap-2">
                <Badge :color="STATUS_COLOR[v.status]" size="xs">{{ v.status }}</Badge>
                <template v-if="canEdit">
                  <Button v-if="v.status === 'DRAFT'" size="xs" variant="outline"
                          :loading="busyVersionId === v.id" @click="runAction('submit', v.id)">
                    Submit
                  </Button>
                  <Button v-if="isAdmin && v.status === 'PENDING_APPROVAL'" size="xs" variant="outline"
                          :loading="busyVersionId === v.id" @click="runAction('approve', v.id)">
                    Approve
                  </Button>
                  <Button v-if="isAdmin && v.status === 'APPROVED'" size="xs"
                          :loading="busyVersionId === v.id" @click="runAction('publish', v.id)">
                    Publish
                  </Button>
                  <Button v-if="isAdmin && v.status === 'DEPRECATED'" size="xs" variant="outline"
                          :loading="busyVersionId === v.id" @click="runAction('rollback', v.id)">
                    Roll back to this
                  </Button>
                </template>
              </div>
            </div>
          </Card>
          <EmptyState v-if="versions.length === 0">No versions yet.</EmptyState>
        </div>
      </template>

      <template #details>
        <dl class="grid grid-cols-2 gap-3 text-sm">
          <div><dt class="text-muted-foreground">Scope selector</dt>
               <dd class="font-mono text-xs">{{ JSON.stringify(selectedBaseline.scope_selector) }}</dd></div>
          <div><dt class="text-muted-foreground">Status</dt>
               <dd><Badge :color="selectedBaseline.is_enabled ? 'green' : 'gray'" size="xs">
                 {{ selectedBaseline.is_enabled ? 'Enabled' : 'Disabled' }}</Badge></dd></div>
          <div><dt class="text-muted-foreground">Created</dt>
               <dd class="font-mono">{{ new Date(selectedBaseline.created_at).toLocaleString() }}</dd></div>
          <div><dt class="text-muted-foreground">Updated</dt>
               <dd class="font-mono">{{ new Date(selectedBaseline.updated_at).toLocaleString() }}</dd></div>
        </dl>
      </template>
    </AppTabs>

    <Dialog v-model="showNewVersion" title="New draft version">
      <template #body>
        <div class="space-y-4">
          <FormField label="Change summary">
            <Input v-model="newVersionForm.change_summary" placeholder="What changed and why" />
          </FormField>
          <FormField label="Expected state" help="JSON, keyed by domain">
            <textarea
              v-model="newVersionForm.expected_state"
              rows="8"
              class="flex w-full rounded-lg border border-input bg-card px-2.5 py-1.5 text-[13px] font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-primary"
            />
          </FormField>
          <Alert v-if="versionFormError" color="red">{{ versionFormError }}</Alert>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showNewVersion = false">Cancel</Button>
        <Button :loading="savingVersion" @click="submitNewVersion">Create draft</Button>
      </template>
    </Dialog>
  </div>
  <Skeleton v-else class="h-64 w-full" />
</template>
