<script setup lang="ts">
import { RefreshCw, Play } from 'lucide-vue-next'

interface Policy {
  id: string
  name: string
  description: string | null
  policy_type: 'UPDATE' | 'SECURITY' | 'COMPLIANCE' | 'MAINTENANCE' | 'PLUGIN' | null
  is_enabled: boolean
  priority: number
  version: number
  created_at: string
  updated_at: string
  target_servers: { filters?: Record<string, string> } | null
}

const api = useApi()
const policies = ref<Policy[]>([])
const total = ref(0)
const loading = ref(false)
const applyingId = ref<string | null>(null)

async function fetchPolicies() {
  loading.value = true
  try {
    const data = await api.get<{ items: Policy[]; total: number }>('/policies')
    policies.value = data.items
    total.value = data.total ?? 0
  } finally {
    loading.value = false
  }
}

async function toggleEnabled(policy: Policy) {
  policy.is_enabled = !policy.is_enabled
  await api.patch(`/policies/${policy.id}`, { is_enabled: policy.is_enabled })
}

async function applyPolicy(policy: Policy) {
  applyingId.value = policy.id
  try {
    await api.post(`/policies/${policy.id}/apply`)
    useToast().add({ title: `Policy "${policy.name}" applied`, color: 'green' })
  } finally {
    applyingId.value = null
  }
}

onMounted(fetchPolicies)

const POLICY_TYPE_COLORS: Record<string, string> = {
  UPDATE: 'gray',
  SECURITY: 'red',
  COMPLIANCE: 'gray',
  MAINTENANCE: 'gray',
  PLUGIN: 'gray',
}

const columns = [
  { key: 'name', label: 'Name' },
  { key: 'policy_type', label: 'Type' },
  { key: 'priority', label: 'Priority' },
  { key: 'version', label: 'Version' },
  { key: 'is_enabled', label: 'Enabled' },
  { key: 'updated_at', label: 'Updated' },
  { key: 'actions', label: '' },
]
</script>

<template>
  <div>
    <div class="flex items-center justify-end mb-4">
      <div class="flex items-center gap-3">
        <Badge color="gray">{{ total }} policies</Badge>
        <Button variant="outline" @click="fetchPolicies()">
          <RefreshCw class="size-4" />
          Refresh
        </Button>
      </div>
    </div>

    <DataTable :rows="policies" :columns="columns" :loading="loading">
      <template #policy_type-data="{ row }">
        <Badge
          v-if="row.policy_type"
          :color="POLICY_TYPE_COLORS[String(row.policy_type)] ?? 'gray'"
          size="xs"
        >{{ row.policy_type }}</Badge>
        <span v-else class="text-muted-foreground">—</span>
      </template>

      <template #is_enabled-data="{ row }">
        <Switch
          :model-value="Boolean(row.is_enabled)"
          @update:model-value="toggleEnabled(row as unknown as Policy)"
        />
      </template>

      <template #updated_at-data="{ row }">
        {{ new Date(String(row.updated_at)).toLocaleDateString() }}
      </template>

      <template #actions-data="{ row }">
        <Button
          size="xs"
          variant="outline"
          :loading="applyingId === row.id"
          @click="applyPolicy(row as unknown as Policy)"
        >
          <Play class="size-3" />
          Apply
        </Button>
      </template>
    </DataTable>
  </div>
</template>
