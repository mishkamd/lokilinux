<script setup lang="ts">
const route = useRoute()
const policySetId = String(route.params.id)

const store = useComplianceStore()
const { selectedPolicySet, policySetRules, policySetCoverage } = storeToRefs(store)
const { canEdit, isAdmin } = useCurrentUser()
const toast = useToast()

onMounted(async () => {
  await store.fetchPolicySet(policySetId)
  await Promise.all([store.fetchPolicySetRules(policySetId), store.fetchPolicySetCoverage(policySetId)])
})

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'red', HIGH: 'red', MEDIUM: 'amber', LOW: 'gray',
}
const STATUS_COLORS: Record<string, string> = {
  DRAFT: 'gray', PUBLISHED: 'green', ARCHIVED: 'gray',
}

const busy = ref(false)

async function publish() {
  busy.value = true
  try {
    await store.publishPolicySet(policySetId)
    toast.add({ title: 'Policy set published' })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to publish', color: 'red' })
  } finally {
    busy.value = false
  }
}

async function archive() {
  if (!confirm('Archive this policy set? It will stop applying to any assigned scope.')) return
  busy.value = true
  try {
    await store.archivePolicySet(policySetId)
    toast.add({ title: 'Policy set archived' })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to archive', color: 'red' })
  } finally {
    busy.value = false
  }
}

async function newVersion() {
  busy.value = true
  try {
    const clone = await store.newPolicySetVersion(policySetId)
    toast.add({ title: 'New draft version created' })
    await navigateTo(`/compliance/policies/${clone.id}`)
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to create new version', color: 'red' })
  } finally {
    busy.value = false
  }
}

const tabs = [
  { label: 'Rules', slot: 'rules' },
  { label: 'Coverage', slot: 'coverage' },
]

const columns = [
  { key: 'title', label: 'Rule' },
  { key: 'domain', label: 'Domain' },
  { key: 'severity', label: 'Severity' },
  { key: 'check_source', label: 'Coverage' },
]
</script>

<template>
  <div v-if="selectedPolicySet">
    <div class="flex items-center justify-between mb-4">
      <div>
        <h2 class="text-lg font-semibold">{{ selectedPolicySet.name }}</h2>
        <p class="text-sm text-muted-foreground">{{ selectedPolicySet.description || 'No description' }}</p>
        <p v-if="selectedPolicySet.parent_policy_set_id" class="text-xs text-muted-foreground mt-1">
          New version of
          <NuxtLink :to="`/compliance/policies/${selectedPolicySet.parent_policy_set_id}`" class="text-primary hover:underline">
            a previously published set
          </NuxtLink>
        </p>
      </div>
      <div class="flex items-center gap-2">
        <Badge color="gray">{{ selectedPolicySet.framework }}</Badge>
        <Badge :color="STATUS_COLORS[selectedPolicySet.status] ?? 'gray'">
          {{ selectedPolicySet.status }} · v{{ selectedPolicySet.published_version }}
        </Badge>
        <Button v-if="canEdit && selectedPolicySet.status === 'DRAFT'" size="sm" :loading="busy" @click="publish">
          Publish
        </Button>
        <Button v-if="canEdit && selectedPolicySet.status === 'PUBLISHED'" size="sm" variant="outline" :loading="busy" @click="newVersion">
          New version
        </Button>
        <Button v-if="isAdmin && selectedPolicySet.status === 'PUBLISHED'" size="sm" color="amber" :loading="busy" @click="archive">
          Archive
        </Button>
      </div>
    </div>

    <AppTabs :items="tabs">
      <template #rules>
        <DataTable :rows="policySetRules" :columns="columns">
          <template #domain-data="{ row }"><Badge color="gray" size="xs">{{ row.domain }}</Badge></template>
          <template #severity-data="{ row }">
            <Badge :color="SEVERITY_COLORS[String(row.severity)] ?? 'gray'" size="xs">{{ row.severity }}</Badge>
          </template>
          <template #check_source-data="{ row }">
            <Badge :color="row.check_source === 'CEL' ? 'green' : 'gray'" size="xs">{{ row.check_source }}</Badge>
          </template>
        </DataTable>
      </template>

      <template #coverage>
        <div v-if="policySetCoverage" class="grid grid-cols-3 gap-4">
          <Card>
            <p class="text-xs text-muted-foreground">CEL-mapped (evaluable)</p>
            <p class="text-2xl font-semibold">{{ policySetCoverage.mapped }}</p>
          </Card>
          <Card>
            <p class="text-xs text-muted-foreground">Unmapped</p>
            <p class="text-2xl font-semibold">{{ policySetCoverage.unmapped }}</p>
          </Card>
          <Card>
            <p class="text-xs text-muted-foreground">Coverage</p>
            <p class="text-2xl font-semibold">{{ policySetCoverage.coverage_pct }}%</p>
          </Card>
        </div>
      </template>
    </AppTabs>
  </div>
  <Skeleton v-else class="h-64 w-full" />
</template>
