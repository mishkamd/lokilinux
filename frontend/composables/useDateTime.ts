const DATE_FMT = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

/**
 * SSR-safe locale formatting: Intl is resolved once at module load and reused,
 * so server and client render identical strings (avoids hydration mismatches
 * from Date.prototype.toLocaleString's locale/timezone resolution).
 */
export function useDateTime() {
  const format = (v: string | number | Date | null | undefined): string => {
    if (v == null) return '—'
    const d = v instanceof Date ? v : new Date(v)
    return Number.isNaN(d.getTime()) ? '—' : DATE_FMT.format(d)
  }
  return { format }
}
