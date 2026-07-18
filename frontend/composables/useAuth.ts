import { createAuthClient } from "better-auth/vue"
import { twoFactorClient } from "better-auth/client/plugins"

type Role = 'ADMIN' | 'OPERATOR' | 'VIEWER' | 'AUDITOR'

const authClient = createAuthClient({
  plugins: [twoFactorClient()],
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

export function useCurrentUser() {
  // authClient.useSession() returns a Vue ref (nanostores shallowRef) — must
  // read .value here since this runs inside a composable, not a <script setup>
  // top-level binding, so no compiler auto-unwrap applies.
  const session = authClient.useSession()

  const user = computed(() => session.value?.data?.user ?? null)
  const isAuthenticated = computed(() => !!session.value?.data)
  const isPending = computed(() => session.value?.isPending)

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
