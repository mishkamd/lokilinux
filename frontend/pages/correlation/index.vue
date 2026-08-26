<script setup lang="ts">
import { Plus, Trash2 } from 'lucide-vue-next'
import type { CorrelationCondition, CorrelationRule, CorrelationRuleInput } from '~/stores/correlation'

const store = useCorrelationStore()
const { rules, loading } = storeToRefs(store)
const toast = useToast()
const { severityColor } = useSeverity()

const columns = [
  { key: 'name', label: 'Name' },
  { key: 'incident_type', label: 'Incident type' },
  { key: 'incident_severity', label: 'Severity' },
  { key: 'threshold_score', label: 'Threshold' },
  { key: 'window_seconds', label: 'Window' },
  { key: 'enabled', label: 'Enabled' },
  { key: 'actions', label: '' },
]

const showEditor = ref(false)
const editingId = ref<string | null>(null)
const submitting = ref(false)
const form = ref<CorrelationRuleInput>(emptyForm())

function emptyForm(): CorrelationRuleInput {
  return {
    name: '', enabled: true, window_seconds: 300, group_by: ['host_id'],
    conditions: [{ signal: '', weight: 20 }], threshold_score: 60,
    incident_type: '', incident_severity: 'HIGH',
  }
}

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  showEditor.value = true
}

function openEdit(rule: CorrelationRule) {
  editingId.value = rule.id
  form.value = {
    name: rule.name, enabled: rule.enabled, window_seconds: rule.window_seconds,
    group_by: [...rule.group_by], conditions: rule.conditions.map((c) => ({ ...c })),
    threshold_score: rule.threshold_score, incident_type: rule.incident_type,
    incident_severity: rule.incident_severity,
  }
  showEditor.value = true
}

function addCondition() {
  form.value.conditions.push({ signal: '', weight: 20 })
}

function removeCondition(idx: number) {
  form.value.conditions.splice(idx, 1)
}

function validate(): string | null {
  if (!form.value.name.trim()) return 'Name is required'
  if (!form.value.incident_type.trim()) return 'Incident type is required'
  if (form.value.window_seconds < 30 || form.value.window_seconds > 3600) return 'Window must be 30-3600 seconds'
  if (form.value.threshold_score <= 0) return 'Threshold must be > 0'
  if (!form.value.conditions.length) return 'At least one condition is required'
  for (const c of form.value.conditions) {
    if (!c.signal.trim()) return 'Every condition needs a signal name'
    if (!c.weight || c.weight <= 0) return 'Every condition needs a weight > 0'
  }
  return null
}

async function submit() {
  const err = validate()
  if (err) {
    toast.add({ title: 'Invalid rule', description: err, color: 'red' })
    return
  }
  submitting.value = true
  try {
    if (editingId.value) {
      await store.updateRule(editingId.value, form.value)
      toast.add({ title: 'Rule updated', color: 'green' })
    } else {
      await store.createRule(form.value)
      toast.add({ title: 'Rule created', color: 'green' })
    }
    showEditor.value = false
  } catch {
    toast.add({ title: 'Error', description: 'Failed to save rule', color: 'red' })
  } finally {
    submitting.value = false
  }
}

const deletingRule = ref<CorrelationRule | null>(null)
const deleting = ref(false)

async function confirmDelete() {
  if (!deletingRule.value) return
  deleting.value = true
  try {
    await store.deleteRule(deletingRule.value.id)
    deletingRule.value = null
  } catch {
    toast.add({ title: 'Error', description: 'Failed to delete rule', color: 'red' })
  } finally {
    deleting.value = false
  }
}

async function toggle(rule: CorrelationRule) {
  try {
    await store.toggleEnabled(rule)
  } catch {
    toast.add({ title: 'Error', description: 'Failed to toggle rule', color: 'red' })
  }
}

onMounted(() => store.fetchRules())
</script>

<template>
  <div>
    <div class="flex items-center justify-end mb-4">
      <Button @click="openCreate">
        <Plus class="size-4" />
        New rule
      </Button>
    </div>

    <DataTable :rows="rules" :columns="columns" :loading="loading">
      <template #name-data="{ row }">
        <button class="font-medium hover:underline" @click="openEdit(row as CorrelationRule)">{{ row.name }}</button>
      </template>
      <template #incident_severity-data="{ row }">
        <Badge :color="severityColor(String(row.incident_severity))" size="xs">{{ row.incident_severity }}</Badge>
      </template>
      <template #threshold_score-data="{ row }">
        <span class="font-mono text-xs tabular-nums">{{ row.threshold_score }}</span>
      </template>
      <template #window_seconds-data="{ row }">
        <span class="font-mono text-xs">{{ row.window_seconds }}s</span>
      </template>
      <template #enabled-data="{ row }">
        <Switch :model-value="Boolean(row.enabled)" @update:model-value="toggle(row as CorrelationRule)" />
      </template>
      <template #actions-data="{ row }">
        <Button size="xs" variant="ghost" class="text-muted-foreground" aria-label="Delete rule" @click="deletingRule = row as CorrelationRule">
          <Trash2 class="size-3.5" />
        </Button>
      </template>
    </DataTable>

    <Dialog v-model="showEditor" :title="editingId ? 'Edit rule' : 'New rule'" size="lg">
      <template #body>
        <div class="space-y-4">
          <div class="grid grid-cols-2 gap-3">
            <FormField label="Name" required>
              <Input v-model="form.name" />
            </FormField>
            <FormField label="Incident type" required>
              <Input v-model="form.incident_type" placeholder="application_degradation" />
            </FormField>
            <FormField label="Incident severity">
              <Select v-model="form.incident_severity" :options="['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']" />
            </FormField>
            <FormField label="Threshold score">
              <Input v-model.number="form.threshold_score" type="number" min="1" />
            </FormField>
            <FormField label="Window (seconds, 30-3600)">
              <Input v-model.number="form.window_seconds" type="number" min="30" max="3600" />
            </FormField>
          </div>

          <FormField label="Conditions (signal type + weight)">
            <div class="space-y-2">
              <div v-for="(c, i) in form.conditions" :key="i" class="flex items-center gap-2">
                <Input v-model="(c as CorrelationCondition).signal" placeholder="cpu.high" class="flex-1" />
                <Input v-model.number="(c as CorrelationCondition).weight" type="number" min="1" class="w-24" placeholder="weight" />
                <Button size="xs" variant="ghost" class="text-muted-foreground" aria-label="Remove condition" @click="removeCondition(i)">
                  <Trash2 class="size-3.5" />
                </Button>
              </div>
              <Button size="xs" variant="outline" @click="addCondition">
                <Plus class="size-3.5" />
                Add condition
              </Button>
            </div>
          </FormField>
        </div>
      </template>
      <template #footer>
        <Button variant="ghost" @click="showEditor = false">Cancel</Button>
        <Button :loading="submitting" @click="submit">{{ editingId ? 'Save' : 'Create' }}</Button>
      </template>
    </Dialog>

    <Dialog :model-value="!!deletingRule" title="Delete rule" @update:model-value="deletingRule = null">
      <template #body>
        <p class="text-sm text-muted-foreground">
          Delete <strong class="text-foreground">{{ deletingRule?.name }}</strong>? This cannot be undone.
        </p>
      </template>
      <template #footer>
        <Button variant="ghost" @click="deletingRule = null">Cancel</Button>
        <Button variant="destructive" :loading="deleting" @click="confirmDelete">Delete</Button>
      </template>
    </Dialog>
  </div>
</template>
