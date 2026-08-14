<script setup lang="ts">
import type { Policy } from '~/stores/policies'

const props = defineProps<{ policy?: Policy | null }>()
const emit = defineEmits<{ close: []; saved: [] }>()

const api = useApi()
const serversStore = useServersStore()
const toast = useToast()

const isEdit = computed(() => !!props.policy)

const STEPS = ['General', 'Targets', 'Trigger', 'Action', 'Review']

const POLICY_TYPES = ['', 'UPDATE', 'SECURITY', 'COMPLIANCE', 'MAINTENANCE', 'PLUGIN']
const SEVERITIES = ['', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

type TargetMode = 'all' | 'agents' | 'filters'

function targetModeFromPolicy(p?: Policy | null): TargetMode {
  const t = p?.target_servers
  if (!t) return 'all'
  if (t.all) return 'all'
  if (t.agent_ids?.length) return 'agents'
  if (t.filters) return 'filters'
  return 'all'
}

const form = ref({
  name: props.policy?.name ?? '',
  description: props.policy?.description ?? '',
  policy_type: props.policy?.policy_type ?? '',
  severity: props.policy?.severity ?? '',
  priority: props.policy?.priority ?? 100,
  tags: (props.policy?.tags ?? []).join(', '),
  is_enabled: props.policy?.is_enabled ?? true,

  targetMode: targetModeFromPolicy(props.policy),
  agent_ids: props.policy?.target_servers?.agent_ids ?? [] as string[],
  filter_os_distro: props.policy?.target_servers?.filters?.os_distro ?? '',
  filter_category_id: props.policy?.target_servers?.filters?.category_id ?? '',
  filter_project_id: props.policy?.target_servers?.filters?.project_id ?? '',

  trigger_type: props.policy?.trigger_type ?? 'MANUAL',
  cron_expr: props.policy?.cron_expr ?? '',

  action_type: (props.policy?.actions?.[0]?.type as string) ?? 'PACKAGE_UPDATE',
  package_names: (props.policy?.actions?.[0]?.params?.package_names ?? []).join(', '),
  security_only: props.policy?.actions?.[0]?.params?.security_only ?? false,
  command: props.policy?.actions?.[0]?.params?.command ?? '',

  requires_approval: props.policy?.execution?.requires_approval ?? false,
})

const agentOptions = ref<Array<{ label: string; value: string }>>([])
const categoryOptions = computed(() => serversStore.categories.map((c) => ({ label: c.name, value: c.id })))
const projectOptions = computed(() => serversStore.projects.map((p) => ({ label: p.name, value: p.id })))

onMounted(async () => {
  agentOptions.value = await serversStore.fetchAgentsForSelect()
  if (!serversStore.categories.length) await serversStore.fetchCategories()
  if (!serversStore.projects.length) await serversStore.fetchProjects()
})

const submitting = ref(false)
const stepError = ref<string | null>(null)
const stepperRef = ref<any>(null)

function onContinue() {
  const idx = stepperRef.value.stepper.index.value
  const err = validateStep(idx)
  if (err) { stepError.value = err; return }
  stepError.value = null
  stepperRef.value.stepper.goToNext()
}

function validateStep(stepIndex: number): string | null {
  switch (STEPS[stepIndex]) {
    case 'General':
      if (!form.value.name.trim()) return 'Name is required'
      return null
    case 'Targets':
      if (form.value.targetMode === 'agents' && form.value.agent_ids.length === 0)
        return 'Select at least one server'
      if (form.value.targetMode === 'filters' && !form.value.filter_os_distro && !form.value.filter_category_id && !form.value.filter_project_id)
        return 'Set at least one filter'
      return null
    case 'Trigger':
      if (form.value.trigger_type === 'SCHEDULE' && !form.value.cron_expr.trim())
        return 'Cron expression is required for scheduled triggers'
      return null
    case 'Action':
      if (form.value.action_type === 'CUSTOM_COMMAND' && !form.value.command.trim())
        return 'Command is required'
      return null
    default:
      return null
  }
}

function buildPayload() {
  const target_servers =
    form.value.targetMode === 'all' ? { all: true }
    : form.value.targetMode === 'agents' ? { agent_ids: form.value.agent_ids }
    : {
        filters: {
          ...(form.value.filter_os_distro ? { os_distro: form.value.filter_os_distro } : {}),
          ...(form.value.filter_category_id ? { category_id: form.value.filter_category_id } : {}),
          ...(form.value.filter_project_id ? { project_id: form.value.filter_project_id } : {}),
        },
      }

  const params =
    form.value.action_type === 'PACKAGE_UPDATE'
      ? {
          ...(form.value.package_names.trim()
            ? { package_names: form.value.package_names.split(',').map((s) => s.trim()).filter(Boolean) }
            : {}),
          ...(form.value.security_only ? { security_only: true } : {}),
        }
      : { command: form.value.command }

  return {
    name: form.value.name,
    description: form.value.description || null,
    policy_type: form.value.policy_type || null,
    rules: {},
    target_servers,
    is_enabled: form.value.is_enabled,
    priority: form.value.priority,
    severity: form.value.severity || null,
    tags: form.value.tags.split(',').map((s) => s.trim()).filter(Boolean),
    trigger_type: form.value.trigger_type,
    cron_expr: form.value.trigger_type === 'SCHEDULE' ? form.value.cron_expr : null,
    actions: [{ type: form.value.action_type, params }],
    execution: { requires_approval: form.value.requires_approval },
  }
}

async function submit() {
  const err = validateStep(3) // re-check the action step, the last one with real validation
  if (err) {
    stepError.value = err
    return
  }
  submitting.value = true
  try {
    const payload = buildPayload()
    if (isEdit.value && props.policy) {
      await api.patch(`/policies/${props.policy.id}`, payload)
      toast.add({ title: 'Policy updated', color: 'green' })
    } else {
      await api.post('/policies', payload)
      toast.add({ title: 'Policy created', color: 'green' })
    }
    emit('saved')
  } catch (e) {
    const detail = (e as { data?: { detail?: string } })?.data?.detail
    toast.add({ title: 'Error', description: detail || 'Failed to save policy', color: 'red' })
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <Dialog
    :model-value="true"
    :title="isEdit ? 'Edit policy' : 'New policy'"
    size="xl"
    @update:model-value="(open: boolean) => { if (!open) emit('close') }"
  >
    <template #body>
      <Stepper ref="stepperRef" :steps="STEPS" v-slot="{ stepper }">
        <div class="min-h-[280px]">
          <div v-if="stepError" class="mb-4">
            <Alert color="red" :description="stepError" />
          </div>

          <!-- General -->
          <div v-if="stepper.current.value === 'General'" class="space-y-4">
            <FormField label="Name" required>
              <Input v-model="form.name" placeholder="ex: Monthly Security Update" />
            </FormField>
            <FormField label="Description">
              <Textarea v-model="form.description" placeholder="What this policy does..." />
            </FormField>
            <div class="grid grid-cols-2 gap-4">
              <FormField label="Category">
                <Select v-model="form.policy_type" :options="POLICY_TYPES" placeholder="No category" />
              </FormField>
              <FormField label="Severity">
                <Select v-model="form.severity" :options="SEVERITIES" placeholder="No severity" />
              </FormField>
              <FormField label="Priority" help="Lower = executed first">
                <Input v-model.number="form.priority" type="number" />
              </FormField>
              <FormField label="Tags" help="comma-separated">
                <Input v-model="form.tags" placeholder="prod, patching" />
              </FormField>
            </div>
            <div class="flex items-center gap-2">
              <Switch v-model="form.is_enabled" />
              <span class="text-[13px]">Active</span>
            </div>
          </div>

          <!-- Targets -->
          <div v-else-if="stepper.current.value === 'Targets'" class="space-y-4">
            <FormField label="Target servers">
              <Select
                v-model="form.targetMode"
                :options="[{ label: 'All servers', value: 'all' }, { label: 'Individual servers', value: 'agents' }, { label: 'Filter (OS / category / project)', value: 'filters' }]"
              />
            </FormField>
            <FormField v-if="form.targetMode === 'agents'" label="Select servers" required>
              <MultiSelect v-model="form.agent_ids" :options="agentOptions" placeholder="Select servers..." />
            </FormField>
            <div v-else-if="form.targetMode === 'filters'" class="grid grid-cols-2 gap-4">
              <FormField label="OS Distribution">
                <Input v-model="form.filter_os_distro" placeholder="e.g. rocky" />
              </FormField>
              <FormField label="Category">
                <Select v-model="form.filter_category_id" :options="[{ label: 'Any category', value: '' }, ...categoryOptions]" />
              </FormField>
              <FormField label="Project">
                <Select v-model="form.filter_project_id" :options="[{ label: 'Any project', value: '' }, ...projectOptions]" />
              </FormField>
            </div>
          </div>

          <!-- Trigger -->
          <div v-else-if="stepper.current.value === 'Trigger'" class="space-y-4">
            <FormField label="Trigger type">
              <Select
                v-model="form.trigger_type"
                :options="[{ label: 'Manual', value: 'MANUAL' }, { label: 'Scheduled (cron)', value: 'SCHEDULE' }]"
              />
            </FormField>
            <FormField
              v-if="form.trigger_type === 'SCHEDULE'"
              label="Cron expression"
              required
              help="e.g. 0 2 * * * — daily at 02:00 UTC"
            >
              <Input v-model="form.cron_expr" placeholder="0 2 * * *" class="font-mono" />
            </FormField>
          </div>

          <!-- Action -->
          <div v-else-if="stepper.current.value === 'Action'" class="space-y-4">
            <FormField label="Action type">
              <Select
                v-model="form.action_type"
                :options="[{ label: 'Package update', value: 'PACKAGE_UPDATE' }, { label: 'Shell command', value: 'CUSTOM_COMMAND' }]"
              />
            </FormField>
            <template v-if="form.action_type === 'PACKAGE_UPDATE'">
              <FormField label="Packages" help="empty = all packages; otherwise comma-separated list">
                <Input v-model="form.package_names" placeholder="curl, openssl" />
              </FormField>
              <div class="flex items-center gap-2">
                <Switch v-model="form.security_only" />
                <span class="text-[13px]">Security updates only</span>
              </div>
            </template>
            <FormField v-else label="Shell command" required help="runs as root on each target server">
              <Textarea v-model="form.command" placeholder="systemctl restart nginx" :rows="4" />
            </FormField>
            <div class="flex items-center gap-2">
              <Switch v-model="form.requires_approval" />
              <span class="text-[13px]">Requires approval before execution</span>
            </div>
          </div>

          <!-- Review -->
          <div v-else class="space-y-3 text-sm">
            <dl class="grid grid-cols-2 gap-x-6 gap-y-2">
              <div><dt class="text-muted-foreground">Name</dt><dd class="font-medium">{{ form.name }}</dd></div>
              <div><dt class="text-muted-foreground">Trigger</dt><dd>{{ form.trigger_type === 'SCHEDULE' ? `cron: ${form.cron_expr}` : 'Manual' }}</dd></div>
              <div><dt class="text-muted-foreground">Targets</dt>
                <dd>
                  {{ form.targetMode === 'all' ? 'All servers' : form.targetMode === 'agents' ? `${form.agent_ids.length} servers selected` : 'Filter' }}
                </dd>
              </div>
              <div><dt class="text-muted-foreground">Action</dt><dd>{{ form.action_type === 'PACKAGE_UPDATE' ? 'Package update' : 'Shell command' }}</dd></div>
            </dl>
          </div>
        </div>
      </Stepper>
    </template>
    <template #footer>
      <Button variant="ghost" :disabled="stepperRef?.stepper.isFirst.value" @click="stepperRef.stepper.goToPrevious()">Back</Button>
      <Button v-if="!stepperRef?.stepper.isLast.value" @click="onContinue">Continue</Button>
      <Button v-else :loading="submitting" @click="submit">{{ isEdit ? 'Save' : 'Create policy' }}</Button>
    </template>
  </Dialog>
</template>
