<template>
  <div class="min-h-screen flex items-center justify-center px-4 relative overflow-hidden atmosphere">
    <Toaster rich-colors />
    <div class="w-full max-w-md relative">
      <div class="text-center mb-8">
        <div class="flex justify-center mb-4">
          <span class="flex items-center justify-center size-14 rounded-2xl bg-[color-mix(in_oklch,var(--primary-active)_15%,transparent)]">
            <span
              role="img"
              :aria-label="companyName"
              class="size-7 shrink-0 bg-primary-active"
              :style="logoMaskStyle"
            />
          </span>
        </div>
        <h1 class="text-4xl font-display font-semibold text-foreground tracking-tight">{{ companyName }}</h1>
        <p class="text-sm text-muted-foreground mt-1">Enterprise Linux Fleet Management</p>
      </div>
      <Card class="w-full">
        <slot />
      </Card>
      <p class="text-center text-xs text-muted-foreground mt-6">
        {{ companyName }} v1.0 &mdash; Enterprise Fleet Management Platform
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Toaster } from 'vue-sonner'

const { companyName, logoMaskStyle } = useBranding()

useHead({ title: 'Autentificare' })
</script>
