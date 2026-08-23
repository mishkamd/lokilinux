<script setup lang="ts">
import { watchDebounced } from '@vueuse/core'
import { nodeDefinition } from '~/utils/workflow/registry'
import type { FieldSpec } from '~/utils/workflow/registry'
import type { WorkflowNode } from '~/types/workflow'

// One renderer for all 8 step types, driven entirely by the selected node's
// NodeDefinition.fields (the form-side half of The One Node Shell Rule,
// plan §7) — a new node type needs a registry entry, never a new component.
const props = defineProps<{ node: WorkflowNode }>()
const emit = defineEmits<{ 'update-config': [key: string, value: unknown] }>()

const def = computed(() => nodeDefinition(props.node.type))

// A field with showIf only renders while another field in the SAME config
// currently holds one of the listed values — evaluated against the local
// (unsaved) form state so switching e.g. `action` reacts instantly, not
// after the 400ms debounce commits it to the store.
const visibleFields = computed(() =>
  def.value.fields.filter((field) => {
    if (!field.showIf) return true
    return field.showIf.equals.includes(local[field.showIf.key] ?? '')
  }),
)

const playbooksStore = usePlaybooksStore()
const { playbooks } = storeToRefs(playbooksStore)
onMounted(() => {
  if (def.value.fields.some(f => f.type === 'playbook')) playbooksStore.fetchPlaybooks()
})
const playbookOptions = computed(() => playbooks.value.map(p => ({ label: p.name, value: p.id })))

// Local, uncontrolled-from-the-store text per field — decouples typing from
// the store round-trip the same way the YAML tab's own debounce does, and
// specifically avoids a half-typed JSON value getting stomped by a v-bind
// reset back to the last successfully-parsed one on every keystroke.
const local = reactive<Record<string, string>>({})
const localList = reactive<Record<string, string[]>>({})
const jsonErrors = reactive<Record<string, boolean>>({})

function _stringify(field: FieldSpec, value: unknown): string {
  if (value === undefined || value === null) return ''
  if (field.type === 'json') return JSON.stringify(value, null, 2)
  return String(value)
}

function resetFromNode() {
  for (const key in jsonErrors) delete jsonErrors[key]
  for (const field of def.value.fields) {
    if (field.type === 'list') {
      localList[field.key] = Array.isArray(props.node.config[field.key]) ? [...(props.node.config[field.key] as string[])] : []
    } else {
      local[field.key] = _stringify(field, props.node.config[field.key])
    }
  }
}

watch(() => props.node.id, resetFromNode, { immediate: true })

watchDebounced(local, () => {
  for (const field of def.value.fields) {
    if (field.type === 'list') continue
    const raw = local[field.key] ?? ''
    if (field.type === 'number') {
      emit('update-config', field.key, raw === '' ? undefined : Number(raw))
    } else if (field.type === 'json') {
      if (raw.trim() === '') { jsonErrors[field.key] = false; emit('update-config', field.key, undefined); continue }
      try {
        const parsed = JSON.parse(raw)
        jsonErrors[field.key] = false
        emit('update-config', field.key, parsed)
      } catch {
        jsonErrors[field.key] = true // don't commit — keeps the last-valid value in the YAML until this is fixed
      }
    } else {
      emit('update-config', field.key, raw === '' ? undefined : raw)
    }
  }
}, { debounce: 400, deep: true })

function onListUpdate(key: string, value: string[]) {
  localList[key] = value
  emit('update-config', key, value.length ? value : undefined)
}
</script>

<template>
  <div class="space-y-3">
    <FormField v-for="field in visibleFields" :key="field.key" :label="field.label" :help="field.help">
      <Input v-if="field.type === 'text'" v-model="local[field.key]" :placeholder="field.placeholder" />
      <Input v-else-if="field.type === 'number'" v-model="local[field.key]" type="number" :placeholder="field.placeholder" />
      <Textarea v-else-if="field.type === 'textarea'" v-model="local[field.key]" :rows="4" :placeholder="field.placeholder" class="text-xs" />
      <template v-else-if="field.type === 'json'">
        <Textarea v-model="local[field.key]" :rows="5" placeholder="{}" class="font-mono text-xs" />
        <p v-if="jsonErrors[field.key]" class="mt-1 text-[11px] text-destructive">Invalid JSON — not saved until this is fixed.</p>
      </template>
      <Select
        v-else-if="field.type === 'select'"
        :model-value="local[field.key]"
        :options="field.options ?? []"
        @update:model-value="(v) => { local[field.key] = v as string }"
      />
      <Select
        v-else-if="field.type === 'playbook'"
        :model-value="local[field.key]"
        :options="playbookOptions"
        placeholder="Select a playbook…"
        @update:model-value="(v) => { local[field.key] = v as string }"
      />
      <TagInput
        v-else-if="field.type === 'list'"
        :model-value="localList[field.key]"
        :placeholder="field.placeholder"
        @update:model-value="(v) => onListUpdate(field.key, v)"
      />
    </FormField>
    <p v-if="!visibleFields.length" class="text-xs text-muted-foreground">This step type has no configuration.</p>
  </div>
</template>
