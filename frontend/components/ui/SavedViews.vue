<script setup lang="ts">
const props = defineProps<{ scope: string }>()

const route = useRoute()
const router = useRouter()
const { views, save, remove } = useSavedViews(props.scope)

const naming = ref(false)
const name = ref('')
const inputEl = ref<HTMLInputElement | null>(null)

watch(naming, async (v) => {
  if (!v) return
  await nextTick()
  inputEl.value?.focus()
})

const currentQuery = computed(() => {
  const query: Record<string, string> = {}
  for (const [k, v] of Object.entries(route.query)) {
    if (typeof v === 'string') query[k] = v
  }
  return query
})

function confirm() {
  if (!name.value.trim()) {
    naming.value = false
    return
  }
  save(name.value, route.path, currentQuery.value)
  name.value = ''
  naming.value = false
}

async function apply(viewName: string) {
  const view = views.value.find((v) => v.name === viewName)
  if (!view) return
  await router.push({ path: view.path, query: view.query })
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-1.5">
    <span class="label-caps text-muted-foreground">Views</span>

    <button
      v-for="view in views"
      :key="view.name"
      type="button"
      class="focus-ring group inline-flex items-center gap-1 rounded-full border border-border px-2.5 py-0.5 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
      @click="apply(view.name)"
    >
      {{ view.name }}
      <span
        role="button"
        tabindex="0"
        class="focus-ring rounded-full opacity-0 transition-opacity group-hover:opacity-60 hover:!opacity-100"
        aria-label="Delete view"
        @click.stop="remove(view.name)"
        @keyup.enter.stop="remove(view.name)"
      >×</span>
    </button>

    <template v-if="naming">
      <input
        ref="inputEl"
        v-model="name"
        type="text"
        placeholder="View name"
        class="h-6 w-32 rounded-md border border-border bg-card px-2 text-xs outline-none focus:ring-2 focus:ring-ring"
        @keyup.enter="confirm"
        @keyup.esc="naming = false"
      >
      <button type="button" class="text-xs text-primary hover:underline" @click="confirm">Save</button>
    </template>
    <button
      v-else
      type="button"
      class="focus-ring rounded-full border border-dashed border-border px-2.5 py-0.5 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
      @click="naming = true"
    >
      + Save view
    </button>
  </div>
</template>
