<script setup lang="ts">
import { ServerCog, ArrowRight } from 'lucide-vue-next'
import type { TopVulnerableResource } from '~/stores/vulnerabilities'

const props = defineProps<{ resources: TopVulnerableResource[]; loading?: boolean }>()

const maxTotal = computed(() => Math.max(1, ...props.resources.map(r => r.total)))
</script>

<template>
  <div class="surface-card rounded-[var(--radius-md)] p-3">
    <div class="flex items-center justify-between mb-2.5">
      <div class="flex items-center gap-1.5 text-muted-foreground">
        <span class="flex items-center justify-center size-5 rounded-md bg-[color-mix(in_oklch,var(--destructive)_15%,transparent)] text-destructive shrink-0">
          <ServerCog class="size-3" />
        </span>
        <h2 class="label-caps">Top Vulnerable Servers</h2>
      </div>
      <NuxtLink to="/vulnerabilities" class="flex items-center gap-1 text-[12px] font-medium text-primary shrink-0">
        View All
        <ArrowRight class="size-3" />
      </NuxtLink>
    </div>

    <div v-if="props.loading" class="space-y-3">
      <Skeleton v-for="i in 3" :key="i" class="h-10 rounded-md" />
    </div>
    <div v-else-if="!props.resources.length" class="text-xs text-muted-foreground py-4 text-center">
      No vulnerable servers detected.
    </div>
    <div v-else class="space-y-3">
      <NuxtLink
        v-for="r in props.resources.slice(0, 5)" :key="r.agent_id"
        :to="`/servers/${r.agent_id}`"
        class="block group"
      >
        <div class="flex items-center justify-between text-xs mb-1">
          <span class="font-medium truncate group-hover:text-primary transition-colors">{{ r.hostname ?? r.agent_id }}</span>
          <span class="text-muted-foreground shrink-0">{{ r.total }} vulnerabilities</span>
        </div>
        <Progress :model-value="r.total" :max="maxTotal" class="h-1.5" indicator-class="bg-destructive" />
      </NuxtLink>
    </div>
  </div>
</template>
