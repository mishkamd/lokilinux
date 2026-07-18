export default defineNuxtRouteMiddleware((to) => {
  if (import.meta.server) return
  if (to.path.startsWith('/auth/')) return

  const { data: session } = useAuth()
  if (!session.value) {
    return navigateTo('/auth/login')
  }

  // ponytail: soft 2FA enforcement — client-side redirect only, no server-side
  // gate exists yet. A determined API-only client could skip this.
  if (to.path === '/account/security') return
  const { require2FA } = useBranding()
  const { user } = useCurrentUser()
  if (require2FA.value && user.value && !(user.value as Record<string, unknown>).twoFactorEnabled) {
    return navigateTo('/account/security')
  }
})
