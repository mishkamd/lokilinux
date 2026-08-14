<script setup lang="ts">
definePageMeta({ layout: 'auth' })

const { signIn } = useAuth()
const router = useRouter()
const toast = useToast()

const form = reactive({ identifier: '', password: '', code: '' })
const pending = ref(false)
const requires2FA = ref(false)

async function onSubmit() {
  const id = form.identifier.trim()
  if (!id || !form.password) return

  pending.value = true
  try {
    const result = id.includes('@')
      ? await signIn.email({ email: id, password: form.password })
      : await signIn.username({ username: id, password: form.password })

    if (!result.data || result.error) {
      toast.add({ title: 'Autentificare eșuată', description: result.error?.message, color: 'red' })
      return
    }

    await refreshAuthToken()
    await refreshNuxtData('current-user')
    await router.push('/')
  } catch (error: unknown) {
    const err = error as { code?: string; message?: string }
    if (err?.code === '2FA_REQUIRED') {
      requires2FA.value = true
    } else {
      toast.add({ title: 'Autentificare eșuată', description: err?.message, color: 'red' })
    }
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <div class="p-6 space-y-6">
    <div class="text-center">
      <h2 class="text-lg font-semibold tracking-tight">Autentificare</h2>
      <p class="text-sm text-muted-foreground mt-1">Fleet Management Platform</p>
    </div>

    <form class="space-y-4" @submit.prevent="onSubmit">
      <FormField label="Email sau utilizator" name="identifier">
        <Input
          id="identifier"
          v-model="form.identifier"
          placeholder="admin@lokilinux.local"
          autocomplete="username"
        />
      </FormField>

      <FormField label="Parolă" name="password">
        <Input
          id="password"
          v-model="form.password"
          type="password"
          placeholder="••••••••"
          autocomplete="current-password"
        />
      </FormField>

      <FormField v-if="requires2FA" label="Cod 2FA" name="code">
        <Input id="code" v-model="form.code" placeholder="000000" maxlength="6" />
      </FormField>

      <Button type="submit" :loading="pending" class="w-full" size="lg">
        Autentificare
      </Button>
    </form>
  </div>
</template>
