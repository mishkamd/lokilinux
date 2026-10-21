<script setup lang="ts">
import { WORKFLOW_TABS } from '~/utils/nav'

// Parent route for the automation area. Runbooks are the incident-response
// half of it — they were a separate top-level entry before, which split one
// product across two menu items.
const tabs = WORKFLOW_TABS

const route = useRoute()
const showTabs = computed(() => tabs.some((t) => t.to === route.path))

</script>

<template>
  <div>
    <TabNav v-if="showTabs" :tabs="tabs" />
    <NuxtPage />
  </div>
</template>
