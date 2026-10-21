export interface SavedView {
  id?: string
  name: string
  path: string
  query: Record<string, string>
}

const STORAGE_PREFIX = 'lokilinux:views:'

/**
 * Named filter presets, per page.
 *
 * The server is the source of truth (so a view follows the user to another
 * device); localStorage is the cache and the offline fallback — if the API is
 * unreachable the view still works, it just doesn't sync.
 */
export function useSavedViews(scope: string) {
  const api = useApi()
  const storageKey = STORAGE_PREFIX + scope
  const views = ref<SavedView[]>([])

  function readCache(): SavedView[] {
    try {
      const raw = localStorage.getItem(storageKey)
      return raw ? (JSON.parse(raw) as SavedView[]) : []
    } catch {
      return []
    }
  }

  function writeCache(list: SavedView[]) {
    try {
      localStorage.setItem(storageKey, JSON.stringify(list))
    } catch {
      // private mode / quota — the server copy still holds
    }
  }

  async function load() {
    const cached = readCache()
    views.value = cached
    try {
      const remote = await api.get<SavedView[]>('/account/views', { query: { scope } })
      views.value = remote ?? []
      writeCache(views.value)
    } catch {
      // offline or not migrated yet — the cache is the fallback
    }
  }

  onMounted(load)

  async function save(name: string, path: string, query: Record<string, string>) {
    const trimmed = name.trim()
    if (!trimmed) return
    // Optimistic: the chip shows up immediately, the server confirms.
    views.value = [
      ...views.value.filter((v) => v.name !== trimmed),
      { name: trimmed, path, query },
    ]
    writeCache(views.value)
    try {
      const saved = await api.post<SavedView>('/account/views', {
        scope,
        name: trimmed,
        path,
        query,
      })
      views.value = views.value.map((v) => (v.name === trimmed ? { ...v, id: saved.id } : v))
      writeCache(views.value)
    } catch {
      // stays in the cache; it syncs on the next save
    }
  }

  async function remove(name: string) {
    const target = views.value.find((v) => v.name === name)
    views.value = views.value.filter((v) => v.name !== name)
    writeCache(views.value)
    if (!target?.id) return
    try {
      await api.del(`/account/views/${target.id}`)
    } catch {
      // already gone locally; the server copy may linger until the next sync
    }
  }

  return { views, save, remove, reload: load }
}
