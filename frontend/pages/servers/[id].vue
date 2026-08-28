<script setup lang="ts">
import { ACTIVE_STATUSES } from '~/stores/jobs'
import { RefreshCw, CheckCircle2, AlertTriangle, Undo2 } from 'lucide-vue-next'

const route = useRoute()
const store = useServersStore()
const { statusColor } = useServers()
const { format: fmtDateTime } = useDateTime()

await store.fetchServer(route.params.id as string)

const server = computed(() => store.selectedServer)

const { jobs, loading: jobsLoading } = useJobs()
const packagesLoaded = ref(false)
const metricsLoaded = ref(false)

// ── Agent group assignment (agent-policy-modernization plan Phase 4) ───────
const groups = ref<{ id: string; name: string }[]>([])
const groupSelection = ref('')
const groupSaving = ref(false)

onMounted(async () => {
  try {
    const res = await useApi().get<{ items: { id: string; name: string }[] }>('/agent-policies/groups/list')
    groups.value = res?.items ?? []
  } catch {
    // group list is a convenience — the rest of the tab still works without it
  }
})

watch(server, (s) => { groupSelection.value = s?.agent_group_id ?? '' }, { immediate: true })

async function saveGroup() {
  if (!server.value) return
  groupSaving.value = true
  try {
    await store.assignServer(
      String(server.value.id), server.value.category_id, server.value.project_id,
      groupSelection.value || null,
    )
    toast.add({ title: 'Group updated', color: 'green' })
  } catch {
    toast.add({ title: 'Failed to update group', color: 'red' })
  } finally {
    groupSaving.value = false
  }
}

const tabs = [
  { label: 'Overview', slot: 'overview' },
  { label: 'Hardware', slot: 'hardware' },
  { label: 'Packages', slot: 'packages' },
  { label: 'Vulnerabilities', slot: 'vulnerabilities' },
  { label: 'Jobs', slot: 'jobs' },
  { label: 'Policy', slot: 'policy' },
  { label: 'Users', slot: 'users' },
  { label: 'Logs', slot: 'logs' },
  { label: 'Settings', slot: 'settings' },
]

const diskColumns = [
  { key: 'mount_point', label: 'Mount' },
  { key: 'filesystem', label: 'Filesystem' },
  { key: 'usage', label: 'Used / Total' },
  { key: 'percent', label: '%' },
]

const networkColumns = [
  { key: 'name', label: 'Interface' },
  { key: 'ip_addresses', label: 'IP' },
  { key: 'mac_address', label: 'MAC' },
  { key: 'is_up', label: 'Status' },
]

const blockDeviceColumns = [
  { key: 'name', label: 'Name' },
  { key: 'type', label: 'Type' },
  { key: 'size', label: 'Size' },
  { key: 'mount_point', label: 'Mount' },
]

const listeningPortColumns = [
  { key: 'protocol', label: 'Proto' },
  { key: 'local_address', label: 'Address' },
  { key: 'local_port', label: 'Port' },
  { key: 'process_name', label: 'Process' },
]

function diskPercent(d: { used_size: number; total_size: number }): number {
  return d.total_size > 0 ? Math.round((d.used_size / d.total_size) * 100) : 0
}

const vulnerabilitiesLoaded = ref(false)
const maintenanceToggling = ref(false)

// Default open-only (matches the badge count on the dashboard and the
// /vulnerabilities/summary KPI) — RESOLVED findings shouldn't dominate the
// tab. "All" is the escape hatch for someone who actually wants history.
const vulnFilter = ref<'open' | 'all'>('open')
function onVulnFilterChange() {
  store.fetchVulnerabilities(route.params.id as string, vulnFilter.value === 'all')
}

function onTabChange(index: number) {
  if (index === 2 && !packagesLoaded.value) {
    store.fetchPackages(route.params.id as string)
    packagesLoaded.value = true
  }
  if (index === 3 && !vulnerabilitiesLoaded.value) {
    store.fetchVulnerabilities(route.params.id as string, vulnFilter.value === 'all')
    vulnerabilitiesLoaded.value = true
  }
  if (index === 4) {
    useJobsStore().fetchJobs(route.params.id as string)
  }
  if (index === 5 && !policyLoaded.value) {
    loadPolicyState()
    policyLoaded.value = true
  }
}

