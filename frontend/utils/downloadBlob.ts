/**
 * Triggers a browser download for an already-fetched Blob via a throwaway
 * anchor element. Extracted from three call sites that hand-rolled this
 * identically (compliance reports, vulnerability export, agent packages).
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
