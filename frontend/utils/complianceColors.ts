// Shared color maps for the compliance module's status badges — one
// definition instead of seven verbatim copies of the severity map.
// Values are Badge `color` props (design tokens, not raw CSS colors).

import type { CheckSource } from '~/stores/compliance'

export const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'red',
  HIGH: 'red',
  MEDIUM: 'amber',
  LOW: 'gray',
}

export const DRIFT_STATUS_COLORS: Record<string, string> = {
  OPEN: 'red',
  ACKNOWLEDGED: 'amber',
  IN_REMEDIATION: 'amber',
  RESOLVED: 'green',
  SUPPRESSED: 'gray',
  EXCEPTION: 'gray',
}

export const CHECK_SOURCE_COLORS: Record<CheckSource, string> = {
  CEL: 'green',
  OVAL_UNMAPPED: 'gray',
  OSCAP_FALLBACK: 'amber',
}
