import type { FetchOptions } from 'ofetch'

export interface ApiInstance {
  get<T>(path: string, opts?: FetchOptions<'json'>): Promise<T>
  post<T>(path: string, body?: unknown, opts?: FetchOptions<'json'>): Promise<T>
  put<T>(path: string, body?: unknown, opts?: FetchOptions<'json'>): Promise<T>
  patch<T>(path: string, body?: unknown, opts?: FetchOptions<'json'>): Promise<T>
  del<T>(path: string, opts?: FetchOptions<'json'>): Promise<T>
}

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
      // ponytail: auth:token is only populated by the client-only auth plugin,
      // so SSR requests would otherwise go out unauthenticated on every full
      // page load — fetch the session directly from the local Better Auth
      // instance (no HTTP round trip) to get a bearer token for this request.
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
        options.headers = {
          ...(options.headers as Record<string, string> ?? {}),
          Authorization: `Bearer ${bearer}`,
        }
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
  })

  return {
    get: <T>(path: string, opts?: FetchOptions<'json'>) =>
      apiFetch<T>(path, { method: 'GET', ...opts }),

    post: <T>(path: string, body?: unknown, opts?: FetchOptions<'json'>) =>
      apiFetch<T>(path, { method: 'POST', body, ...opts }),

    put: <T>(path: string, body?: unknown, opts?: FetchOptions<'json'>) =>
      apiFetch<T>(path, { method: 'PUT', body, ...opts }),

    patch: <T>(path: string, body?: unknown, opts?: FetchOptions<'json'>) =>
      apiFetch<T>(path, { method: 'PATCH', body, ...opts }),

    del: <T>(path: string, opts?: FetchOptions<'json'>) =>
      apiFetch<T>(path, { method: 'DELETE', ...opts }),
  }
}
