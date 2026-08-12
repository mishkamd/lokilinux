import { createAuthClient } from "better-auth/vue"
import { twoFactorClient, usernameClient } from "better-auth/client/plugins"

type Role = 'ADMIN' | 'OPERATOR' | 'VIEWER' | 'AUDITOR'

const authClient = createAuthClient({
  plugins: [twoFactorClient(), usernameClient()],
})

export function useAuth() {
  return authClient
}

export async function refreshAuthToken(): Promise<string | null> {
  if (import.meta.server) return null
  const session = await authClient.getSession()
  // Better Auth bearer plugin exposes session.token for Bearer auth
  const token = (session.data as { session?: { token?: string } } | null)?.session?.token ?? null
  useState<string | null>('auth:token').value = token
  return token
}

interface AuthSession {
  session: { token?: string; [key: string]: unknown }
  user: { name?: string; username?: string; email?: string; role?: string; [key: string]: unknown }
}

export function useCurrentUser() {
  // authClient.useSession() (Better Auth's Vue client, nanostores-based) never
  // resolves during SSR (refreshAuthToken() above explicitly skips it there) —
  // the server render always fell back to a placeholder while the client
  // resolved the real user moments later, causing a hydration mismatch on
  // every authenticated page. useAsyncData mirrors useApi()'s onRequest
  // hook (utils/api.ts): resolve the session server-side via the same
  // request-scoped getSession(event) used for Bearer-token auth, so the
  // value baked into the SSR payload matches what the client hydrates with.
  const { data, status } = useAsyncData<AuthSession | null>('current-user', async () => {
    if (import.meta.server) {
      const event = useRequestEvent()
      if (!event) return null
      const { getSession } = await import('../server/utils/session')
      return (await getSession(event)) as AuthSession | null
    }
    const res = await authClient.getSession()
    return (res.data as AuthSession | null) ?? null
  })

  const user = computed(() => data.value?.user ?? null)
  const isAuthenticated = computed(() => !!data.value?.user)
  const isPending = computed(() => status.value === 'pending')

  function hasRole(role: Role): boolean {
    // Better Auth stores role lowercase ('admin', 'user'); backend RBAC uses
    // uppercase ('ADMIN', 'OPERATOR', ...) — normalize before comparing.
    const userRole = (user.value as Record<string, unknown> | null)?.role as string | undefined
    const normalized = userRole?.toUpperCase()
    return normalized === 'ADMIN' || normalized === role
  }

  const canEdit = computed(() => hasRole('ADMIN') || hasRole('OPERATOR'))
  const isAdmin = computed(() => hasRole('ADMIN'))

  return { user, isAuthenticated, isPending, hasRole, canEdit, isAdmin }
}
