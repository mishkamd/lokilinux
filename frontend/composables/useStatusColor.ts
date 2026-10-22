/**
 * Canonical status → badge colour map, shared by every Observe surface
 * (alerts, signals, incidents, correlation).
 *
 * Before this, four pages each carried their own copy of the same map and
 * they disagreed: an ACKNOWLEDGED alert rendered gray while an
 * ACKNOWLEDGED incident rendered amber. Severity already had a single
 * source of truth (`useSeverity`); status now has one too.
 *
 * The vocabulary is deliberately shared: "needs a human" is red, "a human
 * has it" is amber, "work in progress" is blue, "done" is green, and
 * "no longer relevant" is gray.
 */
const STATUS_COLOR: Record<string, string> = {
  // Needs attention.
  ACTIVE: 'red',
  OPEN: 'red',
  // A human owns it.
  ACKNOWLEDGED: 'amber',
  // Being worked.
  IN_PROGRESS: 'blue',
  // Done.
  RESOLVED: 'green',
  // Closed out / irrelevant.
  CLOSED: 'gray',
  EXPIRED: 'gray',
  SUPPRESSED: 'gray',
}

export function useStatusColor() {
  function statusColor(status: string): string {
    return STATUS_COLOR[status] ?? 'gray'
  }
  return { statusColor }
}
