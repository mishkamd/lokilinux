<script setup lang="ts">
import { CHECK_SOURCE_COLORS, SEVERITY_COLORS } from '~/utils/complianceColors'

const route = useRoute()
const key = String(route.params.key)
const version = String(route.params.version)

const store = useComplianceStore()
const { selectedStandard } = storeToRefs(store)

onMounted(() => store.fetchStandard(key, version))
</script>

<template>
  <div v-if="selectedStandard">
    <PageHeader
      :title="selectedStandard.name"
      :description="selectedStandard.description ?? undefined"
      :back="{ to: '/compliance/standards', label: 'Back to standards' }"
    >
      <template #badges>
        <Badge color="gray">{{ selectedStandard.version }}</Badge>
        <Badge v-if="selectedStandard.publisher" color="gray">{{ selectedStandard.publisher }}</Badge>
      </template>
    </PageHeader>

    <div class="space-y-3">
      <Card v-for="control in selectedStandard.controls" :key="control.control_id">
        <div class="flex items-start justify-between gap-3 mb-2">
          <div>
            <p class="font-mono text-xs text-muted-foreground">{{ control.control_id }}</p>
            <p class="text-sm font-medium">{{ control.title }}</p>
          </div>
          <Badge color="gray" size="xs">{{ control.rules.length }} rule{{ control.rules.length === 1 ? '' : 's' }}</Badge>
        </div>

        <EmptyState v-if="control.rules.length === 0" class="py-4">
          No rule mapped to this control yet.
        </EmptyState>
        <ul v-else class="space-y-1.5">
          <li v-for="rule in control.rules" :key="rule.id" class="flex items-center justify-between gap-3 text-sm">
            <NuxtLink :to="`/compliance/rules/${rule.id}`" class="hover:underline truncate">{{ rule.title }}</NuxtLink>
            <div class="flex items-center gap-1.5 shrink-0">
              <Badge :color="SEVERITY_COLORS[rule.severity] ?? 'gray'" size="xs">{{ rule.severity }}</Badge>
              <Badge :color="CHECK_SOURCE_COLORS[rule.check_source] ?? 'gray'" size="xs">{{ rule.check_source }}</Badge>
            </div>
          </li>
        </ul>
      </Card>

      <EmptyState v-if="selectedStandard.controls.length === 0">
        No controls mapped for this standard version.
      </EmptyState>
    </div>
  </div>
  <Skeleton v-else class="h-64 w-full" />
</template>