// ── Desired-state policy (agent-policy-modernization plan, Faza 4) ────────────
interface PolicyStateInfo {
  desired: { policy: string; policy_id?: string; version: number; hash: string } | null
  actual: { policy: string; version: number; hash: string } | null
  in_sync: boolean
  status: string
  last_error: string | null
  versions?: { version: number; hash: string }[]
}

const policyLoaded = ref(false)
const policyState = ref<PolicyStateInfo | null>(null)
const policyLoading = ref(false)
const rollbackTo = ref<number | null>(null)
const policyBusy = ref(false)
const policyMsg = ref('')

async function loadPolicyState() {
  policyLoading.value = true
  policyMsg.value = ''
  try {
    const api = useApi()
    policyState.value = await api.get<PolicyStateInfo>(`/agent-policies/agents/${route.params.id}/policy`)
  } catch (e: unknown) {
    policyMsg.value = (e as { data?: { detail?: string } })?.data?.detail ?? 'Failed to load policy state'
  } finally {
    policyLoading.value = false
  }
}

async function syncNow() {
  policyBusy.value = true
  policyMsg.value = ''
  try {
    const api = useApi()
    const res = await api.post<{ notified: boolean; desired_version: number }>(
      `/agent-policies/agents/${route.params.id}/policy/sync-now`,
    )
    policyMsg.value = res?.notified ? `Re-notify sent (desired v${res.desired_version}).` : 'Notify failed'
    setTimeout(() => loadPolicyState(), 2500)
  } catch (e: unknown) {
    policyMsg.value = (e as { data?: { detail?: string } })?.data?.detail ?? 'Sync failed'
  } finally {
    policyBusy.value = false
  }
}

async function doRollback() {
  if (rollbackTo.value == null) return
  policyBusy.value = true
  policyMsg.value = ''
  try {
    const api = useApi()
    const res = await api.post<{ to_version: number; deployment_id: string }>(
      `/agent-policies/agents/${route.params.id}/policy/rollback`,
      { to_version: rollbackTo.value },
    )
    policyMsg.value = `Rollback deployment opened → v${res.to_version}. Applied on next heartbeat.`
    await loadPolicyState()
  } catch (e: unknown) {
    policyMsg.value = (e as { data?: { detail?: string } })?.data?.detail ?? 'Rollback failed'
  } finally {
    policyBusy.value = false
  }
}

onMounted(() => {
  store.fetchMetrics(route.params.id as string)
  metricsLoaded.value = true
})

// CPU/RAM/disk usage on the Overview tab changes every agent heartbeat
// (~60s server-side) but was only ever fetched once on page load — 30s
// matches the /servers/{id}/metrics cache TTL (TTL_AGENT_STATUS), so most
// polls land right as the cached value expires instead of wasting requests.
let metricsPoll: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  metricsPoll = setInterval(() => store.fetchMetrics(route.params.id as string), 30000)
})
onUnmounted(() => clearInterval(metricsPoll))

// Same poll pattern as pages/jobs/index.vue and JobDetail.vue — jobs on
// this server's Jobs tab don't move on their own client-side either, and
// this tab has no manual Refresh button.
const hasActiveJobs = computed(() => jobs.value.some((j) => ACTIVE_STATUSES.includes(j.status)))
let jobsPoll: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  jobsPoll = setInterval(() => {
    if (hasActiveJobs.value) useJobsStore().fetchJobs(route.params.id as string)
  }, 5000)
})
onUnmounted(() => clearInterval(jobsPoll))

async function handleToggleMaintenance() {
  maintenanceToggling.value = true
  try {
    await store.toggleMaintenance(route.params.id as string)
  } finally {
    maintenanceToggling.value = false
  }
}

const jobColumns = [
  { key: 'job_type', label: 'Type' },
  { key: 'status', label: 'Status' },
  { key: 'created_at', label: 'Created' },
  { key: 'completed_at', label: 'Completed' },
]

const selectedJob = ref<(typeof jobs.value)[0] | null>(null)

const packageColumns = [
  { key: 'name', label: 'Name' },
  { key: 'version', label: 'Installed version' },
  { key: 'latest_version', label: 'Available' },
  { key: 'architecture', label: 'Architecture' },
  { key: 'update_status', label: 'Update' },
]

const selectedPackageIds = ref<(string | number)[]>([])
const updatingPackages = ref(false)
const toast = useToast()

