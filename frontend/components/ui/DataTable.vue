<script setup lang="ts" generic="T extends object">
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight } from 'lucide-vue-next'

const props = withDefaults(
  defineProps<{
    rows: T[]
    columns: { key: string; label: string; noSort?: boolean }[]
    loading?: boolean
    rowsClickable?: boolean
    selectable?: boolean
    selected?: (string | number)[]
    rowKey?: string
    /** Client-side pagination; omit to render all rows */
    pageSize?: number
    /** Enable click-to-sort headers on every column that doesn't set noSort */
    sortable?: boolean
    skeletonRows?: number
    emptyTitle?: string
    emptyDescription?: string
  }>(),
  { skeletonRows: 5 },
)

const emit = defineEmits<{
  'row-click': [T]
  'update:selected': [(string | number)[]]
}>()

const slots = useSlots()

const keyField = computed(() => props.rowKey ?? 'id')
const selectedSet = computed(() => new Set(props.selected ?? []))
const allSelected = computed(() =>
  displayedRows.value.length > 0 &&
  displayedRows.value.every((row) => selectedSet.value.has(val(row, keyField.value) as string | number)),
)

function val(row: T, key: string): unknown {
  return (row as Record<string, unknown>)[key]
}

function toggleAll(checked: boolean) {
  emit(
    'update:selected',
    checked
      ? displayedRows.value.map((row) => val(row, keyField.value) as string | number)
      : [],
  )
}

function toggleRow(row: T, checked: boolean) {
  const key = val(row, keyField.value) as string | number
  const next = new Set(selectedSet.value)
  if (checked) next.add(key)
  else next.delete(key)
  emit('update:selected', [...next])
}

// --- Sorting ---------------------------------------------------------------

type SortDir = 'asc' | 'desc'
const sortKey = ref('')
const sortDir = ref<SortDir>('asc')

function isSortable(col: { key: string; noSort?: boolean }) {
  return props.sortable === true && !col.noSort
}

function compareValues(a: unknown, b: unknown): number {
  if (a == null && b == null) return 0
  if (a == null) return 1
  if (b == null) return -1
  if (typeof a === 'number' && typeof b === 'number') return a - b
  if (typeof a === 'boolean' && typeof b === 'boolean') return Number(a) - Number(b)
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' })
}

const sortedRows = computed(() => {
  if (!sortKey.value) return props.rows
  const key = sortKey.value
  const dir = sortDir.value === 'asc' ? 1 : -1
  return [...props.rows].sort((a, b) => compareValues(val(a, key), val(b, key)) * dir)
})

function toggleSort(col: { key: string }) {
  if (sortKey.value === col.key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = col.key
    sortDir.value = 'asc'
  }
  page.value = 1
}

// --- Pagination ------------------------------------------------------------

const page = ref(1)

watch(
  () => [props.rows.length, props.pageSize] as const,
  () => {
    page.value = 1
  },
)

const totalPages = computed(() =>
  props.pageSize && props.pageSize > 0 ? Math.max(1, Math.ceil(sortedRows.value.length / props.pageSize)) : 1,
)

const displayedRows = computed(() => {
  if (!props.pageSize || props.pageSize <= 0) return sortedRows.value
  const start = (page.value - 1) * props.pageSize
  return sortedRows.value.slice(start, start + props.pageSize)
})

const rangeStart = computed(() =>
  sortedRows.value.length === 0 ? 0 : (page.value - 1) * (props.pageSize ?? 0) + 1,
)
const rangeEnd = computed(() => rangeStart.value + displayedRows.value.length - 1)

// --- Keys ------------------------------------------------------------------

function keyFor(row: T, index: number): string | number {
  const k = val(row, keyField.value)
  return k != null ? (k as string | number) : index
}

function fmt(v: unknown): string {
  return v == null ? '—' : String(v)
}
</script>

