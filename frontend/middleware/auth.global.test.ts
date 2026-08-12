import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport } from '@nuxt/test-utils/runtime'

// mockNuxtImport is a macro hoisted above all declarations.
// vi.hoisted() creates values available before the hoist boundary.
const mocks = vi.hoisted(() => ({
  navigateTo: vi.fn(),
  useBranding: vi.fn(() => ({ require2FA: { value: false } })),
  useCurrentUser: vi.fn(() => ({ user: { value: null } })),
  getSession: vi.fn(),
  useSession: vi.fn(() => ({ value: { data: null, isPending: true } })),
}))

mockNuxtImport('navigateTo', () => mocks.navigateTo)
mockNuxtImport('useBranding', () => mocks.useBranding)
mockNuxtImport('useCurrentUser', () => mocks.useCurrentUser)
mockNuxtImport('useAuth', () => () => ({
  getSession: mocks.getSession,
  useSession: mocks.useSession,
}))

describe('middleware/auth.global.ts — session refresh race', () => {
  beforeEach(() => {
    mocks.navigateTo.mockReset()
    mocks.getSession.mockReset()
    mocks.useSession.mockReset()
    mocks.useBranding.mockImplementation(() => ({ require2FA: { value: false } }))
    mocks.useCurrentUser.mockImplementation(() => ({ user: { value: null } }))
  })

  it('does not redirect when getSession() returns authenticated session despite useSession() being null', async () => {
    mocks.useSession.mockReturnValue({ value: { data: null, isPending: true } })
    mocks.getSession.mockResolvedValue({
      data: {
        session: { token: 'session-token' },
        user: { email: 'admin@lokilinux.local', role: 'admin' },
      },
      error: null,
    })

    const { default: middleware } = await import('../middleware/auth.global')

    const mockRoute = { path: '/' }
    const result = await middleware(mockRoute as any, {} as any)

    expect(mocks.navigateTo).not.toHaveBeenCalledWith('/auth/login')
    expect(result).not.toBe('/auth/login')
  })

  it('redirects to /auth/login when getSession() returns null data', async () => {
    mocks.useSession.mockReturnValue({ value: { data: null, isPending: false } })
    mocks.getSession.mockResolvedValue({
      data: null,
      error: { status: 401, message: 'Unauthorized' },
    })

    const { default: middleware } = await import('../middleware/auth.global')

    const mockRoute = { path: '/dashboard' }
    await middleware(mockRoute as any, {} as any)

    expect(mocks.navigateTo).toHaveBeenCalledWith('/auth/login')
  })

  it('redirects to /auth/login when getSession() rejects', async () => {
    mocks.useSession.mockReturnValue({ value: { data: null, isPending: false } })
    mocks.getSession.mockRejectedValue(new Error('Network error'))

    const { default: middleware } = await import('../middleware/auth.global')

    const mockRoute = { path: '/settings' }
    await middleware(mockRoute as any, {} as any)

    expect(mocks.navigateTo).toHaveBeenCalledWith('/auth/login')
  })

  it('allows /auth/ paths without checking session', async () => {
    const { default: middleware } = await import('../middleware/auth.global')

    const mockRoute = { path: '/auth/login' }
    const result = await middleware(mockRoute as any, {} as any)

    expect(mocks.getSession).not.toHaveBeenCalled()
    expect(mocks.navigateTo).not.toHaveBeenCalled()
    expect(result).toBeUndefined()
  })
})
