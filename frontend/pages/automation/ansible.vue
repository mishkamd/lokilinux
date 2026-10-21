<script setup lang="ts">
import { ANSIBLE_TABS } from '~/utils/nav'

// Parent route for the Ansible area — one sidebar entry, four tabs.
const tabs = ANSIBLE_TABS

const route = useRoute()
const showTabs = computed(() => tabs.some((t) => t.to === route.path))

</script>

<template>
  <div>
    <TabNav v-if="showTabs" :tabs="tabs" />
    <NuxtPage />
  </div>
</template>
