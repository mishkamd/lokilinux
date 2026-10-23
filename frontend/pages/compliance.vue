<script setup lang="ts">
import { COMPLIANCE_TABS, CONFIGURATION_TABS } from '~/utils/nav'

// Parent route for the compliance area: the sub-pages are nested children,
// so their URLs stay exactly as they were.
//
// Two tab sets, not one: Compliance ("does it satisfy a rule/standard") and
// Configuration ("what should this host look like, and did it drift") are
// separate products with separate vocabularies (utils/nav.ts). Previously
// the Configuration pages simply had no tab bar at all, which left an
// operator who landed on /compliance/drift unable to reach its neighbours
// without going back through the sidebar.
const route = useRoute()

const isConfigurationPage = computed(() =>
  CONFIGURATION_TABS.some((t) => route.path === t.to || route.path.startsWith(`${t.to}/`)),
)

const tabs = computed(() => (isConfigurationPage.value ? CONFIGURATION_TABS : COMPLIANCE_TABS))
</script>

<template>
  <div>
    <TabNav :tabs="tabs" />
    <NuxtPage />
  </div>
</template>
