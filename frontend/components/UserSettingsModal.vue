<script setup lang="ts">
interface Props {
  modelValue: boolean
}

interface Emits {
  (e: 'update:modelValue', value: boolean): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const { user: currentUser } = useCurrentUser()
const authClient = useAuth()
const toast = useToast()

const profileForm = reactive({ name: '' })
const savingProfile = ref(false)

watch(() => props.modelValue, (open) => {
  if (open) {
    profileForm.name = currentUser.value?.name
      ?? (currentUser.value as Record<string, unknown>)?.username as string
      ?? ''
  }
}, { immediate: true })

async function saveProfile() {
  savingProfile.value = true
  try {
    await authClient.updateUser({ name: profileForm.name })
    toast.add({ title: 'Profile updated', color: 'green' })
  } catch {
    toast.add({ title: 'Failed to update profile', color: 'red' })
  } finally {
    savingProfile.value = false
  }
}

function handleSecurity() {
  emit('update:modelValue', false)
  navigateTo('/account/security')
}
</script>

<template>
  <Dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" title="User Settings">
    <template #body>
      <div class="space-y-4">
        <FormField label="Name">
          <Input v-model="profileForm.name" placeholder="Your name" />
        </FormField>
        <FormField label="Email" help="Email changes require SMTP verification, currently unavailable">
          <Input
            :model-value="(currentUser as Record<string, unknown>)?.email ?? ''"
            disabled
            type="email"
            placeholder="your.email@example.com"
          />
        </FormField>
        <div class="flex gap-2 pt-2">
          <Button :loading="savingProfile" size="sm" @click="saveProfile">
            Save Name
          </Button>
          <Button variant="outline" size="sm" @click="handleSecurity">
            Security & Password
          </Button>
        </div>
      </div>
    </template>

    <template #footer>
      <Button variant="ghost" @click="$emit('update:modelValue', false)">
        Close
      </Button>
    </template>
  </Dialog>
</template>
