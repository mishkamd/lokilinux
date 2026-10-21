const KEY = 'lokilinux:recent-routes'

/**
 * The last few routes the user visited — the palette's "recent" list.
 *
 * ponytail: a path list in localStorage, no server, no user profile. It is a
 * shortcut, not a record: losing it (cleared storage, another device) costs
 * nothing but the shortcut.
 */
export function useRecentRoutes(limit = 5) {
  const recent = ref<string[]>([])
  const router = useRouter()

  onMounted(() => {
    try {
      const raw = localStorage.getItem(KEY)
      recent.value = raw ? (JSON.parse(raw) as string[]) : []
    } catch {
      recent.value = []
    }
    router.afterEach((to) => {
      if (!to.path || to.path === '/') return
      const next = [to.path, ...recent.value.filter((p) => p !== to.path)].slice(0, limit)
      recent.value = next
      try {
        localStorage.setItem(KEY, JSON.stringify(next))
      } catch {
        // private mode / quota — the shortcut just doesn't persist
      }
    })
  })

  return { recent }
}
