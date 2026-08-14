import type { FetchOptions } from 'ofetch'

export interface ApiInstance {
  get<T>(path: string, opts?: FetchOptions<'json'>): Promise<T>
  post<T>(path: string, body?: unknown, opts?: FetchOptions<'json'>): Promise<T>
  put<T>(path: string, body?: unknown, opts?: FetchOptions<'json'>): Promise<T>
  patch<T>(path: string, body?: unknown, opts?: FetchOptions<'json'>): Promise<T>
  del<T>(path: string, opts?: FetchOptions<'json'>): Promise<T>
}

/** Simplified fetch signature — strips Nuxt's route-typed overloads that
 *  cause excessive-complexity errors with TS 6. The typed route info is
 *  only useful inside auto-generated server code; callers go through
 *  ApiInstance which already erases it. */
type SimpleFetch = <T>(path: string, opts?: FetchOptions<'json'>) => Promise<T>

export function useApi(): ApiInstance {
  const config = useRuntimeConfig()
  const token = useState<string | null>('auth:token')

  // SSR calls the API container directly (internal network); the browser calls
  // the same-origin proxy route (/api/v1/**), so one public URL fronts everything.
  const baseURL = import.meta.server
    ? (config.apiInternal as string)
    : config.public.apiBase

  const apiFetch = $fetch.create({
    baseURL,
    async onRequest({ options }) {
      let bearer = token.value
      if (!bearer && import.meta.server) {
        const event = useRequestEvent()
        if (event) {
          const { getSession } = await import('../server/utils/session')
          const session = await getSession(event)
          bearer = (session as { session?: { token?: string } } | null)?.session?.token ?? null
        }
      }
      if (bearer) {
        const headers = new Headers(options.headers)
        headers.set('Authorization', `Bearer ${bearer}`)
        options.headers = headers
      }
    },
    onResponseError({ response }): void {
      if (response.status === 401) {
        if (import.meta.client) navigateTo('/auth/login')
        return
      }
      if (response.status >= 500) {
        useToast().add({
          title: 'Server error',
          description: 'Something went wrong. Please try again.',
          color: 'red',
        })
      }
    },
  }) as unknown as SimpleFetch

  return {
    get: <T>(path: string, opts?: FetchOptions<'json'>) =>
      apiFetch<T>(path, { method: 'GET', ...opts }) as unknown as Promise<T>,

    post: <T>(path: string, body?: unknown, opts?: FetchOptions<'json'>) =>
      apiFetch<T>(path, {
        method: 'POST',
        body: body as BodyInit | Record<string, unknown> | null,
        ...opts,
      }) as unknown as Promise<T>,

    put: <T>(path: string, body?: unknown, opts?: FetchOptions<'json'>) =>
      apiFetch<T>(path, {
        method: 'PUT',
        body: body as BodyInit | Record<string, unknown> | null,
        ...opts,
      }) as unknown as Promise<T>,

    patch: <T>(path: string, body?: unknown, opts?: FetchOptions<'json'>) =>
      apiFetch<T>(path, {
        method: 'PATCH',
        body: body as BodyInit | Record<string, unknown> | null,
        ...opts,
      }) as unknown as Promise<T>,

    del: <T>(path: string, opts?: FetchOptions<'json'>) =>
      apiFetch<T>(path, { method: 'DELETE', ...opts }) as unknown as Promise<T>,
  }
}
