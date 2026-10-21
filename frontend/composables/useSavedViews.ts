export interface SavedView {
  name: string
  path: string
  query: Record<string, string>
}

const STORAGE_PREFIX = 'lokilinux:views:'

/**
 * Named filter presets, stored per page in localStorage.
 *
 * ponytail: a bookmarked URL already IS a shareable view, so persistence is
 * the only thing missing. localStorage keeps this a frontend-only feature —
 * no migration, no API, no per-user server state. Trade-off: views do not
 * follow the user to another device; the URL is the shareable artifact.
 */
export function useSavedViews(scope: string) {
  const storageKey = STORAGE_PREFIX + scope
  const views = ref<SavedView[]>([])

  function load() {
    try {
      const raw = localStorage.getItem(storageKey)
      views.value = raw ? (JSON.parse(raw) as SavedView[]) : []
    } catch {
      views.value = []
    }
  }

  function persist() {
    try {
      localStorage.setItem(storageKey, JSON.stringify(views.value))
    } catch {
      // Private mode / quota — the view still works for this session.
    }
  }

  onMounted(load)

  function save(name: string, path: string, query: Record<string, string>) {
    const trimmed = name.trim()
    if (!trimmed) return
    views.value = [
      ...views.value.filter((v) => v.name !== trimmed),
      { name: trimmed, path, query },
    ]
    persist()
  }

  function remove(name: string) {
    views.value = views.value.filter((v) => v.name !== name)
    persist()
  }

  return { views, save, remove, reload: load }
}
