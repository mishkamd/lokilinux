const SEVERITY_COLOR: Record<string, string> = {
  CRITICAL: 'red', HIGH: 'orange', MEDIUM: 'amber', LOW: 'blue', INFO: 'gray',
}

const SEVERITY_LABEL: Record<string, string> = {
  CRITICAL: 'Critical', HIGH: 'High', MEDIUM: 'Medium', LOW: 'Low', INFO: 'Info',
}

export function useSeverity() {
  function severityColor(severity: string): string {
    return SEVERITY_COLOR[severity] ?? 'gray'
  }

  function severityLabel(severity: string): string {
    return SEVERITY_LABEL[severity] ?? severity
  }

  return { severityColor, severityLabel }
}
