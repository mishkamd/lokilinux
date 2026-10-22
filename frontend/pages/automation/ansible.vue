<script setup lang="ts">
import { ANSIBLE_TABS } from '~/utils/nav'

// Parent route for the Ansible area — one sidebar entry, four tabs.
const tabs = ANSIBLE_TABS

const route = useRoute()
const showTabs = computed(() => tabs.some((t) => t.to === route.path))

// The area shell has no index child (the tabs live one level deeper), so
// landing on the bare area URL would render an empty page. Send it to the
// first tab instead — a 302 on the server, so a bookmark never flashes an
// empty screen.
if (!showTabs.value) await navigateTo(tabs[0]!.to, { replace: true })
</script>

<template>
  <div>
    <TabNav v-if="showTabs" :tabs="tabs" />
    <NuxtPage />
  </div>
</template>
