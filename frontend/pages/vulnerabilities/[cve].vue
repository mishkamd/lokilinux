<script setup lang="ts">
const route = useRoute()
const cveId = String(route.params.cve)

const store = useVulnerabilitiesStore()
const { selectedCve, selectedCveResources } = storeToRefs(store)
const { canEdit, isAdmin } = useCurrentUser()
const toast = useToast()

const loading = ref(true)
onMounted(async () => {
  try {
    await Promise.all([store.fetchCve(cveId), store.fetchCveResources(cveId)])
  } finally {
    loading.value = false
  }
})

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'red', HIGH: 'orange', MEDIUM: 'amber', LOW: 'green',
}
const STATUS_COLORS: Record<string, string> = {
  OPEN: 'red', PATCH_AVAILABLE: 'amber', IN_PROGRESS: 'amber',
  MITIGATED: 'gray', RESOLVED: 'green', ACCEPTED_RISK: 'gray',
}

const resourceColumns = [
  { key: 'hostname', label: 'Hostname' },
  { key: 'ip', label: 'IP' },
  { key: 'os_distro', label: 'OS' },
  { key: 'package_name', label: 'Package' },
  { key: 'package_version', label: 'Installed' },
  { key: 'fixed_version', label: 'Fixed' },
  { key: 'environment', label: 'Environment' },
  { key: 'last_scan_at', label: 'Last Scan' },
  { key: 'status', label: 'Status' },
]

// Timeline: first detected/last scan come from the resources actually
// reported; "fix available" and "patched" are derived from the same rows
// rather than invented — a stage only lights up if the data backs it.
const timeline = computed(() => {
  const rows = selectedCveResources.value
  const firstDetected = rows.length ? rows.map((r) => r.last_scan_at).filter(Boolean).sort()[0] : null
  const anyFixAvailable = rows.some((r) => r.fixed_version)
  const anyInProgress = rows.some((r) => r.status === 'IN_PROGRESS')
  const allPatched = rows.length > 0 && rows.every((r) => r.status === 'RESOLVED' || r.status === 'ACCEPTED_RISK')
  return [
    { label: 'First detected', done: rows.length > 0, detail: firstDetected ? new Date(firstDetected).toLocaleDateString() : null },
    { label: 'Fix available', done: anyFixAvailable },
    { label: 'Patch scheduled', done: anyInProgress || allPatched },
    { label: 'Patched', done: allPatched },
  ]
})

const selected = ref<(string | number)[]>([])

const remediating = ref(false)
async function remediate() {
  remediating.value = true
  try {
    await store.remediateCve(cveId, selected.value.length ? { agent_ids: selected.value as string[] } : {})
    toast.add({ title: 'Remediation plan created', description: 'Draft plan — submit and approve it to dispatch.' })
    await store.fetchCveResources(cveId)
    selected.value = []
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to create remediation plan', color: 'red' })
  } finally {
    remediating.value = false
  }
}

const showAcceptRisk = ref(false)
const acceptRiskReason = ref('')
const acceptingRisk = ref(false)
async function submitAcceptRisk() {
  if (!acceptRiskReason.value.trim()) return
  acceptingRisk.value = true
  try {
    await store.acceptRisk(cveId, {
      reason: acceptRiskReason.value,
      agent_ids: selected.value.length ? (selected.value as string[]) : undefined,
    })
    toast.add({ title: 'Risk accepted' })
    showAcceptRisk.value = false
    acceptRiskReason.value = ''
    selected.value = []
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to accept risk', color: 'red' })
  } finally {
    acceptingRisk.value = false
  }
}

