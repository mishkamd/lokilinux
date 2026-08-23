<script setup lang="ts">
import { watchDebounced } from '@vueuse/core'
import { X } from 'lucide-vue-next'
import { nodeDefinition, TONE_BG } from '~/utils/workflow/registry'
import type { WorkflowNode } from '~/types/workflow'

const props = defineProps<{ node: WorkflowNode }>()
const emit = defineEmits<{
  'update-field': [field: string, value: unknown]
  'update-config': [key: string, value: unknown]
  close: []
}>()

const def = computed(() => nodeDefinition(props.node.type))

const ON_FAILURE_OPTIONS = [
  { label: '(inherit default)', value: '' },
  { label: 'Stop', value: 'stop' },
  { label: 'Continue', value: 'continue' },
  { label: 'Branch', value: 'branch' },
]

// Same local-then-debounced-commit shape as WorkflowNodeConfigForm.vue —
// text/number step fields shouldn't push a store patch on every keystroke.
const nameLocal = ref('')
const timeoutLocal = ref('')
const retryAttemptsLocal = ref('')
const retryDelayLocal = ref('')

// The id field is deliberately NOT part of the watchDebounced-on-every-
// keystroke group above: a step id has uniqueness and pattern constraints
// (Faza B §B7 — see applyRenameStep) that would fail mid-type on almost
// every keystroke, and each attempt would also flip selectedNodeId to
// whatever partial string was just typed, closing this very panel. Commits
// once, on blur/Enter, going straight to the store (same direct-store-call
// pattern WorkflowNodeConfigForm.vue already uses for usePlaybooksStore)
// since it needs renameStep's synchronous success/failure return to show
// an inline error — an emit up to the page couldn't hand that back.
const store = useWorkflowStore()
const idLocal = ref('')
const idError = ref('')

function resetFromNode() {
  nameLocal.value = props.node.name
  timeoutLocal.value = props.node.timeout !== undefined ? String(props.node.timeout) : ''
  retryAttemptsLocal.value = props.node.retry?.attempts !== undefined ? String(props.node.retry.attempts) : ''
  retryDelayLocal.value = props.node.retry?.delay !== undefined ? String(props.node.retry.delay) : ''
  idLocal.value = props.node.id
  idError.value = ''
}
watch(() => props.node.id, resetFromNode, { immediate: true })

function onIdBlur() {
  if (idLocal.value === props.node.id) { idError.value = ''; return }
  if (store.renameStep(props.node.id, idLocal.value)) {
    idError.value = ''
  } else {
    idError.value = 'Must be unique and match ^[a-z0-9_-]{1,64}$'
    idLocal.value = props.node.id
  }
}

watchDebounced(nameLocal, (v) => { if (v) emit('update-field', 'name', v) }, { debounce: 400 })
watchDebounced(timeoutLocal, (v) => emit('update-field', 'timeout', v === '' ? undefined : Number(v)), { debounce: 400 })
watchDebounced(retryAttemptsLocal, (v) => emit('update-field', 'retry.attempts', v === '' ? undefined : Number(v)), { debounce: 400 })
watchDebounced(retryDelayLocal, (v) => emit('update-field', 'retry.delay', v === '' ? undefined : Number(v)), { debounce: 400 })

function onDisabledChange(v: boolean) {
  emit('update-field', 'disabled', v || undefined)
}
function onFailureChange(v: string) {
  emit('update-field', 'on_failure', v === '' ? undefined : v)
}
</script>

<template>
  <div class="flex h-full w-80 shrink-0 flex-col border-l border-border bg-card">
    <div class="flex items-center gap-2.5 border-b border-border px-3 py-2.5">
      <span class="flex size-7 shrink-0 items-center justify-center rounded-md" :class="TONE_BG[def.tone]">
        <component :is="def.icon" class="size-3.5" />
      </span>
      <div class="min-w-0 flex-1">
        <p class="truncate text-[13px] font-medium">{{ def.label }}</p>
        <p class="label-caps text-[10px] text-muted-foreground">{{ node.id }}</p>
      </div>
      <button type="button" class="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label="Close" @click="emit('close')">
        <X class="size-4" />
      </button>
    </div>

    <div class="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
      <p class="text-xs text-muted-foreground">{{ def.description }}</p>

      <div class="space-y-3 border-b border-border pb-4">
        <FormField label="ID">
          <Input v-model="idLocal" class="font-mono text-xs" @blur="onIdBlur" @keyup.enter="($event.target as HTMLElement).blur()" />
          <p v-if="idError" class="mt-1 text-[11px] text-destructive">{{ idError }}</p>
        </FormField>
        <FormField label="Name">
          <Input v-model="nameLocal" />
        </FormField>
        <FormField label="Timeout (seconds)" help="Falls back to spec.defaults.timeout when empty.">
          <Input v-model="timeoutLocal" type="number" />
        </FormField>
        <FormField label="On failure">
          <Select :model-value="node.on_failure ?? ''" :options="ON_FAILURE_OPTIONS" @update:model-value="(v) => onFailureChange(v as string)" />
        </FormField>
        <div class="grid grid-cols-2 gap-2">
          <FormField label="Retry attempts">
            <Input v-model="retryAttemptsLocal" type="number" />
          </FormField>
          <FormField label="Retry delay (s)">
            <Input v-model="retryDelayLocal" type="number" />
          </FormField>
        </div>
        <div class="flex items-center justify-between">
          <Label>Disabled</Label>
          <Switch :model-value="!!node.disabled" @update:model-value="onDisabledChange" />
        </div>
      </div>

      <WorkflowNodeConfigForm :node="node" @update-config="(key, value) => emit('update-config', key, value)" />
    </div>
  </div>
</template>
