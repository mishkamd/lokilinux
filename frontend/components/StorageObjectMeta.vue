<script setup lang="ts">
/**
 * Read-only metadata panel for one object-storage object — fetched lazily
 * from GET /storage/objects/{id}. Never shows credentials or internal
 * RustFS details, only what CLAUDE.md's storage UI section asks for:
 * provider, object key, size, SHA-256, version.
 */
interface StorageObject {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  sha256: string
  storage_provider: string
  bucket: string
  object_key: string
  version: number
  category: string
  status: string
  created_at: string
}

const props = defineProps<{ objectId: string }>()

const api = useApi()
const object = ref<StorageObject | null>(null)
const loading = ref(true)
const error = ref(false)

onMounted(async () => {
  try {
    object.value = await api.get<StorageObject>(`/storage/objects/${props.objectId}`)
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <p v-if="loading" class="text-sm text-muted-foreground">Loading storage metadata…</p>
  <p v-else-if="error || !object" class="text-sm text-destructive">Storage metadata unavailable.</p>
  <dl v-else class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
    <dt class="text-muted-foreground">Storage</dt>
    <dd class="font-mono text-xs uppercase">{{ object.storage_provider }}</dd>

    <dt class="text-muted-foreground">Object</dt>
    <dd class="font-mono text-xs break-all">{{ object.object_key }}</dd>

    <dt class="text-muted-foreground">Size</dt>
    <dd>{{ formatBytes(object.size_bytes) }}</dd>

    <dt class="text-muted-foreground">SHA-256</dt>
    <dd class="font-mono text-xs break-all" :title="object.sha256">{{ object.sha256 }}</dd>

    <dt class="text-muted-foreground">Version</dt>
    <dd>v{{ object.version }}</dd>
  </dl>
</template>
