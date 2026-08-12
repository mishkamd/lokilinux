<script setup lang="ts">
import { FileText, ShieldCheck, ShieldAlert } from 'lucide-vue-next'

const store = useComplianceStore()
const { baselines, baselinesTotal, baselinesLoading, topViolations, topViolationsLoading, topChangedFiles, topChangedFilesLoading } = storeToRefs(store)

onMounted(() => {
  store.fetchBaselines()
  store.fetchTopViolations()
  store.fetchTopChangedFiles()
})

const enabledCount = computed(
  () => baselines.value.filter((b) => b.is_enabled).length,
)

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'red', HIGH: 'red', MEDIUM: 'amber', LOW: 'gray',
}

const SEVERITY_RANK: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }

const sortedDrift = computed(() =>
  [...topViolations.value.recent_drift].sort(
    (a, b) => (SEVERITY_RANK[String(a.severity)] ?? 9) - (SEVERITY_RANK[String(b.severity)] ?? 9),
  ),
)
</script>

<template>
  <div>
    <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
      <StatCard
        :icon="ShieldCheck"
        label="Baselines"
        :value="baselinesTotal"
        to="/compliance/baselines"
        view-all-label="View"
      />
      <StatCard
        :icon="FileText"
        label="Enabled"
        :value="enabledCount"
        subtitle="baselines on this page"
        to="/compliance/baselines"
        view-all-label="View"
      />
      <StatCard
        :icon="ShieldAlert"
        label="Open drift"
        :value="topViolations.recent_drift.length"
        subtitle="worst events, last 7 days"
        to="/compliance/drift"
        view-all-label="View"
      />
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
      <Card>
        <template #header>
          <div class="flex items-center justify-between">
            <p class="label-caps">Top violations</p>
            <Button variant="ghost" size="xs" to="/compliance/drift">View all</Button>
          </div>
        </template>
        <Skeleton v-if="topViolationsLoading" class="h-24 w-full" />
        <div v-else-if="topViolations.top_rules.length === 0 && sortedDrift.length === 0"
             class="text-sm text-muted-foreground py-6 text-center">
          No violations yet — publish a baseline and import policy rules to start scoring.
        </div>
        <template v-else>
          <ul v-if="topViolations.top_rules.length" class="divide-y divide-border">
            <li v-for="r in topViolations.top_rules.slice(0, 5)" :key="r.rule_id" class="py-2 flex items-center justify-between gap-2">
              <div class="min-w-0">
                <p class="text-sm font-medium truncate" :title="r.title">{{ r.title }}</p>
                <p class="text-xs text-muted-foreground font-mono truncate">{{ r.rule_key }} · {{ r.domain }}</p>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <Badge :color="SEVERITY_COLORS[r.severity] ?? 'gray'" size="xs">{{ r.severity }}</Badge>
                <Badge color="gray" size="xs">{{ r.fail_count }}×</Badge>
              </div>
            </li>
          </ul>
          <ul v-if="sortedDrift.length" class="divide-y divide-border mt-2">
            <li v-for="d in sortedDrift.slice(0, 5)" :key="String(d.id)" class="py-2 flex items-center justify-between gap-2">
              <div class="min-w-0">
                <p class="text-sm font-medium truncate">{{ d.summary }}</p>
                <p class="text-xs text-muted-foreground font-mono truncate">
                  {{ new Date(String(d.time)).toLocaleString() }} · {{ d.domain }} · {{ d.compared_against }}
                </p>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <Badge :color="SEVERITY_COLORS[String(d.severity)] ?? 'gray'" size="xs">{{ d.severity }}</Badge>
                <Button variant="ghost" size="xs" @click="navigateTo(`/compliance/drift/${d.id}`)">View</Button>
              </div>
            </li>
          </ul>
        </template>
      </Card>

      <Card>
        <template #header>
          <div class="flex items-center justify-between">
            <p class="label-caps">Top changed files</p>
            <Button variant="ghost" size="xs" to="/compliance/file-integrity">View all</Button>
          </div>
        </template>
        <Skeleton v-if="topChangedFilesLoading" class="h-24 w-full" />
        <p v-else-if="topChangedFiles.length === 0" class="text-sm text-muted-foreground py-6 text-center">
          No file changes tracked yet (7-day window).
        </p>
        <ul v-else class="divide-y divide-border">
          <li v-for="f in topChangedFiles.slice(0, 8)" :key="f.path" class="py-2 flex items-center justify-between gap-2">
            <p class="text-sm font-mono truncate" :title="f.path">{{ f.path }}</p>
            <Badge color="gray" size="xs">{{ f.change_count }}×</Badge>
          </li>
        </ul>
      </Card>
    </div>

    <Card>
      <template #header>
        <div class="flex items-center justify-between">
          <p class="label-caps">Recent baselines</p>
          <Button variant="ghost" size="xs" to="/compliance/baselines">View all</Button>
        </div>
      </template>
      <Skeleton v-if="baselinesLoading" class="h-24 w-full" />
      <p v-else-if="baselines.length === 0" class="text-sm text-muted-foreground py-4 text-center">
        No baselines yet. <NuxtLink to="/compliance/baselines" class="text-primary hover:underline">Create one</NuxtLink>.
      </p>
      <ul v-else class="divide-y divide-border">
        <li v-for="b in baselines.slice(0, 5)" :key="b.id" class="py-2.5 flex items-center justify-between">
          <div>
            <NuxtLink :to="`/compliance/baselines/${b.id}`" class="text-sm font-medium hover:underline">{{ b.name }}</NuxtLink>
            <p class="text-xs text-muted-foreground font-mono">{{ b.scope_type }}</p>
          </div>
          <Badge v-if="b.is_enabled" color="green" size="xs">Enabled</Badge>
          <Badge v-else color="gray" size="xs">Disabled</Badge>
        </li>
      </ul>
    </Card>
  </div>
</template>
