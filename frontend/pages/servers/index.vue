<script setup lang="ts">
import { RefreshCw, Search, Pencil, Plus } from 'lucide-vue-next'

const {
  servers, total, loading, filters, fetchServers, statusColor, toggleMaintenance,
  categories, projects, fetchCategories, fetchProjects, createCategory, createProject, assignServer,
} = useServers()
const toast = useToast()

// Client-only fetch (matches pages/jobs/index.vue): the last_seen_at column
// below renders new Date(...).toLocaleString(), which formats differently
// server vs. client (locale/timezone) — SSR-fetching real rows here would
// hydration-mismatch on every row's timestamp. Rendering empty on the
// server and populating after mount avoids that; onMounted only ever runs
// client-side, so there is nothing to await during SSR.
onMounted(() => {
  fetchServers()
  fetchCategories()
  fetchProjects()
})

const columns = [
  { key: 'hostname', label: 'Hostname' },
  { key: 'ip_address', label: 'IP' },
  { key: 'os_name', label: 'OS' },
  { key: 'status', label: 'Status' },
  { key: 'category', label: 'Category' },
  { key: 'project', label: 'Project' },
  { key: 'last_seen_at', label: 'Last Seen' },
  { key: 'actions', label: '' },
]

const statusOptions = ['', 'ACTIVE', 'INACTIVE', 'UNHEALTHY', 'MAINTENANCE', 'PENDING', 'REGISTERED']

const categoryFilter = ref('')
const projectFilter = ref('')

const categoryOptions = computed(() => [
  { label: 'Category', value: '' },
  ...categories.value.map((c) => ({ label: c.name, value: c.id })),
])
const projectOptions = computed(() => [
  { label: 'Project', value: '' },
  ...projects.value.map((p) => ({ label: p.name, value: p.id })),
])

const filteredServers = computed(() => servers.value.filter((s) => {
  if (categoryFilter.value && s.category_id !== categoryFilter.value) return false
  if (projectFilter.value && s.project_id !== projectFilter.value) return false
  return true
}))

const editingServer = ref<(typeof servers.value)[0] | null>(null)
const savingMaintenance = ref(false)
const selectedIds = ref<(string | number)[]>([])

const assignOptions = computed(() => [{ label: 'None', value: '' }, ...categories.value.map((c) => ({ label: c.name, value: c.id }))])
const projectAssignOptions = computed(() => [{ label: 'None', value: '' }, ...projects.value.map((p) => ({ label: p.name, value: p.id }))])

const savingRowId = ref<string | null>(null)

async function updateCategory(row: (typeof servers.value)[0], value: string) {
  savingRowId.value = String(row.id)
  try {
    await assignServer(String(row.id), value || null, row.project_id)
  } catch {
    toast.add({ title: 'Failed to update category', color: 'red' })
  } finally {
    savingRowId.value = null
  }
}

async function updateProject(row: (typeof servers.value)[0], value: string) {
  savingRowId.value = String(row.id)
  try {
    await assignServer(String(row.id), row.category_id, value || null)
  } catch {
    toast.add({ title: 'Failed to update project', color: 'red' })
  } finally {
    savingRowId.value = null
  }
}

async function saveMaintenance() {
  if (!editingServer.value) return
  savingMaintenance.value = true
  try {
    await toggleMaintenance(String(editingServer.value.id))
    toast.add({ title: 'Server updated', color: 'green' })
    editingServer.value = null
  } catch {
    toast.add({ title: 'Failed to update server', color: 'red' })
  } finally {
    savingMaintenance.value = false
  }
}

const showNewEntity = ref(false)
const newEntityType = ref<'category' | 'project'>('category')
const newEntityName = ref('')
const newEntityCategoryId = ref('')
const savingEntity = ref(false)

const entityTypeOptions = [
  { label: 'Category', value: 'category' },
  { label: 'Project', value: 'project' },
]

