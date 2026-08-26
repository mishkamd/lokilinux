<script setup lang="ts">
import { Save, Plus, Trash2, FileText } from 'lucide-vue-next'
import type { AnsibleRole } from '~/stores/ansible_roles'

const route = useRoute()
const store = useAnsibleRolesStore()
const { canEdit } = useCurrentUser()
const toast = useToast()

const isNew = computed(() => route.params.id === 'new')
const role = ref<AnsibleRole | null>(null)
const name = ref('')
const description = ref('')
const files = ref<Record<string, string>>({ 'tasks/main.yml': '---\n# tasks for this role\n' })
const activePath = ref('tasks/main.yml')
const saving = ref(false)

if (!isNew.value) {
  role.value = await store.fetchRole(String(route.params.id))
  name.value = role.value.name
  description.value = role.value.description ?? ''
  files.value = { ...role.value.files }
  activePath.value = Object.keys(files.value)[0] ?? ''
}

const paths = computed(() => Object.keys(files.value).sort())

// v-model bridge for the active file so CodeMirror edits land in files map
const activeContent = computed({
  get: () => files.value[activePath.value] ?? '',
  set: (v: string) => { if (activePath.value) files.value[activePath.value] = v },
})

const newFilePath = ref('')

function addFile() {
  const p = newFilePath.value.trim().replace(/^\/+/, '')
  if (!p) return
  if (p.split('/').includes('..')) {
    toast.add({ title: 'Invalid path', color: 'red' })
    return
  }
  if (!(p in files.value)) files.value[p] = ''
  activePath.value = p
  newFilePath.value = ''
}

function removeFile(path: string) {
  const { [path]: _, ...rest } = files.value
  files.value = rest
  if (activePath.value === path) activePath.value = paths.value[0] ?? ''
}

async function save() {
  if (!name.value.trim()) {
    toast.add({ title: 'Name is required', color: 'red' })
    return
  }
  if (!paths.value.length) {
    toast.add({ title: 'Role needs at least one file', color: 'red' })
    return
  }
  saving.value = true
  try {
    const payload = { name: name.value, description: description.value, files: files.value }
    if (isNew.value) {
      const created = await store.createRole(payload)
      toast.add({ title: 'Role created', color: 'green' })
      await navigateTo(`/automation/ansible/roles/${created.id}`)
    } else {
      role.value = await store.updateRole(String(route.params.id), payload)
      toast.add({ title: `Role saved (v${role.value.version})`, color: 'green' })
    }
  } catch {
    toast.add({ title: 'Failed to save role', color: 'red' })
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="max-w-6xl">
    <PageHeader
      :title="isNew ? 'New Role' : name"
      :back="{ to: '/automation/ansible/roles', label: 'Back to roles' }"
    >
      <template v-if="role" #badges>
        <Badge color="gray" size="xs">v{{ role.version }}</Badge>
      </template>
      <template #actions>
        <Button v-if="canEdit" :loading="saving" @click="save">
          <Save class="size-4" />
          Save
        </Button>
      </template>
    </PageHeader>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
      <FormField label="Name" required>
        <Input v-model="name" placeholder="Role name (e.g. autoInstall)..." :disabled="!canEdit" />
      </FormField>
      <FormField label="Description">
        <Input v-model="description" placeholder="What this role does..." :disabled="!canEdit" />
      </FormField>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-[240px_1fr] gap-4">
      <!-- File tree -->
      <div class="rounded-lg border border-border bg-card p-2 space-y-1 self-start">
        <p class="label-caps px-2 py-1">Files</p>
        <button
          v-for="p in paths"
          :key="p"
          type="button"
          class="w-full flex items-center gap-2 px-2 py-1.5 rounded text-left text-sm transition-colors"
          :class="p === activePath ? 'bg-muted text-foreground' : 'text-muted-foreground hover:bg-muted/50'"
          @click="activePath = p"
        >
          <FileText class="size-3.5 shrink-0" />
          <span class="truncate flex-1 font-mono text-xs">{{ p }}</span>
          <Trash2
            v-if="canEdit && paths.length > 1"
            class="size-3 shrink-0 opacity-50 hover:opacity-100 hover:text-destructive"
            @click.stop="removeFile(p)"
          />
        </button>
        <div v-if="canEdit" class="flex items-center gap-1 pt-1">
          <Input
            v-model="newFilePath"
            placeholder="defaults/main.yml"
            class="text-xs font-mono h-7"
            @keyup.enter="addFile"
          />
          <Button size="xs" variant="ghost" aria-label="Add file" @click="addFile">
            <Plus class="size-3.5" />
          </Button>
        </div>
      </div>

      <!-- Editor — min-w-0 lets the grid column shrink so long lines scroll
           inside the editor instead of stretching the page past the viewport. -->
      <div class="min-w-0">
        <p class="text-xs text-muted-foreground font-mono mb-1.5 truncate">{{ activePath || '—' }}</p>
        <PlaybookEditor v-if="activePath" :key="activePath" v-model="activeContent" tall />
      </div>
    </div>
  </div>
</template>
