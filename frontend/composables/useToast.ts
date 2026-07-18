import { toast } from 'vue-sonner'

export function useToast() {
  return {
    add({ title, description, color }: { title: string; description?: string; color?: string }) {
      const opts = description ? { description } : {}
      if (color === 'red') toast.error(title, opts)
      else if (color === 'green') toast.success(title, opts)
      else if (color === 'yellow') toast.warning(title, opts)
      else toast(title, opts)
    },
  }
}
