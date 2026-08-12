import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'

const signInMocks = {
  email: vi.fn(),
  username: vi.fn(),
}

const routerMocks = {
  push: vi.fn(),
  replace: vi.fn(),
  afterEach: vi.fn(),
  beforeResolve: vi.fn(),
  beforeEach: vi.fn(),
  currentRoute: { value: { path: '/auth/login' } },
}

const toastMocks = {
  add: vi.fn(),
}

mockNuxtImport('useAuth', () => () => ({
  signIn: signInMocks,
}))

mockNuxtImport('refreshAuthToken', () => vi.fn().mockResolvedValue('tok'))
mockNuxtImport('useRouter', () => () => routerMocks)
mockNuxtImport('useToast', () => () => toastMocks)

import LoginPage from './login.vue'

describe('auth/login.vue — email/username dispatch', () => {
  beforeEach(() => {
    signInMocks.email.mockReset()
    signInMocks.username.mockReset()
    routerMocks.push.mockReset()
    toastMocks.add.mockReset()
  })

  it('calls signIn.email when identifier contains @', async () => {
    signInMocks.email.mockResolvedValue({ data: { session: { token: 'tok' }, user: { email: 'admin@lokilinux.local' } } })

    const wrapper = await mountSuspended(LoginPage)

    await wrapper.find('#identifier').setValue('admin@lokilinux.local')
    await wrapper.find('#password').setValue('password123')
    await wrapper.find('form').trigger('submit')

    await vi.waitFor(() => {
      expect(signInMocks.email).toHaveBeenCalledWith({
        email: 'admin@lokilinux.local',
        password: 'password123',
      })
      expect(signInMocks.username).not.toHaveBeenCalled()
      expect(routerMocks.push).toHaveBeenCalledWith('/')
    })
  })

  it('calls signIn.username when identifier does not contain @', async () => {
    signInMocks.username.mockResolvedValue({ data: { session: { token: 'tok' }, user: { username: 'admin' } } })

    const wrapper = await mountSuspended(LoginPage)

    await wrapper.find('#identifier').setValue('admin')
    await wrapper.find('#password').setValue('password123')
    await wrapper.find('form').trigger('submit')

    await vi.waitFor(() => {
      expect(signInMocks.username).toHaveBeenCalledWith({
        username: 'admin',
        password: 'password123',
      })
      expect(signInMocks.email).not.toHaveBeenCalled()
    })
  })

  it('stays on login page when signIn returns null data (no successful auth)', async () => {
    signInMocks.email.mockResolvedValue({ data: null, error: { message: 'Invalid credentials' } })

    const wrapper = await mountSuspended(LoginPage)

    await wrapper.find('#identifier').setValue('admin@lokilinux.local')
    await wrapper.find('#password').setValue('wrongpass')
    await wrapper.find('form').trigger('submit')

    await vi.waitFor(() => {
      expect(signInMocks.email).toHaveBeenCalledWith({
        email: 'admin@lokilinux.local',
        password: 'wrongpass',
      })
      expect(signInMocks.username).not.toHaveBeenCalled()
    })
  })

  it('does not retry alternate auth method after failed credentials', async () => {
    signInMocks.email.mockRejectedValue(new Error('Unauthorized'))

    const wrapper = await mountSuspended(LoginPage)

    await wrapper.find('#identifier').setValue('admin@lokilinux.local')
    await wrapper.find('#password').setValue('wrongpass')
    await wrapper.find('form').trigger('submit')

    await vi.waitFor(() => {
      expect(signInMocks.email).toHaveBeenCalledTimes(1)
      expect(signInMocks.username).not.toHaveBeenCalled()
    })
  })
})
