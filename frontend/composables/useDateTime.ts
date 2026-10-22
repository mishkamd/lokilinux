const DATE_FMT = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

/**
 * Parse a timestamp for display.
 *
 * A string without a timezone designator is UTC: ClickHouse `DateTime64`
 * columns are naive UTC, and JS would otherwise read them as local time and
 * shift every event by the server's offset. Strings that do carry a zone
 * (Postgres, e.g. `2026-10-21T11:49:19.612000Z`) are left alone.
 */
function toDate(v: string | number | Date): Date {
  if (v instanceof Date) return v
  if (typeof v === 'number') return new Date(v)
  const s = v.trim()
  if (!s) return new Date(NaN)
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(s)
  return new Date(hasZone ? s : `${s}Z`)
}

/**
 * SSR-safe locale formatting: Intl is resolved once at module load and reused,
 * so server and client render identical strings (avoids hydration mismatches
 * from Date.prototype.toLocaleString's locale/timezone resolution).
 */
export function useDateTime() {
  const format = (v: string | number | Date | null | undefined): string => {
    if (v == null) return '—'
    const d = toDate(v)
    return Number.isNaN(d.getTime()) ? '—' : DATE_FMT.format(d)
  }
  return { format }
}