async function submitPackageUpdate(names?: string[]) {
  updatingPackages.value = true
  try {
    await useJobsStore().createJob({
      name: names ? `Update packages (${names.length})` : 'Update all packages',
      job_type: 'PACKAGE_UPDATE',
      target_servers: { agent_ids: [route.params.id as string] },
      parameters: names ? { package_names: names } : null,
    })
    await useJobsStore().fetchJobs(route.params.id as string)
    selectedPackageIds.value = []
    toast.add({ title: 'Update job created', color: 'green' })
  } catch (err) {
    const status = (err as { response?: { status?: number }; statusCode?: number })?.response?.status
      ?? (err as { statusCode?: number })?.statusCode
    toast.add(
      status === 409
        ? { title: 'Identical job already queued for this server', color: 'orange' }
        : { title: 'Failed to create update job', color: 'red' },
    )
  } finally {
    updatingPackages.value = false
  }
}

function updateSelectedPackages() {
  const names = store.packages
    .filter((p) => selectedPackageIds.value.includes(p.id))
    .map((p) => p.name)
  submitPackageUpdate(names)
}

const { statusColor: jobStatusColor } = useJobs()

const vulnerabilityColumns = [
  { key: 'cve_id', label: 'CVE' },
  { key: 'package_name', label: 'Package' },
  { key: 'severity', label: 'Severity' },
  { key: 'cvss_score', label: 'CVSS' },
  { key: 'fix_available', label: 'Fix available' },
  { key: 'status', label: 'Status' },
]

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'red',
  HIGH: 'red',
  MEDIUM: 'gray',
  LOW: 'gray',
}

const VULN_STATUS_COLORS: Record<string, string> = {
  OPEN: 'red',
  PATCH_AVAILABLE: 'amber',
  IN_PROGRESS: 'blue',
  MITIGATED: 'gray',
  RESOLVED: 'green',
  ACCEPTED_RISK: 'gray',
}

const VULN_FILTER_OPTIONS = [
  { label: 'Open', value: 'open' },
  { label: 'All', value: 'all' },
]
</script>

