<script setup lang="ts">
import { RefreshCw, Plus, Pencil, Trash2, Upload } from 'lucide-vue-next'
import type { AnsibleRole } from '~/stores/ansible_roles'

const store = useAnsibleRolesStore()
const { canEdit } = useCurrentUser()
const toast = useToast()

// ── Upload role directory ─────────────────────────────────────────────────
// Uses <input webkitdirectory> — user picks the role folder; the folder name
// becomes the role name and every file under it becomes files[<relpath>].
// Zero deps: browser File API only. Skips VCS/CI cruft and files too large
// to be a sane role source.
const dirInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)

const SKIP_SEGMENTS = new Set(['.git', '.github', '.svn', '__pycache__', 'node_modules'])
const SKIP_NAMES = new Set(['.gitignore', '.travis.yml', '.DS_Store'])
const MAX_FILE_BYTES = 512 * 1024

async function onDirSelected(e: Event) {
  const fileList = (e.target as HTMLInputElement).files
  if (!fileList?.length) return
  uploading.value = true
  try {
    const files: Record<string, string> = {}
    let roleName = ''
    let skipped = 0

    for (const file of Array.from(fileList)) {
      // webkitRelativePath = "roleFolder/tasks/main.yml"
      const rel = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
      const parts = rel.split('/')
      if (!roleName) roleName = parts[0] || 'role'
      const inner = parts.slice(1) // path inside the role folder

      if (!inner.length) continue
      if (inner.some((seg) => SKIP_SEGMENTS.has(seg)) || SKIP_NAMES.has(inner[inner.length - 1]!)) {
        skipped++
        continue
      }
      if (file.size > MAX_FILE_BYTES) {
        skipped++
        continue
      }
      files[inner.join('/')] = await file.text()
    }

    if (!Object.keys(files).length) {
      toast.add({ title: 'No usable files found in folder', color: 'red' })
      return
    }
    const created = await store.createRole({ name: roleName, description: `Uploaded role folder`, files })
    toast.add({
      title: `Role "${roleName}" uploaded`,
      description: `${Object.keys(files).length} files${skipped ? `, ${skipped} skipped` : ''}`,
      color: 'green',
    })
    navigateTo(`/automation/ansible/roles/${created.id}`)
  } catch (err) {
    toast.add({ title: 'Upload failed', description: err instanceof Error ? err.message : undefined, color: 'red' })
  } finally {
    uploading.value = false
    if (dirInput.value) dirInput.value.value = ''
  }
}

const columns = [
  { key: 'name', label: 'Name' },
  { key: 'files', label: 'Files' },
  { key: 'version', label: 'Version' },
  { key: 'is_enabled', label: 'Status' },
  { key: 'updated_at', label: 'Updated' },
  { key: 'actions', label: '' },
]

await store.fetchRoles()

function openCreate() {
  navigateTo('/automation/ansible/roles/new')
}

function openEdit(role: AnsibleRole) {
  navigateTo(`/automation/ansible/roles/${role.id}`)
}

const deletingRole = ref<AnsibleRole | null>(null)
const deleting = ref(false)

async function confirmDelete() {
  if (!deletingRole.value) return
  deleting.value = true
  try {
    await store.deleteRole(deletingRole.value.id)
    toast.add({ title: 'Role deleted', color: 'green' })
    deletingRole.value = null
  } catch {
    toast.add({ title: 'Failed to delete role', color: 'red' })
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-4">
      <div class="flex items-center gap-3">
        <Button variant="outline" @click="store.fetchRoles()">
          <RefreshCw class="size-4" />
          Refresh
        </Button>
        <Badge color="gray">{{ store.roles.length }} roles</Badge>
      </div>
      <div v-if="canEdit" class="flex items-center gap-2">
        <input
          ref="dirInput"
          type="file"
          webkitdirectory
          directory
          multiple
          class="hidden"
          @change="onDirSelected"
        />
        <Button variant="outline" :loading="uploading" @click="dirInput?.click()">
          <Upload class="size-4" />
          Upload Role
        </Button>
        <Button @click="openCreate()">
          <Plus class="size-4" />
          New Role
        </Button>
      </div>
    </div>

    <Alert
      color="blue"
      class="mb-4"
      title="Ansible Roles"
      description="Reusable roles (tasks, defaults, templates, handlers...). Attach roles to a playbook in the playbook editor — at run time they are shipped alongside the playbook and resolved from ./roles/ automatically."
    />

    <DataTable :rows="store.roles" :columns="columns" :loading="store.loading">
      <template #files-data="{ row }">
        <Badge color="gray" size="xs">{{ Object.keys((row as AnsibleRole).files).length }} files</Badge>
      </template>
      <template #is_enabled-data="{ row }">
        <Badge :color="(row as AnsibleRole).is_enabled ? 'green' : 'gray'" size="xs">
          {{ (row as AnsibleRole).is_enabled ? 'enabled' : 'disabled' }}
        </Badge>
      </template>
      <template #updated_at-data="{ row }">
        <span class="font-mono text-xs">{{ new Date(String((row as AnsibleRole).updated_at)).toLocaleString() }}</span>
      </template>
      <template #actions-data="{ row }">
        <div class="flex items-center justify-end gap-1">
          <Button v-if="canEdit" size="xs" variant="ghost" class="text-muted-foreground" @click="openEdit(row as AnsibleRole)">
            <Pencil class="size-3.5" />
          </Button>
          <Button v-if="canEdit" size="xs" variant="ghost" class="text-muted-foreground" @click="deletingRole = row as AnsibleRole">
            <Trash2 class="size-3.5" />
          </Button>
        </div>
      </template>
    </DataTable>

    <Dialog :model-value="!!deletingRole" title="Delete Role" @update:model-value="deletingRole = null">
      <template #body>
        <p class="text-sm text-muted-foreground">
          Delete role <strong class="text-foreground">{{ deletingRole?.name }}</strong>?
          Playbooks referencing it will run without it.
        </p>
      </template>
      <template #footer>
        <Button variant="ghost" @click="deletingRole = null">Cancel</Button>
        <Button variant="destructive" :loading="deleting" @click="confirmDelete">Delete</Button>
      </template>
    </Dialog>
  </div>
</template>
