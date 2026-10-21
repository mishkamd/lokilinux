<script setup lang="ts">
import { COMPLIANCE_TABS } from '~/utils/nav'

// Parent route for the compliance area: the eight sub-pages are nested
// children, so their URLs stay exactly as they were and the tab bar replaces
// eight sidebar entries with one.
const tabs = COMPLIANCE_TABS

const route = useRoute()
// Configuration pages (baselines, drift, file integrity) live under
// /compliance/* but are a different product — no tab bar for them.
const showTabs = computed(() => tabs.some((t) => t.to === route.path))

</script>

<template>
  <div>
    <TabNav v-if="showTabs" :tabs="tabs" />
    <NuxtPage />
  </div>
</template>
