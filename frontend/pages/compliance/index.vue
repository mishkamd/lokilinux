<script setup lang="ts">
import { ShieldCheck, FileText } from 'lucide-vue-next'

const store = useComplianceStore()
const { baselines, baselinesTotal, baselinesLoading } = storeToRefs(store)

onMounted(() => store.fetchBaselines())

const enabledCount = computed(
  () => baselines.value.filter((b) => b.is_enabled).length,
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
        subtitle="on the current page"
        to="/compliance/baselines"
        view-all-label="View"
      />
      <Card>
        <p class="label-caps mb-1">Module status</p>
        <p class="text-sm text-muted-foreground">
          Phase 1: Baseline Manager + Inventory Collector. Drift detection, policy scoring,
          and remediation land in later phases — see
          <code class="font-mono text-xs">docs/compliance/13-OPS.md</code> for the roadmap.
        </p>
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