<template>
  <div class="rounded-[var(--radius-lg)] border border-border bg-card shadow-[var(--shadow-surface)] overflow-hidden">
    <div v-if="$slots.toolbar" class="border-b border-border px-3 py-2">
      <slot name="toolbar" />
    </div>

    <div class="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead v-if="selectable" class="w-10">
              <Checkbox :model-value="allSelected" @update:model-value="toggleAll" />
            </TableHead>
            <TableHead v-for="col in columns" :key="col.key">
              <button
                v-if="isSortable(col)"
                type="button"
                class="group inline-flex items-center gap-1 uppercase tracking-wide text-muted-foreground transition-colors hover:text-foreground"
                :aria-label="`Sort by ${col.label}`"
                @click="toggleSort(col)"
              >
                {{ col.label }}
                <ArrowUp v-if="sortKey === col.key && sortDir === 'asc'" class="size-3" />
                <ArrowDown v-else-if="sortKey === col.key && sortDir === 'desc'" class="size-3" />
                <ArrowUpDown v-else class="size-3 opacity-30 group-hover:opacity-60" />
              </button>
              <template v-else>{{ col.label }}</template>
            </TableHead>
          </TableRow>
        </TableHeader>

        <TableBody v-if="loading">
          <TableRow v-for="r in skeletonRows" :key="`sk-${r}`" class="hover:bg-transparent">
            <TableCell v-if="selectable">
              <Skeleton class="size-4" />
            </TableCell>
            <TableCell v-for="col in columns" :key="col.key">
              <Skeleton class="h-4 w-full max-w-[140px]" :style="{ opacity: 1 - r * 0.12 }" />
            </TableCell>
          </TableRow>
        </TableBody>

        <TableBody v-else>
          <template v-if="displayedRows.length">
            <TableRow
              v-for="(row, i) in displayedRows"
              :key="keyFor(row, i)"
              :class="rowsClickable ? 'cursor-pointer' : ''"
              :tabindex="rowsClickable ? 0 : undefined"
              @click="rowsClickable && emit('row-click', row)"
              @keydown.enter.prevent="rowsClickable && emit('row-click', row)"
            >
              <TableCell v-if="selectable" @click.stop>
                <Checkbox
                  :model-value="selectedSet.has(val(row, keyField) as string | number)"
                  @update:model-value="(checked) => toggleRow(row, checked)"
                />
              </TableCell>
              <TableCell v-for="col in columns" :key="col.key">
                <template v-if="slots[`${col.key}-data`]">
                  <slot :name="`${col.key}-data`" :row="row" />
                </template>
                <span v-else>{{ fmt(val(row, col.key)) }}</span>
              </TableCell>
            </TableRow>
          </template>
          <TableRow v-else class="hover:bg-transparent">
            <TableCell :colspan="columns.length + (selectable ? 1 : 0)">
              <slot name="empty">
                <div class="flex flex-col items-center gap-1 py-8 text-center">
                  <p class="text-sm font-medium text-foreground">{{ emptyTitle ?? 'No data' }}</p>
                  <p v-if="emptyDescription" class="text-xs text-muted-foreground max-w-sm">{{ emptyDescription }}</p>
                </div>
              </slot>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>

    <div
      v-if="pageSize && pageSize > 0 && sortedRows.length > pageSize"
      class="flex items-center justify-between border-t border-border px-3 py-2 text-xs text-muted-foreground"
    >
      <span>{{ rangeStart }}–{{ rangeEnd }} of {{ sortedRows.length }}</span>
      <div class="flex items-center gap-1">
        <Button size="icon" variant="ghost" class="size-7" :disabled="page <= 1" aria-label="Previous page" @click="page--">
          <ChevronLeft class="size-4" />
        </Button>
        <span class="min-w-16 text-center tabular-nums">{{ page }} / {{ totalPages }}</span>
        <Button
          size="icon"
          variant="ghost"
          class="size-7"
          :disabled="page >= totalPages"
          aria-label="Next page"
          @click="page++"
        >
          <ChevronRight class="size-4" />
        </Button>
      </div>
    </div>
  </div>
</template>
