/**
 * Global open/close state for the command palette, so any component can
 * trigger it without prop-drilling a dialog through the layout.
 */
export function useCommandPalette() {
  const open = useState<boolean>('command-palette:open', () => false)

  function show() {
    open.value = true
  }

  function hide() {
    open.value = false
  }

  function toggle() {
    open.value = !open.value
  }

  return { open, show, hide, toggle }
}
