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
    toast.add({ title: 'Parolă schimbată', color: 'green' })
    pwForm.current = ''
    pwForm.next = ''
  } catch (error: unknown) {
    const err = error as { message?: string }
    toast.add({ title: 'Nu s-a putut schimba parola', description: err?.message, color: 'red' })
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
    toast.add({ title: 'Nu s-a putut porni înrolarea', description: err?.message, color: 'red' })
  } finally {
    pending.value = false
  }
}

async function confirmEnroll() {
  pending.value = true
  try {
    await authClient.twoFactor.verifyTotp({ code: verifyCode.value })
    toast.add({ title: '2FA activat', color: 'green' })
    step.value = 'idle'
    password.value = ''
    verifyCode.value = ''
    await authClient.getSession({ query: { disableCookieCache: true } })
  } catch (error: unknown) {
    const err = error as { message?: string }
    toast.add({ title: 'Cod invalid', description: err?.message, color: 'red' })
  } finally {
    pending.value = false
  }
}

async function disable2FA() {
  pending.value = true
  try {
    await authClient.twoFactor.disable({ password: password.value })
    toast.add({ title: '2FA dezactivat', color: 'green' })
    password.value = ''
    await authClient.getSession({ query: { disableCookieCache: true } })
  } catch (error: unknown) {
    const err = error as { message?: string }
    toast.add({ title: 'Nu s-a putut dezactiva', description: err?.message, color: 'red' })
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <div class="max-w-lg space-y-6">
    <h2 class="text-lg font-semibold">Securitate cont</h2>

    <Card>
      <template #header>Schimbă parola</template>
      <div class="space-y-4">
        <FormField label="Parolă curentă">
          <Input v-model="pwForm.current" type="password" placeholder="••••••••" />
        </FormField>
        <FormField label="Parolă nouă">
          <Input v-model="pwForm.next" type="password" placeholder="••••••••" />
        </FormField>
        <Button :loading="pwPending" @click="changePassword">Schimbă parola</Button>
      </div>
    </Card>

    <Card>
      <template #header>Autentificare în doi factori (TOTP)</template>
      <div class="space-y-4">
        <p class="text-sm">
          Status: <span :class="isEnabled ? 'text-green-500' : 'text-muted-foreground'">{{ isEnabled ? 'Activat' : 'Dezactivat' }}</span>
        </p>

        <template v-if="isEnabled">
          <FormField label="Parolă" help="Necesară pentru dezactivare">
            <Input v-model="password" type="password" placeholder="••••••••" />
          </FormField>
          <Button variant="destructive" :loading="pending" @click="disable2FA">Dezactivează 2FA</Button>
        </template>

        <template v-else-if="step === 'idle'">
          <FormField label="Parolă" help="Necesară pentru a genera un secret TOTP nou">
            <Input v-model="password" type="password" placeholder="••••••••" />
          </FormField>
          <Button :loading="pending" @click="startEnroll">Activează 2FA</Button>
        </template>

        <template v-else-if="step === 'verify'">
          <div class="space-y-2">
            <p class="text-sm text-muted-foreground">
              Adaugă manual cheia asta în aplicația de autentificare (Google Authenticator, Authy etc — nu avem generator de QR aici):
            </p>
            <code class="block break-all rounded bg-muted p-2 text-xs">{{ totpSecret }}</code>
          </div>
          <FormField label="Cod din aplicație">
            <Input v-model="verifyCode" placeholder="000000" maxlength="6" />
          </FormField>
          <Button :loading="pending" @click="confirmEnroll">Confirmă</Button>

          <div v-if="backupCodes.length" class="space-y-1 pt-2 border-t border-border">
            <p class="text-sm font-medium">Coduri de rezervă — salvează-le acum, nu se mai afișează</p>
            <code class="block rounded bg-muted p-2 text-xs whitespace-pre-wrap">{{ backupCodes.join('\n') }}</code>
          </div>
        </template>
      </div>
    </Card>
  </div>
</template>