<template>
  <div v-if="server">
    <PageHeader :title="server.hostname" :back="{ to: '/servers', label: 'Back to servers' }">
      <template #badges>
        <Badge :color="statusColor(String(server.status))">{{ server.status }}</Badge>
      </template>
    </PageHeader>

    <AppTabs :items="tabs" @change="onTabChange">
      <template #overview>
        <Card class="mt-4">
          <dl class="grid grid-cols-2 gap-x-8 gap-y-4">
            <div class="col-span-2 grid grid-cols-4 gap-x-8 gap-y-4 pb-4 mb-1 border-b border-border">
              <ServerMetricsCards :metrics="store.metrics" :loading="store.metricsLoading" />
            </div>
            <div>
              <dt class="text-xs text-muted-foreground">OS</dt>
              <dd class="font-medium text-[13px] mt-0.5">{{ [server.os_name, server.os_version].filter(Boolean).join(' ') || '—' }}</dd>
            </div>
            <div>
              <dt class="text-xs text-muted-foreground">Kernel</dt>
              <dd class="font-medium text-[13px] mt-0.5">{{ server.kernel_version || '—' }}</dd>
            </div>
            <div>
              <dt class="text-xs text-muted-foreground">IP Address</dt>
              <dd class="font-medium text-[13px] mt-0.5">{{ server.ip_address || '—' }}</dd>
            </div>
            <div>
              <dt class="text-xs text-muted-foreground">FQDN</dt>
              <dd class="font-medium text-[13px] mt-0.5">{{ server.fqdn || '—' }}</dd>
            </div>
            <div>
              <dt class="text-xs text-muted-foreground">Agent Version</dt>
              <dd class="font-medium text-[13px] mt-0.5">{{ server.agent_version || '—' }}</dd>
            </div>
            <div>
              <dt class="text-xs text-muted-foreground">Last Seen</dt>
              <dd class="font-medium text-[13px] mt-0.5">{{ server.last_seen_at ? fmtDateTime(String(server.last_seen_at)) : 'Never' }}</dd>
            </div>
            <div v-if="Object.keys(server.tags as object).length">
              <dt class="text-xs text-muted-foreground">Tags</dt>
              <dd class="flex flex-wrap gap-1 mt-1">
                <Badge
                  v-for="(val, key) in server.tags as Record<string, string>"
                  :key="key"
                  color="gray"
                  size="xs"
                >{{ key }}={{ val }}</Badge>
              </dd>
            </div>
          </dl>
        </Card>
      </template>

      <template #hardware>
        <div class="mt-4 space-y-6">
          <div>
            <h3 class="text-sm font-medium mb-2">Disks</h3>
            <DataTable :rows="server.disks ?? []" :columns="diskColumns" sortable empty-title="No disks reported">
              <template #usage-data="{ row }">
                {{ formatBytes(row.used_size) }} / {{ formatBytes(row.total_size) }}
              </template>
              <template #percent-data="{ row }">
                <span class="tabular-nums" :style="{ color: diskPercent(row) > 90 ? 'var(--destructive)' : 'inherit' }">
                  {{ diskPercent(row) }}%
                </span>
              </template>
            </DataTable>
          </div>

          <div>
            <h3 class="text-sm font-medium mb-2">Network Interfaces</h3>
            <DataTable :rows="server.network_interfaces ?? []" :columns="networkColumns" sortable empty-title="No interfaces reported">
              <template #ip_addresses-data="{ row }">
                {{ row.ip_addresses?.join(', ') || '—' }}
              </template>
              <template #is_up-data="{ row }">
                <Badge :color="row.is_up ? 'green' : 'gray'" size="xs">{{ row.is_up ? 'up' : 'down' }}</Badge>
              </template>
            </DataTable>
          </div>

          <div>
            <h3 class="text-sm font-medium mb-2">Block Devices</h3>
            <DataTable :rows="server.block_devices ?? []" :columns="blockDeviceColumns" sortable empty-title="No block devices reported">
              <template #name-data="{ row }">
                <span :class="row.parent_name ? 'pl-4' : ''">{{ row.parent_name ? '└─ ' : '' }}{{ row.name }}</span>
              </template>
              <template #size-data="{ row }">{{ formatBytes(row.size) }}</template>
            </DataTable>
          </div>

          <div>
            <h3 class="text-sm font-medium mb-2">Listening Ports</h3>
            <DataTable :rows="server.listening_ports ?? []" :columns="listeningPortColumns" sortable empty-title="No listening ports reported">
              <template #protocol-data="{ row }">
                <Badge color="gray" size="xs">{{ row.protocol }}</Badge>
              </template>
              <template #process_name-data="{ row }">
                {{ row.process_name || '—' }}
              </template>
            </DataTable>
          </div>
        </div>
      </template>

      <template #packages>
        <div class="mt-4">
          <div class="flex items-center gap-2 mb-3">
            <Badge v-if="selectedPackageIds.length" color="green">{{ selectedPackageIds.length }} selected</Badge>
            <Button size="xs" :disabled="!selectedPackageIds.length || updatingPackages" @click="updateSelectedPackages">
              Update selected
            </Button>
            <Button variant="outline" size="xs" :disabled="updatingPackages" @click="submitPackageUpdate()">
              Update all
            </Button>
          </div>
          <DataTable
            :rows="store.packages"
            :columns="packageColumns"
            :loading="store.packagesLoading"
            sortable
            :page-size="25"
            empty-title="No packages reported yet"
            empty-description="This appears after the first heartbeat with inventory from the agent."
            selectable
            v-model:selected="selectedPackageIds"
          >
            <template #latest_version-data="{ row }">
              <span v-if="row.latest_version" class="text-[13px] font-medium">{{ row.latest_version }}</span>
              <span v-else class="text-[13px] text-muted-foreground">{{ row.version }}</span>
            </template>
            <template #update_status-data="{ row }">
              <Badge v-if="row.is_security_update_available" color="red" size="xs">security update</Badge>
              <Badge v-else-if="row.is_update_available" color="gray" size="xs">update</Badge>
              <span v-else class="text-muted-foreground text-xs">up to date</span>
            </template>
          </DataTable>
        </div>
      </template>

      <template #vulnerabilities>
        <div class="mt-4">
          <div class="mb-3 flex items-center justify-end gap-2">
            <span class="text-xs text-muted-foreground">Status</span>
            <Select v-model="vulnFilter" :options="VULN_FILTER_OPTIONS" class="w-28" @update:model-value="onVulnFilterChange" />
          </div>
          <DataTable
            :rows="store.vulnerabilities"
            :columns="vulnerabilityColumns"
            :loading="store.vulnerabilitiesLoading"
            sortable
            :page-size="25"
            empty-title="No vulnerabilities reported"
            :empty-description="vulnFilter === 'open' ? 'Switch to “All” to see resolved findings.' : 'This appears after CVE scan processing for this server\'s packages.'"
          >
            <template #severity-data="{ row }">
              <Badge v-if="row.severity" :color="SEVERITY_COLORS[row.severity] ?? 'gray'" size="xs">{{ row.severity }}</Badge>
              <span v-else class="text-muted-foreground text-xs">—</span>
            </template>
            <template #cvss_score-data="{ row }">
              <span class="tabular-nums">{{ row.cvss_score ?? '—' }}</span>
            </template>
            <template #fix_available-data="{ row }">
              <Badge v-if="row.fix_available" color="green" size="xs">yes</Badge>
              <span v-else class="text-muted-foreground text-xs">no</span>
            </template>
            <template #status-data="{ row }">
              <Badge :color="VULN_STATUS_COLORS[row.status] ?? 'gray'" size="xs">{{ row.status }}</Badge>
            </template>
          </DataTable>
        </div>
      </template>

      <template #jobs>
        <div class="mt-4">
          <DataTable
            :rows="jobs"
            :columns="jobColumns"
            :loading="jobsLoading"
            sortable
            :page-size="25"
            empty-title="No jobs for this server yet"
            rows-clickable
            @row-click="selectedJob = $event"
          >
            <template #status-data="{ row }">
              <Badge :color="jobStatusColor(String(row.status))" size="xs">{{ row.status }}</Badge>
            </template>
            <template #created_at-data="{ row }">
              {{ fmtDateTime(String(row.created_at)) }}
            </template>
            <template #completed_at-data="{ row }">
              {{ row.completed_at ? fmtDateTime(String(row.completed_at)) : '—' }}
            </template>
          </DataTable>
          <p class="text-xs text-muted-foreground mt-2">Click a job for full output (stdout/stderr).</p>
        </div>
      </template>

      <template #policy>
        <div class="mt-4 space-y-4">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-semibold">Desired-state policy</h3>
            <div class="flex items-center gap-2">
              <Button variant="outline" size="xs" :loading="policyLoading" @click="loadPolicyState">
                <RefreshCw class="size-3.5" />
                Refresh
              </Button>
              <Button
                v-if="policyState?.desired && !policyState.in_sync"
                size="xs"
                :loading="policyBusy"
                @click="syncNow"
              >
                Sync Now
              </Button>
            </div>
          </div>

          <div v-if="groups.length" class="flex items-end gap-2">
            <FormField label="Group" help="GROUP-scope policy deploys target agents by this assignment.">
              <Select
                v-model="groupSelection"
                :options="[{ label: 'No group', value: '' }, ...groups.map((g) => ({ label: g.name, value: g.id }))]"
                class="w-48"
              />
            </FormField>
            <Button variant="outline" size="sm" :loading="groupSaving" :disabled="groupSelection === (server?.agent_group_id ?? '')" @click="saveGroup">
              Save
            </Button>
          </div>

          <p v-if="policyLoading && !policyState" class="text-sm text-muted-foreground">Loading…</p>

          <template v-else-if="policyState">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Card>
                <template #header><p class="label-caps">Desired</p></template>
                <div v-if="policyState.desired" class="text-sm space-y-1">
                  <p class="font-medium">{{ policyState.desired.policy }}</p>
                  <p class="font-mono text-xs text-muted-foreground">
                    v{{ policyState.desired.version }} · {{ policyState.desired.hash.slice(0, 16) }}…
                  </p>
                </div>
                <p v-else class="text-sm text-muted-foreground">No policy assigned.</p>
              </Card>
              <Card>
                <template #header><p class="label-caps">Actual (applied on agent)</p></template>
                <div v-if="policyState.actual" class="text-sm space-y-1">
                  <p class="font-medium">{{ policyState.actual.policy }}</p>
                  <p class="font-mono text-xs text-muted-foreground">
                    v{{ policyState.actual.version }} · {{ policyState.actual.hash.slice(0, 16) }}…
                  </p>
                </div>
                <p v-else class="text-sm text-muted-foreground">Nothing applied yet — waiting for first reconcile.</p>
              </Card>
            </div>

            <div class="flex items-center gap-2 text-sm">
              <template v-if="policyState.in_sync">
                <CheckCircle2 class="size-4 text-success" />
                <span class="text-success font-medium">In sync</span>
              </template>
              <template v-else-if="policyState.desired">
                <AlertTriangle class="size-4 text-amber-500" />
                <span class="text-amber-500 font-medium">Out of sync</span>
                <span class="text-xs text-muted-foreground">
                  desired v{{ policyState.desired.version }} / actual
                  {{ policyState.actual ? `v${policyState.actual.version}` : 'none' }}
                </span>
              </template>
              <Badge v-if="policyState.status !== 'idle'" color="gray" size="xs">{{ policyState.status }}</Badge>
            </div>

            <p v-if="policyState.last_error" class="text-xs text-destructive">{{ policyState.last_error }}</p>
            <p v-if="policyMsg" class="text-xs text-muted-foreground">{{ policyMsg }}</p>

            <div v-if="policyState.desired && (policyState.versions?.length ?? 0) > 1" class="flex items-end gap-2">
              <FormField label="Rollback to version">
                <Select
                  :model-value="rollbackTo != null ? String(rollbackTo) : undefined"
                  :options="(policyState.versions ?? []).map((v) => ({ label: `v${v.version}`, value: String(v.version) }))"
                  placeholder="Select version..."
                  class="w-40"
                  @update:model-value="rollbackTo = $event != null ? Number($event) : null"
                />
              </FormField>
              <Button variant="outline" size="sm" :disabled="rollbackTo == null || policyBusy" @click="doRollback">
                <Undo2 class="size-3.5" />
                Rollback
              </Button>
            </div>
          </template>
        </div>
      </template>

      <template #users>
        <Card class="mt-4">
          <template #header>System Users</template>
          <ul v-if="server.system_users?.length" class="space-y-1">
            <li v-for="u in server.system_users" :key="u" class="text-[13px] font-mono">{{ u }}</li>
          </ul>
          <p v-else class="text-xs text-muted-foreground">
            No users reported yet. This appears after the first heartbeat from the agent.
          </p>
        </Card>
      </template>

      <template #logs>
        <Card class="mt-4">
          <template #header>Agent Logs</template>
          <div v-if="server.recent_logs" class="space-y-4">
            <div class="flex gap-4">
              <div class="flex items-center gap-2">
                <Badge color="green">{{ server.recent_logs.connections }}</Badge>
                <span class="text-xs text-muted-foreground">Connections</span>
              </div>
              <div class="flex items-center gap-2">
                <Badge color="gray">{{ server.recent_logs.informative }}</Badge>
                <span class="text-xs text-muted-foreground">Informative</span>
              </div>
              <div class="flex items-center gap-2">
                <Badge color="red">{{ server.recent_logs.critical }}</Badge>
                <span class="text-xs text-muted-foreground">Critical</span>
              </div>
            </div>
            <pre
              v-if="server.recent_logs.lines.length"
              class="text-xs font-mono bg-muted rounded-md p-3 max-h-96 overflow-y-auto whitespace-pre-wrap"
            >{{ server.recent_logs.lines.join('\n') }}</pre>
          </div>
          <p v-else class="text-xs text-muted-foreground">
            No logs reported yet. This appears after the first heartbeat from the agent.
          </p>
        </Card>
      </template>

      <template #settings>
        <Card class="mt-4">
          <template #header>Maintenance Mode</template>
          <div class="flex items-center justify-between">
            <div>
              <p class="text-[13px] font-medium">
                Current status: <Badge :color="statusColor(String(server.status))">{{ server.status }}</Badge>
              </p>
              <p class="text-xs text-muted-foreground mt-1">
                Maintenance mode suspends alerts and marks the server as intentionally unavailable.
              </p>
            </div>
            <Button
              size="sm"
              :variant="server.status === 'MAINTENANCE' ? 'default' : 'outline'"
              :disabled="maintenanceToggling"
              @click="handleToggleMaintenance"
            >
              {{ server.status === 'MAINTENANCE' ? 'Disable maintenance' : 'Enable maintenance' }}
            </Button>
          </div>
        </Card>
      </template>
    </AppTabs>
  </div>

  <div v-else-if="store.selectedServerError" class="rounded-md border border-destructive p-4 text-sm text-destructive">
    Failed to load server: {{ store.selectedServerError }}
  </div>

  <div v-else class="flex items-center justify-center h-64 text-muted-foreground">
    Server not found.
  </div>

  <JobDetail :job="selectedJob" @close="selectedJob = null" />
</template>
