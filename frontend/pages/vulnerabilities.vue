<script setup lang="ts">
import { VULNERABILITY_TABS } from '~/utils/nav'

// Parent route for the vulnerability area. The two views are the ones
// CONCEPTS.md defines: Open Exposure (active findings on hosts right now)
// and the CVE Catalog (fleet-independent, all-time).
const tabs = VULNERABILITY_TABS

const route = useRoute()
const showTabs = computed(() => tabs.some((t) => t.to === route.path))

</script>

<template>
  <div>
    <TabNav v-if="showTabs" :tabs="tabs" />
    <NuxtPage />
  </div>
</template>
