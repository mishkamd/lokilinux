<script setup lang="ts">
import { SEVERITY_COLORS, CHECK_SOURCE_COLORS, RULE_STATUS_COLORS } from '~/utils/complianceColors'
import type { CheckSource } from '~/stores/compliance'

const route = useRoute()
const store = useComplianceStore()
const { selectedRule } = storeToRefs(store)

const loading = ref(true)
const loadError = ref<string | null>(null)

async function load() {
  loading.value = true
  loadError.value = null
  try {
    await store.fetchRule(String(route.params.id))
  } catch (err) {
    loadError.value = (err as { data?: { detail?: string } })?.data?.detail ?? 'Failed to load rule'
  } finally {
    loading.value = false
  }
}
onMounted(load)

const COVERAGE_COLORS: Record<string, string> = {
  PASS: 'green', FAIL: 'red', NOT_APPLICABLE: 'gray', ERROR: 'red', NOT_EVALUATED: 'gray',
}

const coverageEntries = computed(() => Object.entries(selectedRule.value?.coverage ?? {}).filter(([, n]) => n > 0))
</script>

<template>
  <div>
    <div v-if="loading" class="space-y-4">
      <Skeleton class="h-8 w-64" />
      <Skeleton class="h-4 w-48" />
      <Skeleton class="h-64 w-full" />
    </div>

    <div v-else-if="loadError">
      <Alert color="red" class="mb-4">{{ loadError }}</Alert>
      <Button variant="outline" @click="load">Retry</Button>
    </div>

    <div v-else-if="selectedRule">
      <PageHeader
        :title="selectedRule.title"
        :description="`${selectedRule.rule_key} · ${selectedRule.domain}`"
        :back="{ to: '/compliance/rules', label: 'Back to rules' }"
      >
        <template #badges>
          <Badge :color="SEVERITY_COLORS[selectedRule.severity] ?? 'gray'">{{ selectedRule.severity }}</Badge>
          <Badge :color="CHECK_SOURCE_COLORS[selectedRule.check_source] ?? 'gray'">{{ selectedRule.check_source }}</Badge>
          <Badge :color="selectedRule.status === 'ACTIVE' ? 'green' : (RULE_STATUS_COLORS[selectedRule.status] ?? 'gray')">{{ selectedRule.status }}</Badge>
        </template>
      </PageHeader>

      <p v-if="selectedRule.check_source !== 'CEL'" class="text-sm text-muted-foreground mb-4">
        Imported as reference catalog — not executable. This rule never runs, never scores,
        and never counts toward coverage until a CEL check is hand-mapped to it.
      </p>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
        <Card>
          <template #header><p class="label-caps">Description</p></template>
          <p v-if="selectedRule.description" class="text-sm whitespace-pre-wrap">{{ selectedRule.description }}</p>
          <p v-else class="text-sm text-muted-foreground">No description.</p>
        </Card>
        <Card>
          <template #header><p class="label-caps">Rationale</p></template>
          <p v-if="selectedRule.rationale" class="text-sm whitespace-pre-wrap">{{ selectedRule.rationale }}</p>
          <p v-else class="text-sm text-muted-foreground">No rationale.</p>
        </Card>
      </div>

      <Card class="mb-4">
        <template #header><p class="label-caps">Applicability &amp; check</p></template>
        <dl class="grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt class="text-muted-foreground">Platforms</dt>
            <dd v-if="selectedRule.platform_filter?.length" class="flex flex-wrap gap-1 mt-1">
              <Badge v-for="p in selectedRule.platform_filter" :key="p" color="gray" size="xs">{{ p }}</Badge>
            </dd>
            <dd v-else class="text-muted-foreground">Every platform</dd>
          </div>
          <div>
            <dt class="text-muted-foreground">Source</dt>
            <dd class="font-mono">{{ selectedRule.source }} <span v-if="selectedRule.source_version">· {{ selectedRule.source_version }}</span></dd>
          </div>
        </dl>
        <div v-if="selectedRule.check_expr" class="mt-3">
          <p class="text-xs text-muted-foreground mb-1">Check expression (CEL)</p>
          <pre class="font-mono text-xs whitespace-pre-wrap rounded-lg border p-2 bg-muted/30">{{ selectedRule.check_expr }}</pre>
        </div>
        <div v-if="selectedRule.expected_value" class="mt-3">
          <p class="text-xs text-muted-foreground mb-1">Expected value</p>
          <pre class="font-mono text-xs whitespace-pre-wrap rounded-lg border p-2 bg-muted/30">{{ JSON.stringify(selectedRule.expected_value, null, 2) }}</pre>
        </div>
      </Card>

      <Card class="mb-4">
        <template #header><p class="label-caps">Framework mappings</p></template>
        <EmptyState v-if="selectedRule.framework_mappings.length === 0">
          No framework mappings recorded.
        </EmptyState>
        <ul v-else class="divide-y divide-border">
          <li v-for="m in selectedRule.framework_mappings" :key="`${m.framework_key}-${m.control_id}`" class="py-2 flex items-center justify-between gap-2">
            <div class="min-w-0">
              <p class="text-sm font-medium">{{ m.framework_name }} <span class="text-muted-foreground font-mono text-xs">{{ m.framework_version }}</span></p>
              <p class="text-xs text-muted-foreground truncate">{{ m.control_title }}</p>
            </div>
            <Badge color="gray" size="xs" class="font-mono shrink-0">{{ m.control_id }}</Badge>
          </li>
        </ul>
      </Card>

      <Card class="mb-4">
        <template #header><p class="label-caps">Coverage</p></template>
        <EmptyState v-if="coverageEntries.length === 0">
          Not evaluated on any server yet.
        </EmptyState>
        <div v-else class="flex flex-wrap gap-2">
          <Badge v-for="[result, n] in coverageEntries" :key="result" :color="COVERAGE_COLORS[result] ?? 'gray'">
            {{ result }}: {{ n }}
          </Badge>
        </div>
        <div v-if="selectedRule.failing_agents.length" class="mt-3">
          <p class="text-xs text-muted-foreground mb-1">Failing servers ({{ selectedRule.failing_agents.length }})</p>
          <div class="flex flex-wrap gap-1">
            <NuxtLink
              v-for="fa in selectedRule.failing_agents.slice(0, 20)" :key="fa.agent_id"
              :to="`/servers/${fa.agent_id}`" class="font-mono text-xs text-primary hover:underline"
            >
              {{ fa.hostname || fa.agent_id.slice(0, 8) + '…' }}
            </NuxtLink>
          </div>
        </div>
      </Card>
    </div>
  </div>
</template>
