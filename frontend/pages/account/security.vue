<script setup lang="ts">
definePageMeta({ layout: 'default' })

const authClient = useAuth()
const { user: currentUser } = useCurrentUser()
const toast = useToast()

const isEnabled = computed(() => !!(currentUser.value as Record<string, unknown>)?.twoFactorEnabled)

const step = ref<'idle' | 'enroll' | 'verify'>('idle')
const password = ref('')
const totpSecret = ref('')
const backupCodes = ref<string[]>([])
const verifyCode = ref('')
const pending = ref(false)

const pwForm = reactive({ current: '', next: '' })
const pwPending = ref(false)

async function changePassword() {
  pwPending.value = true
  try {
    await authClient.changePassword({ currentPassword: pwForm.current, newPassword: pwForm.next })
    toast.add({ title: 'Password changed', color: 'green' })
    pwForm.current = ''
    pwForm.next = ''
  } catch (error: unknown) {
    const err = error as { message?: string }
    toast.add({ title: 'Could not change password', description: err?.message, color: 'red' })
  } finally {
    pwPending.value = false
  }
}

function extractSecret(totpURI: string): string {
  try {
    return new URL(totpURI).searchParams.get('secret') ?? totpURI
  } catch {
    return totpURI
  }
}

async function startEnroll() {
  pending.value = true
  try {
    const res = await authClient.twoFactor.enable({ password: password.value })
    const data = (res as { data?: { totpURI: string; backupCodes: string[] } }).data
    if (!data) throw new Error('no data')
    totpSecret.value = extractSecret(data.totpURI)
    backupCodes.value = data.backupCodes
    step.value = 'verify'
  } catch (error: unknown) {
    const err = error as { message?: string }
    toast.add({ title: 'Could not start enrollment', description: err?.message, color: 'red' })
  } finally {
    pending.value = false
  }
}

async function confirmEnroll() {
  pending.value = true
  try {
    await authClient.twoFactor.verifyTotp({ code: verifyCode.value })
    toast.add({ title: '2FA enabled', color: 'green' })
    step.value = 'idle'
    password.value = ''
    verifyCode.value = ''
    await authClient.getSession({ query: { disableCookieCache: true } })
  } catch (error: unknown) {
    const err = error as { message?: string }
    toast.add({ title: 'Invalid code', description: err?.message, color: 'red' })
  } finally {
    pending.value = false
  }
}

async function disable2FA() {
  pending.value = true
  try {
    await authClient.twoFactor.disable({ password: password.value })
    toast.add({ title: '2FA disabled', color: 'green' })
    password.value = ''
    await authClient.getSession({ query: { disableCookieCache: true } })
  } catch (error: unknown) {
    const err = error as { message?: string }
    toast.add({ title: 'Could not disable', description: err?.message, color: 'red' })
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <div class="max-w-lg space-y-6">
    <PageHeader title="Account Security" />

    <Card>
      <template #header>Change password</template>
      <div class="space-y-4">
        <FormField label="Current password">
          <Input v-model="pwForm.current" type="password" placeholder="••••••••" />
        </FormField>
        <FormField label="New password">
          <Input v-model="pwForm.next" type="password" placeholder="••••••••" />
        </FormField>
        <Button :loading="pwPending" @click="changePassword">Change password</Button>
      </div>
    </Card>

    <Card>
      <template #header>Two-factor authentication (TOTP)</template>
      <div class="space-y-4">
        <p class="text-sm">
          Status: <span :class="isEnabled ? 'text-success' : 'text-muted-foreground'">{{ isEnabled ? 'Enabled' : 'Disabled' }}</span>
        </p>

        <template v-if="isEnabled">
          <FormField label="Password" help="Required to disable">
            <Input v-model="password" type="password" placeholder="••••••••" />
          </FormField>
          <Button variant="destructive" :loading="pending" @click="disable2FA">Disable 2FA</Button>
        </template>

        <template v-else-if="step === 'idle'">
          <FormField label="Password" help="Required to generate a new TOTP secret">
            <Input v-model="password" type="password" placeholder="••••••••" />
          </FormField>
          <Button :loading="pending" @click="startEnroll">Enable 2FA</Button>
        </template>

        <template v-else-if="step === 'verify'">
          <div class="space-y-2">
            <p class="text-sm text-muted-foreground">
              Add this key manually to your authenticator app (Google Authenticator, Authy, etc. — no QR generator here):
            </p>
            <code class="block break-all rounded bg-muted p-2 text-xs">{{ totpSecret }}</code>
          </div>
          <FormField label="Code from app">
            <Input v-model="verifyCode" placeholder="000000" maxlength="6" />
          </FormField>
          <Button :loading="pending" @click="confirmEnroll">Confirm</Button>

          <div v-if="backupCodes.length" class="space-y-1 pt-2 border-t border-border">
            <p class="text-sm font-medium">Backup codes — save them now, they won't be shown again</p>
            <code class="block rounded bg-muted p-2 text-xs whitespace-pre-wrap">{{ backupCodes.join('\n') }}</code>
          </div>
        </template>
      </div>
    </Card>
  </div>
</template>
