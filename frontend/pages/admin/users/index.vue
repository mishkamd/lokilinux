<script setup lang="ts">
import { Plus, Trash2, Pencil } from 'lucide-vue-next'

definePageMeta({ layout: 'default' })

interface User {
  id: string
  name: string | null
  email: string
  role: string
}

const api = useApi()
const toast = useToast()

const { data, refresh, pending } = await useAsyncData('admin-users', () =>
  api.get<{ items: User[]; total: number }>('/admin/users'),
)

const showModal = ref(false)
const form = reactive({ email: '', username: '', password: '', role: 'VIEWER' })
const saving = ref(false)

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function validateForm(): string | null {
  if (!EMAIL_RE.test(form.email)) return 'Enter a valid email address'
  if (form.username.trim().length < 3) return 'Username must be at least 3 characters'
  if (form.password.length < 8) return 'Password must be at least 8 characters'
  return null
}

async function createUser() {
  const err = validateForm()
  if (err) {
    toast.add({ title: 'Invalid input', description: err, color: 'red' })
    return
  }
  saving.value = true
  try {
    await api.post('/admin/users', { ...form })
    toast.add({ title: 'User created', color: 'green' })
    showModal.value = false
    await refresh()
  } catch {
    toast.add({ title: 'Failed to create user', color: 'red' })
  } finally {
    saving.value = false
  }
}

async function setRole(userId: string, role: string) {
  try {
    await api.post(`/admin/users/${userId}/role`, null, { params: { role } })
    toast.add({ title: 'Role updated', color: 'green' })
    await refresh()
  } catch {
    toast.add({ title: 'Failed to update role', color: 'red' })
  }
}

const editingUser = ref<User | null>(null)
const editRole = ref('VIEWER')
const savingRole = ref(false)

function openEdit(user: User) {
  editingUser.value = user
  editRole.value = String(user.role).toUpperCase()
}

async function saveEdit() {
  if (!editingUser.value) return
  savingRole.value = true
  try {
    await setRole(String(editingUser.value.id), editRole.value)
    editingUser.value = null
  } finally {
    savingRole.value = false
  }
}

const deletingUser = ref<User | null>(null)
const deleting = ref(false)

async function confirmDelete() {
  if (!deletingUser.value) return
  deleting.value = true
  try {
    await api.del(`/admin/users/${deletingUser.value.id}`)
    toast.add({ title: 'User deleted', color: 'green' })
    deletingUser.value = null
    await refresh()
  } catch {
    toast.add({ title: 'Failed to delete user', color: 'red' })
  } finally {
    deleting.value = false
  }
}

const roles = ['ADMIN', 'OPERATOR', 'VIEWER', 'AUDITOR']

const columns = [
  { key: 'name', label: 'Name' },
  { key: 'email', label: 'Email' },
  { key: 'role', label: 'Role' },
  { key: 'actions', label: '', noSort: true },
]

const searchQuery = ref('')

const filteredUsers = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  const items = data.value?.items ?? []
  if (!q) return items
  return items.filter((u) =>
    [u.name, u.email, u.role].some((v) => v != null && String(v).toLowerCase().includes(q)),
  )
})
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="Users">
      <template #actions>
        <Button @click="showModal = true">
          <Plus class="size-4" />
          Add User
        </Button>
      </template>
    </PageHeader>

    <DataTable
      :rows="filteredUsers"
      :columns="columns"
      :loading="pending"
      sortable
      :page-size="25"
      empty-title="No users found"
      :empty-description="searchQuery ? `Nothing matches “${searchQuery}”.` : 'Create the first user to get started.'"
    >
      <template #toolbar>
        <Input v-model="searchQuery" placeholder="Search name, email or role..." class="w-full sm:w-64" />
      </template>
      <template #role-data="{ row }">
        <Badge color="gray">{{ String(row.role).toUpperCase() }}</Badge>
      </template>
      <template #actions-data="{ row }">
        <div class="flex items-center justify-end gap-1">
          <Tooltip text="Edit user">
            <Button size="xs" variant="ghost" aria-label="Edit user" @click="openEdit(row as unknown as User)">
              <Pencil class="size-3.5" />
            </Button>
          </Tooltip>
          <Tooltip text="Delete user">
            <Button size="xs" variant="ghost" aria-label="Delete user" @click="deletingUser = row as unknown as User">
              <Trash2 class="size-3.5" />
            </Button>
          </Tooltip>
        </div>
      </template>
    </DataTable>

    <Dialog v-model="showModal" title="Create User">
      <template #body>
        <div class="space-y-3">
          <FormField label="Email">
            <Input v-model="form.email" type="email" />
          </FormField>
          <FormField label="Username">
            <Input v-model="form.username" />
          </FormField>
          <FormField label="Password">
            <Input v-model="form.password" type="password" />
          </FormField>
          <FormField label="Role">
            <Select v-model="form.role" :options="roles" />
          </FormField>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showModal = false">Cancel</Button>
        <Button :loading="saving" @click="createUser">Create</Button>
      </template>
    </Dialog>

    <Dialog :model-value="!!editingUser" title="Edit User" @update:model-value="editingUser = null">
      <template #body>
        <div class="space-y-3">
          <FormField label="Name">
            <Input :model-value="editingUser?.name ?? editingUser?.email ?? ''" disabled />
          </FormField>
          <FormField label="Role">
            <Select v-model="editRole" :options="roles" />
          </FormField>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="editingUser = null">Cancel</Button>
        <Button :loading="savingRole" @click="saveEdit">Save</Button>
      </template>
    </Dialog>

    <ConfirmDeleteDialog
      :model-value="!!deletingUser"
      :entity-name="deletingUser?.name ?? deletingUser?.email"
      :loading="deleting"
      title="Delete User"
      @update:model-value="deletingUser = null"
      @confirm="confirmDelete"
    />
  </div>
</template>