async function saveNewEntity() {
  if (!newEntityName.value.trim()) return
  savingEntity.value = true
  try {
    if (newEntityType.value === 'category') {
      await createCategory(newEntityName.value.trim())
      toast.add({ title: 'Category created', color: 'green' })
    } else {
      await createProject(newEntityName.value.trim(), newEntityCategoryId.value || null)
      toast.add({ title: 'Project created', color: 'green' })
    }
    newEntityName.value = ''
    newEntityCategoryId.value = ''
    showNewEntity.value = false
  } catch {
    toast.add({ title: `Failed to create ${newEntityType.value}`, color: 'red' })
  } finally {
    savingEntity.value = false
  }
}
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div class="flex flex-wrap items-center gap-3">
        <div class="relative w-56">
          <Search class="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input
            v-model="filters.search"
            placeholder="Search hostname..."
            class="pl-9"
            @keyup.enter="fetchServers()"
          />
        </div>
        <Select
          v-model="filters.status"
          :options="statusOptions"
          placeholder="Status"
          class="w-40"
          @change="fetchServers()"
        />
        <Select v-model="categoryFilter" :options="categoryOptions" class="w-36" />
        <Select v-model="projectFilter" :options="projectOptions" class="w-36" />
        <Button variant="ghost" size="xs" @click="showNewEntity = true">
          <Plus class="size-3.5" /> New
        </Button>
        <Button variant="outline" @click="fetchServers()">
          <RefreshCw class="size-4" />
          Refresh
        </Button>
      </div>
      <Badge v-if="selectedIds.length" color="green">{{ selectedIds.length }} selected</Badge>
      <Badge color="gray">{{ filteredServers.length }} servers</Badge>
    </div>

    <DataTable
      :rows="filteredServers"
      :columns="columns"
      :loading="loading"
      rows-clickable
      selectable
      v-model:selected="selectedIds"
      @row-click="(row) => navigateTo(`/servers/${row.id}`)"
    >
      <template #hostname-data="{ row }">
        <span class="font-mono">{{ row.hostname }}</span>
      </template>
      <template #status-data="{ row }">
        <Badge :color="statusColor(String(row.status))">{{ row.status }}</Badge>
      </template>
      <template #os_name-data="{ row }">
        {{ [row.os_name, row.os_version].filter(Boolean).join(' ') || '—' }}
      </template>
      <template #category-data="{ row }">
        <div class="w-36" @click.stop>
          <Select
            :model-value="row.category_id ?? ''"
            :options="assignOptions"
            :disabled="savingRowId === String(row.id)"
            @update:model-value="updateCategory(row as typeof servers.value[0], $event)"
          />
        </div>
      </template>
      <template #project-data="{ row }">
        <div class="w-36" @click.stop>
          <Select
            :model-value="row.project_id ?? ''"
            :options="projectAssignOptions"
            :disabled="savingRowId === String(row.id)"
            @update:model-value="updateProject(row as typeof servers.value[0], $event)"
          />
        </div>
      </template>
      <template #last_seen_at-data="{ row }">
        <span class="font-mono text-xs">{{ row.last_seen_at ? new Date(String(row.last_seen_at)).toLocaleString() : 'Never' }}</span>
      </template>
      <template #actions-data="{ row }">
        <div class="flex items-center justify-end">
          <Button
            size="xs"
            variant="ghost"
            class="text-muted-foreground"
            @click.stop="editingServer = row as typeof servers.value[0]"
          >
            <Pencil class="size-3.5" />
          </Button>
        </div>
      </template>
    </DataTable>

    <Dialog :model-value="!!editingServer" title="Edit Server" @update:model-value="editingServer = null">
      <template #body>
        <div class="space-y-3">
          <FormField label="Status" help="Toggling flips the server between ACTIVE and MAINTENANCE.">
            <Badge :color="statusColor(String(editingServer?.status))">{{ editingServer?.status }}</Badge>
          </FormField>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="editingServer = null">Cancel</Button>
        <Button :loading="savingMaintenance" @click="saveMaintenance">
          {{ editingServer?.status === 'MAINTENANCE' ? 'Set Active' : 'Set Maintenance' }}
        </Button>
      </template>
    </Dialog>

    <Dialog :model-value="showNewEntity" title="New Category/Project" @update:model-value="showNewEntity = false">
      <template #body>
        <div class="space-y-3">
          <FormField label="Type">
            <Select v-model="newEntityType" :options="entityTypeOptions" />
          </FormField>
          <FormField label="Name">
            <Input v-model="newEntityName" placeholder="e.g. Production" @keyup.enter="saveNewEntity" />
          </FormField>
          <FormField v-if="newEntityType === 'project'" label="Category" help="Optional">
            <Select v-model="newEntityCategoryId" :options="[{ label: 'None', value: '' }, ...categories.map((c) => ({ label: c.name, value: c.id }))]" />
          </FormField>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showNewEntity = false">Cancel</Button>
        <Button :loading="savingEntity" @click="saveNewEntity">Create</Button>
      </template>
    </Dialog>
  </div>
</template>
