<script setup lang="ts">
import { watchDebounced } from '@vueuse/core'
import { X, Trash2 } from 'lucide-vue-next'
import type { WorkflowEdge } from '~/types/workflow'

// Faza B §D5 — without this panel the 4 handles added in WorkflowNodeBase.vue
// are half-useless: a fresh Handle-to-Handle drag always defaults `on` to
// 'success' (stores/workflow.ts addEdge), so a failure/rollback branch still
// required hand-editing YAML. This is the other half — click an edge, set
// its condition and an optional label, all from the canvas.
const props = defineProps<{ edge: WorkflowEdge }>()
const emit = defineEmits<{
  'update-edge': [patch: { on?: WorkflowEdge['on']; label?: string }]
  delete: []
  close: []
}>()

const ON_OPTIONS = [
  { label: 'Success', value: 'success' },
  { label: 'Failure', value: 'failure' },
  { label: 'Always', value: 'always' },
]

// Same local-then-debounced-commit shape as WorkflowProperties.vue — typing
// a label shouldn't push a store patch (and a history commit) per keystroke.
const labelLocal = ref('')
function resetFromEdge() {
  labelLocal.value = props.edge.label ?? ''
}
watch(() => props.edge.id, resetFromEdge, { immediate: true })
watchDebounced(labelLocal, (v) => emit('update-edge', { label: v }), { debounce: 400 })

function onOnChange(v: string) {
  emit('update-edge', { on: v as WorkflowEdge['on'] })
}
</script>

<template>
  <div class="flex h-full w-80 shrink-0 flex-col border-l border-border bg-card">
    <div class="flex items-center gap-2.5 border-b border-border px-3 py-2.5">
      <div class="min-w-0 flex-1">
        <p class="truncate text-[13px] font-medium">Edge</p>
        <p class="label-caps truncate text-[10px] text-muted-foreground">{{ edge.from }} → {{ edge.to }}</p>
      </div>
      <button type="button" class="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label="Close" @click="emit('close')">
        <X class="size-4" />
      </button>
    </div>

    <div class="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
      <FormField label="On" help="Which of this edge's step's outcomes traverses it.">
        <Select :model-value="edge.on" :options="ON_OPTIONS" @update:model-value="(v) => onOnChange(v as string)" />
      </FormField>
      <FormField label="Label">
        <Input v-model="labelLocal" placeholder="Optional" />
      </FormField>
      <Button size="sm" variant="destructive" class="w-full" @click="emit('delete')">
        <Trash2 class="size-3.5" />
        Delete edge
      </Button>
    </div>
  </div>
</template>
