/**
 * Canonical workflow status → badge colour map.
 *
 * Severity already had one source of truth (`useSeverity`) and the Observe
 * surfaces had another (`useStatusColor`); the workflow module had neither —
 * `WorkflowRunPanel.vue` kept a private `RUN_STATUS_COLOR`, the workflow
 * list and the builder each re-derived "published vs draft" on the spot.
 *
 * The vocabulary is the app-wide one: blue is in flight, amber is waiting on
 * a human, green is done, red needs attention, gray is everything that is
 * not doing anything.
 */
const WORKFLOW_STATUS_COLOR: Record<string, string> = {
  // In flight — `--info` (Recon Blue) is the designated running hue.
  RUNNING: 'blue',
  // Waiting on a human to approve — a human owns it, so amber.
  WAITING_APPROVAL: 'amber',
  // Done.
  SUCCEEDED: 'green',
  PUBLISHED: 'green',
  // Needs attention.
  FAILED: 'red',
  // Not doing anything.
  PENDING: 'gray',
  SKIPPED: 'gray',
  CANCELLED: 'gray',
  DRAFT: 'gray',
  ARCHIVED: 'gray',
}

export function useWorkflowStatus() {
  function workflowStatusColor(status: string): string {
    return WORKFLOW_STATUS_COLOR[status] ?? 'gray'
  }

  return { workflowStatusColor }
}
