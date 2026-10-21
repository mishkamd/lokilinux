type Filters = Record<string, string>

/**
 * Merge filter values into a query object: non-empty filters are written,
 * empty ones dropped, and unrelated query keys (?tab=, ?action=) preserved.
 */
export function buildFilterQuery(
  filters: Filters,
  keys: string[],
  current: Record<string, unknown>,
): Record<string, string> {
  const query: Record<string, string> = {}
  for (const [k, v] of Object.entries(current)) {
    if (!keys.includes(k) && v !== undefined && v !== null) query[k] = String(v)
  }
  for (const k of keys) {
    const v = filters[k]
    if (v) query[k] = v
  }
  return query
}

function sameQuery(a: Record<string, string>, b: Record<string, unknown>): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)])
  for (const k of keys) {
    if ((a[k] ?? '') !== (b[k] ? String(b[k]) : '')) return false
  }
  return true
}

/**
 * Two-way binding between a filter object and the URL query.
 *
 * Filter state lives in the URL, so a list is shareable, bookmarkable and
 * linkable from an incident or a runbook. The object is mutated in place —
 * pass the store's own filter object and it keeps working.
 */
export function useUrlFilters<T extends Filters>(target: T, defaults: T = { ...target }): T {
  const route = useRoute()
  const router = useRouter()
  const keys = Object.keys(defaults)

  function hydrate() {
    const mutable = target as Filters
    for (const k of keys) {
      const raw = route.query[k]
      const next = (typeof raw === 'string' ? raw : defaults[k]) ?? ''
      if (mutable[k] !== next) mutable[k] = next
    }
  }

  hydrate()

  watch(
    target,
    () => {
      const query = buildFilterQuery(target, keys, route.query)
      if (sameQuery(query, route.query)) return
      router.replace({ query })
    },
    { deep: true },
  )

  // Another source (palette, saved view, deep link) changed the query.
  watch(
    () => route.query,
    () => hydrate(),
  )

  return target
}
