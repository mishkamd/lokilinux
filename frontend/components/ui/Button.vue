<script setup lang="ts">
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '~/utils/cn'

defineOptions({ inheritAttrs: false })

const variants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-lg)] text-sm font-medium transition-all duration-[var(--duration-normal)] ease-[var(--ease-out-expo)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 hover:-translate-y-0.5 active:translate-y-0',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary-hover',
        destructive: 'bg-destructive text-white hover:bg-destructive/90',
        outline: 'border border-border bg-transparent hover:bg-accent hover:text-accent-foreground',
        secondary: 'bg-secondary text-secondary-foreground hover:bg-accent',
        ghost: 'hover:bg-accent hover:text-accent-foreground',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-8 px-3 text-[14px]',
        sm: 'h-7 px-2.5 text-xs',
        lg: 'h-9 px-6',
        icon: 'h-8 w-8',
        xs: 'h-6 px-2 text-xs rounded-[var(--radius-sm)]',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

type BtnVariants = VariantProps<typeof variants>

const props = defineProps<{
  variant?: BtnVariants['variant']
  size?: BtnVariants['size']
  disabled?: boolean
  loading?: boolean
  to?: string
  target?: string
  class?: string
}>()

const attrs = useAttrs()
const cls = computed(() => cn(variants({ variant: props.variant, size: props.size }), props.class))
const restAttrs = computed(() => {
  const { class: _c, ...rest } = attrs as Record<string, unknown>
  return rest
})
</script>

<template>
  <NuxtLink
    v-if="to"
    :to="to"
    :target="target"
    :class="cls"
    v-bind="restAttrs"
  >
    <slot />
  </NuxtLink>
  <button
    v-else
    type="button"
    :disabled="disabled || loading"
    :class="cls"
    v-bind="restAttrs"
  >
    <span
      v-if="loading"
      class="size-4 shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent"
    />
    <slot />
  </button>
</template>
