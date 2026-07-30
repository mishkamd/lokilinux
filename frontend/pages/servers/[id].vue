<script setup lang="ts">
import { ArrowLeft } from 'lucide-vue-next'

const route = useRoute()
const store = useServersStore()
const { statusColor } = useServers()

await store.fetchServer(route.params.id as string)

const server = computed(() => store.selectedServer)

const { jobs, loading: jobsLoading } = useJobs()
const jobsLoaded = ref(false)
const packagesLoaded = ref(false)
const metricsLoaded = ref(false)

const tabs = [
  { label: 'Overview', slot: 'overview' },
  { label: 'Hardware', slot: 'hardware' },
  { label: 'Packages', slot: 'packages' },
  { label: 'Vulnerabilities', slot: 'vulnerabilities' },
  { label: 'Jobs', slot: 'jobs' },
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

function onTabChange(index: number) {
  if (index === 2 && !packagesLoaded.value) {
    store.fetchPackages(route.params.id as string)
    packagesLoaded.value = true
  }
  if (index === 3 && !vulnerabilitiesLoaded.value) {
    store.fetchVulnerabilities(route.params.id as string)
    vulnerabilitiesLoaded.value = true
  }
  if (index === 4 && !jobsLoaded.value) {
    useJobsStore().fetchJobs(route.params.id as string)
    jobsLoaded.value = true
  }
}

onMounted(() => {
  store.fetchMetrics(route.params.id as string)
  metricsLoaded.value = true
})

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

const packageColumns = [
  { key: 'name', label: 'Nume' },
  { key: 'version', label: 'Versiune' },
  { key: 'architecture', label: 'Arhitectură' },
  { key: 'update_status', label: 'Update' },
]

const selectedPackageIds = ref<(string | number)[]>([])
const updatingPackages = ref(false)
const toast = useToast()

async function submitPackageUpdate(names?: string[]) {
  updatingPackages.value = true
  try {
    await useJobsStore().createJob({
      name: names ? `Update pachete (${names.length})` : 'Update all packages',
      job_type: 'PACKAGE_UPDATE',
      target_servers: { agent_ids: [route.params.id as string] },
      priority: 50,
      parameters: names ? { package_names: names } : null,
    })
    selectedPackageIds.value = []
    toast.add({ title: 'Job de update creat', color: 'green' })
  } catch (err) {
    const status = (err as { response?: { status?: number }; statusCode?: number })?.response?.status
      ?? (err as { statusCode?: number })?.statusCode
    toast.add(
      status === 409
        ? { title: 'Există deja un job identic în coadă pentru acest server', color: 'orange' }
        : { title: 'Nu s-a putut crea job-ul de update', color: 'red' },
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
  { key: 'package_name', label: 'Pachet' },
  { key: 'severity', label: 'Severitate' },
  { key: 'cvss_score', label: 'CVSS' },
  { key: 'fix_available', label: 'Fix disponibil' },
]

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'red',
  HIGH: 'red',
  MEDIUM: 'gray',
  LOW: 'gray',
}
</script>

<template>
  <div v-if="server">
    <div class="flex items-center gap-3 mb-4">
      <Button to="/servers" variant="ghost" size="sm">
        <ArrowLeft class="size-4" />
      </Button>
      <h1 class="text-lg font-semibold tracking-tight">{{ server.hostname }}</h1>
      <Badge :color="statusColor(String(server.status))">{{ server.status }}</Badge>
    </div>

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
              <dd class="font-medium text-[13px] mt-0.5">{{ server.last_seen_at ? new Date(String(server.last_seen_at)).toLocaleString() : 'Never' }}</dd>
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
            <DataTable :rows="server.disks ?? []" :columns="diskColumns">
              <template #usage-data="{ row }">
                {{ formatBytes(row.used_size) }} / {{ formatBytes(row.total_size) }}
              </template>
              <template #percent-data="{ row }">
                <span :style="{ color: diskPercent(row) > 90 ? 'var(--destructive)' : 'inherit' }">
                  {{ diskPercent(row) }}%
                </span>
              </template>
            </DataTable>
          </div>

          <div>
            <h3 class="text-sm font-medium mb-2">Network Interfaces</h3>
            <DataTable :rows="server.network_interfaces ?? []" :columns="networkColumns">
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
            <DataTable :rows="server.block_devices ?? []" :columns="blockDeviceColumns">
              <template #name-data="{ row }">
                <span :class="row.parent_name ? 'pl-4' : ''">{{ row.parent_name ? '└─ ' : '' }}{{ row.name }}</span>
              </template>
              <template #size-data="{ row }">{{ formatBytes(row.size) }}</template>
            </DataTable>
          </div>

          <div>
            <h3 class="text-sm font-medium mb-2">Listening Ports</h3>
            <DataTable :rows="server.listening_ports ?? []" :columns="listeningPortColumns">
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
            <Badge v-if="selectedPackageIds.length" color="green">{{ selectedPackageIds.length }} selectate</Badge>
            <Button size="xs" :disabled="!selectedPackageIds.length || updatingPackages" @click="updateSelectedPackages">
              Actualizează selectate
            </Button>
            <Button variant="outline" size="xs" :disabled="updatingPackages" @click="submitPackageUpdate()">
              Actualizează tot
            </Button>
          </div>
          <DataTable
            :rows="store.packages"
            :columns="packageColumns"
            :loading="store.packagesLoading"
            selectable
            v-model:selected="selectedPackageIds"
          >
            <template #update_status-data="{ row }">
              <Badge v-if="row.is_security_update_available" color="red" size="xs">security update</Badge>
              <Badge v-else-if="row.is_update_available" color="gray" size="xs">update</Badge>
              <span v-else class="text-muted-foreground text-xs">up to date</span>
            </template>
          </DataTable>
          <p v-if="!store.packagesLoading && !store.packages.length" class="text-xs text-muted-foreground mt-2">
            Niciun pachet raportat încă — apare după primul heartbeat cu inventar de la agent.
          </p>
        </div>
      </template>

      <template #vulnerabilities>
        <div class="mt-4">
          <DataTable :rows="store.vulnerabilities" :columns="vulnerabilityColumns" :loading="store.vulnerabilitiesLoading">
            <template #severity-data="{ row }">
              <Badge v-if="row.severity" :color="SEVERITY_COLORS[row.severity] ?? 'gray'" size="xs">{{ row.severity }}</Badge>
              <span v-else class="text-muted-foreground text-xs">—</span>
            </template>
            <template #cvss_score-data="{ row }">
              {{ row.cvss_score ?? '—' }}
            </template>
            <template #fix_available-data="{ row }">
              <Badge v-if="row.fix_available" color="green" size="xs">da</Badge>
              <span v-else class="text-muted-foreground text-xs">nu</span>
            </template>
          </DataTable>
          <p v-if="!store.vulnerabilitiesLoading && !store.vulnerabilities.length" class="text-xs text-muted-foreground mt-2">
            Nicio vulnerabilitate raportată — apare după procesarea scanării CVE pentru pachetele acestui server.
          </p>
        </div>
      </template>

      <template #jobs>
        <div class="mt-4">
          <DataTable :rows="jobs" :columns="jobColumns" :loading="jobsLoading">
            <template #status-data="{ row }">
              <Badge :color="jobStatusColor(String(row.status))" size="xs">{{ row.status }}</Badge>
            </template>
            <template #created_at-data="{ row }">
              {{ new Date(String(row.created_at)).toLocaleString() }}
            </template>
            <template #completed_at-data="{ row }">
              {{ row.completed_at ? new Date(String(row.completed_at)).toLocaleString() : '—' }}
            </template>
          </DataTable>
        </div>
      </template>

      <template #users>
        <Card class="mt-4">
          <template #header>System Users</template>
          <ul v-if="server.system_users?.length" class="space-y-1">
            <li v-for="u in server.system_users" :key="u" class="text-[13px] font-mono">{{ u }}</li>
          </ul>
          <p v-else class="text-xs text-muted-foreground">
            Niciun user raportat încă — apare după primul heartbeat de la agent.
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
                <span class="text-xs text-muted-foreground">Conexiuni</span>
              </div>
              <div class="flex items-center gap-2">
                <Badge color="gray">{{ server.recent_logs.informative }}</Badge>
                <span class="text-xs text-muted-foreground">Informative</span>
              </div>
              <div class="flex items-center gap-2">
                <Badge color="red">{{ server.recent_logs.critical }}</Badge>
                <span class="text-xs text-muted-foreground">Critice</span>
              </div>
            </div>
            <pre
              v-if="server.recent_logs.lines.length"
              class="text-xs font-mono bg-muted rounded-md p-3 max-h-96 overflow-y-auto whitespace-pre-wrap"
            >{{ server.recent_logs.lines.join('\n') }}</pre>
          </div>
          <p v-else class="text-xs text-muted-foreground">
            Niciun log raportat încă — apare după primul heartbeat de la agent.
          </p>
        </Card>
      </template>

      <template #settings>
        <Card class="mt-4">
          <template #header>Maintenance Mode</template>
          <div class="flex items-center justify-between">
            <div>
              <p class="text-[13px] font-medium">
                Status curent: <Badge :color="statusColor(String(server.status))">{{ server.status }}</Badge>
              </p>
              <p class="text-xs text-muted-foreground mt-1">
                Modul mentenanță suspendă alertele și marchează serverul ca fiind indisponibil intenționat.
              </p>
            </div>
            <Button
              size="sm"
              :variant="server.status === 'MAINTENANCE' ? 'default' : 'outline'"
              :disabled="maintenanceToggling"
              @click="handleToggleMaintenance"
            >
              {{ server.status === 'MAINTENANCE' ? 'Dezactivează mentenanța' : 'Activează mentenanța' }}
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
</template>