const rescanning = ref(false)
async function rescan() {
  rescanning.value = true
  try {
    const res = await store.rescanCve(cveId, selected.value.length ? (selected.value as string[]) : undefined)
    toast.add({ title: `Rescan queued for ${res.agents_queued} server(s)`, description: 'Takes effect on their next heartbeat.' })
  } catch (err) {
    toast.add({ title: (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to queue rescan', color: 'red' })
  } finally {
    rescanning.value = false
  }
}
</script>

<template>
  <div>
    <Skeleton v-if="loading" class="h-64 w-full" />
    <div v-else-if="selectedCve">
      <PageHeader
        :title="selectedCve.cve_id"
        :description="selectedCve.description || 'No description available yet — enrichment runs in the background.'"
        :back="{ to: '/vulnerabilities', label: 'Back to vulnerabilities' }"
      >
        <template #badges>
          <Badge v-if="selectedCve.cvss_v3_severity" :color="SEVERITY_COLORS[selectedCve.cvss_v3_severity] ?? 'gray'">
            {{ selectedCve.cvss_v3_severity }}<span v-if="selectedCve.cvss_v3_score"> — {{ selectedCve.cvss_v3_score }}</span>
          </Badge>
          <Badge v-if="selectedCve.is_zero_day" color="red" variant="solid" size="xs">0-day</Badge>
          <Badge v-if="selectedCve.is_actively_exploited" color="red" size="xs">Actively exploited</Badge>
        </template>
      </PageHeader>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <Card class="lg:col-span-2">
          <template #header><p class="label-caps">Detection Timeline</p></template>
          <div class="flex items-center gap-2 overflow-x-auto py-2">
            <template v-for="(step, i) in timeline" :key="step.label">
              <div class="flex flex-col items-center gap-1 shrink-0">
                <span class="size-3 rounded-full" :class="step.done ? 'bg-success' : 'bg-muted border border-border'" />
                <span class="text-xs whitespace-nowrap" :class="step.done ? 'text-foreground' : 'text-muted-foreground'">{{ step.label }}</span>
                <span v-if="step.detail" class="text-xs text-muted-foreground font-mono">{{ step.detail }}</span>
              </div>
              <Separator v-if="i < timeline.length - 1" class="w-8" />
            </template>
          </div>
        </Card>
        <Card>
          <template #header><p class="label-caps">References</p></template>
          <ul class="space-y-1 text-xs">
            <li v-if="selectedCve.published_date">Published: <span class="font-mono">{{ new Date(selectedCve.published_date).toLocaleDateString() }}</span></li>
            <li>
              <a :href="`https://nvd.nist.gov/vuln/detail/${selectedCve.cve_id}`" target="_blank" rel="noopener" class="text-primary hover:underline">
                NVD detail page
              </a>
            </li>
          </ul>
        </Card>
      </div>

      <Card>
        <template #header>
          <div class="flex items-center justify-between flex-wrap gap-2">
            <p class="label-caps">Affected Resources ({{ selectedCveResources.length }})</p>
            <div v-if="canEdit" class="flex items-center gap-2">
              <Button size="xs" variant="outline" :loading="rescanning" @click="rescan">
                Rescan{{ selected.length ? ` (${selected.length})` : '' }}
              </Button>
              <Button v-if="isAdmin" size="xs" variant="outline" @click="showAcceptRisk = true">
                Accept risk{{ selected.length ? ` (${selected.length})` : '' }}
              </Button>
              <Button size="xs" :loading="remediating" @click="remediate">
                Remediate{{ selected.length ? ` (${selected.length})` : '' }}
              </Button>
            </div>
          </div>
        </template>
        <EmptyState v-if="selectedCveResources.length === 0">
          No resources currently report this CVE.
        </EmptyState>
        <DataTable
          v-else :rows="selectedCveResources" :columns="resourceColumns" row-key="agent_id"
          :selectable="canEdit" :selected="selected" @update:selected="selected = $event"
        >
          <template #hostname-data="{ row }">
            <NuxtLink :to="`/servers/${row.agent_id}`" class="font-mono text-xs text-primary hover:underline">
              {{ row.hostname || row.agent_id }}
            </NuxtLink>
          </template>
          <template #ip-data="{ row }"><span class="font-mono text-xs">{{ row.ip || '—' }}</span></template>
          <template #os_distro-data="{ row }"><span class="text-xs">{{ row.os_distro }} {{ row.os_version }}</span></template>
          <template #package_name-data="{ row }"><span class="font-mono text-xs">{{ row.package_name }}</span></template>
          <template #package_version-data="{ row }"><span class="font-mono text-xs">{{ row.package_version }}</span></template>
          <template #fixed_version-data="{ row }"><span class="font-mono text-xs">{{ row.fixed_version || '—' }}</span></template>
          <template #environment-data="{ row }">
            <Badge v-if="row.environment" color="gray" size="xs">{{ row.environment }}</Badge>
            <span v-else class="text-muted-foreground text-xs">—</span>
          </template>
          <template #last_scan_at-data="{ row }">
            <span class="font-mono text-xs">{{ row.last_scan_at ? new Date(row.last_scan_at).toLocaleString() : '—' }}</span>
          </template>
          <template #status-data="{ row }">
            <Badge :color="STATUS_COLORS[row.status] ?? 'gray'" size="xs">{{ row.status }}</Badge>
          </template>
        </DataTable>
      </Card>
    </div>

    <Dialog v-model="showAcceptRisk" title="Accept risk">
      <template #body>
        <FormField label="Reason" required help="Recorded on the audit log">
          <Textarea v-model="acceptRiskReason" rows="3" placeholder="Compensating control in place; no exposed network path." />
        </FormField>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showAcceptRisk = false">Cancel</Button>
        <Button :loading="acceptingRisk" :disabled="!acceptRiskReason.trim()" @click="submitAcceptRisk">Accept risk</Button>
      </template>
    </Dialog>
  </div>
</template>
