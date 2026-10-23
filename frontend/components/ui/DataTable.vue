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
    /** Accessible name for the table — a screen reader announces a table with
     *  no name as an unlabelled grid. */
    caption?: string
    /** Human name of a row — used for the row checkbox's accessible name. */
    rowLabel?: (row: T) => string
    /** Persistence key for the column visibility + density preferences. */
    preferencesKey?: string
    /** Start with these columns hidden (the user can bring them back). */
    hiddenColumns?: string[]
  }>(),
  { skeletonRows: 5 },
)

const emit = defineEmits<{
  'row-click': [T]
  'update:selected': [(string | number)[]]
}>()

const slots = useSlots()

// ── Column visibility + density (per table, persisted locally) ──────────────
const STORAGE_KEY = 'lokilinux:table:'
const hidden = ref<string[]>([])
const density = ref<'compact' | 'comfortable'>('comfortable')

function loadPreferences() {
  if (!props.preferencesKey) return
  try {
    const raw = localStorage.getItem(STORAGE_KEY + props.preferencesKey)
    if (!raw) {
      hidden.value = props.hiddenColumns ?? []
      return
    }
    const parsed = JSON.parse(raw) as { hidden?: string[]; density?: 'compact' | 'comfortable' }
    hidden.value = parsed.hidden ?? props.hiddenColumns ?? []
    density.value = parsed.density ?? 'comfortable'
  } catch {
    hidden.value = props.hiddenColumns ?? []
  }
}

function persistPreferences() {
  if (!props.preferencesKey) return
  try {
    localStorage.setItem(
      STORAGE_KEY + props.preferencesKey,
      JSON.stringify({ hidden: hidden.value, density: density.value }),
    )
  } catch {
    // private mode / quota — the preferences just don't persist
  }
}

onMounted(loadPreferences)

function toggleColumn(key: string) {
  hidden.value = hidden.value.includes(key)
    ? hidden.value.filter((k) => k !== key)
    : [...hidden.value, key]
  persistPreferences()
}

function toggleDensity() {
  density.value = density.value === 'compact' ? 'comfortable' : 'compact'
  persistPreferences()
}

/** The columns actually rendered, in the order the caller declared them. */
const visibleColumns = computed(() =>
  props.columns.filter((c) => !hidden.value.includes(c.key)),
)

const keyField = computed(() => props.rowKey ?? 'id')
const selectedSet = computed(() => new Set(props.selected ?? []))
const allSelected = computed(() =>
  displayedRows.value.length > 0 &&
  displayedRows.value.every((row) => selectedSet.value.has(val(row, keyField.value) as string | number)),
)

function val(row: T, key: string): unknown {
  return (row as Record<string, unknown>)[key]
}

function clearSelection() {
  emit('update:selected', [])
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

function isSortable(col: { key: string; label: string; noSort?: boolean }) {
  // An unlabelled column has nothing to sort by — a bare 13px arrow button
  // with the aria-label "Sort by " is a target nobody can find.
  return props.sortable === true && !col.noSort && !!col.label
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

<!--
  The header cell renders its label through an element, never through a bare
  text interpolation. An empty label (the actions column) made the server
  emit a text node where the client expected a fragment — Vue then reported
  "Hydration completed but contains mismatches" on every table that has one.
-->

<template>
  <div class="rounded-[var(--radius-lg)] border border-border bg-card shadow-[var(--shadow-surface)] overflow-hidden">
    <div
      v-if="$slots.toolbar || $slots.bulk || preferencesKey"
      class="flex items-center gap-2 border-b border-border px-3 py-2"
    >
      <slot name="toolbar" />
      <!-- Bulk actions, shown only while rows are selected -->
      <div v-if="$slots.bulk && selected?.length" class="flex items-center gap-2 border-l border-border pl-2">
        <slot name="bulk" :selected="selected" :clear="clearSelection" />
      </div>
      <div v-if="preferencesKey" class="ml-auto flex items-center gap-1">
        <button
          type="button"
          class="focus-ring rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          :aria-pressed="density === 'compact'"
          @click="toggleDensity"
        >
          {{ density === 'compact' ? 'Comfortable' : 'Compact' }}
        </button>
        <details class="relative">
          <summary
            class="focus-ring cursor-pointer list-none rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            Columns
          </summary>
          <div class="absolute right-0 z-20 mt-1 w-44 rounded-[var(--radius-sm)] border border-border bg-popover p-1 shadow-[var(--shadow-overlay)]">
            <label
              v-for="col in columns"
              :key="col.key"
              class="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1 min-h-6 text-xs text-foreground hover:bg-accent"
            >
              <input
                type="checkbox"
                class="size-4 accent-[var(--primary)]"
                :checked="!hidden.includes(col.key)"
                @change="toggleColumn(col.key)"
              >
              {{ col.label }}
            </label>
          </div>
        </details>
      </div>
    </div>

    <div class="dt-table overflow-x-auto" :class="density === 'compact' ? '[&_td]:py-0.5 [&_th]:h-7' : ''">
      <Table :aria-label="caption">
        <caption v-if="caption" class="sr-only">{{ caption }}</caption>
        <TableHeader>
          <TableRow>
            <TableHead v-if="selectable" class="w-10">
              <Checkbox aria-label="Select all rows" :model-value="allSelected" @update:model-value="toggleAll" />
            </TableHead>
            <TableHead
              v-for="col in visibleColumns"
              :key="col.key"
              :aria-sort="sortKey === col.key ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'"
            >
              <button
                v-if="isSortable(col)"
                type="button"
                class="focus-ring group inline-flex items-center gap-1 rounded-sm uppercase tracking-wide text-muted-foreground transition-colors hover:text-foreground py-1 -my-1"
                :aria-label="`Sort by ${col.label}`"
                @click="toggleSort(col)"
              >
                {{ col.label }}
                <ArrowUp v-if="sortKey === col.key && sortDir === 'asc'" class="size-3" />
                <ArrowDown v-else-if="sortKey === col.key && sortDir === 'desc'" class="size-3" />
                <ArrowUpDown v-else class="size-3 opacity-30 group-hover:opacity-60" />
              </button>
              <span v-else-if="col.label">{{ col.label }}</span>
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
              :class="rowsClickable ? 'focus-ring cursor-pointer' : ''"
              :tabindex="rowsClickable ? 0 : undefined"
              @click="rowsClickable && emit('row-click', row)"
              @keydown.enter.prevent="rowsClickable && emit('row-click', row)"
            >
              <TableCell v-if="selectable" @click.stop>
                <Checkbox
                  :aria-label="`Select ${props.rowLabel ? props.rowLabel(row) : String(val(row, keyField))}`"
                  :model-value="selectedSet.has(val(row, keyField) as string | number)"
                  @update:model-value="(checked) => toggleRow(row, checked)"
                />
              </TableCell>
              <TableCell v-for="col in visibleColumns" :key="col.key" :data-label="col.label">
                <template v-if="slots[`${col.key}-data`]">
                  <slot :name="`${col.key}-data`" :row="row" />
                </template>
                <span v-else>{{ fmt(val(row, col.key)) }}</span>
              </TableCell>
            </TableRow>
          </template>
          <TableRow v-else class="hover:bg-transparent">
            <TableCell :colspan="visibleColumns.length + (selectable ? 1 : 0)">
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

<style scoped>
/* Mobile (MIS-247): the table collapses into a stack of cards. Every cell
 * keeps its value and carries its column label, so a ten-column table stays
 * readable at 390px instead of scrolling sideways. The header row turns into
 * a horizontal strip of sort chips, so sorting survives the collapse. */
@media (max-width: 767.98px) {
  .dt-table :deep(table) {
    display: block;
    width: 100%;
  }
  .dt-table :deep(thead) {
    display: block;
    overflow-x: auto;
    border-bottom: 1px solid var(--border);
  }
  .dt-table :deep(thead tr) {
    display: flex;
    width: max-content;
    gap: 8px;
    padding: 6px 12px;
    border: 0;
  }
  .dt-table :deep(thead th) {
    display: inline-flex;
    align-items: center;
    height: auto;
    padding: 0;
    white-space: nowrap;
  }
  .dt-table :deep(tbody tr) {
    display: block;
    height: auto;
    padding: 6px 0;
    border-bottom: 1px solid var(--border);
  }
  .dt-table :deep(tbody td) {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 4px 12px;
    border: 0;
    overflow-wrap: anywhere;
  }
  .dt-table :deep(tbody td)::before {
    content: attr(data-label);
    flex: 0 0 auto;
    color: var(--muted-foreground);
    font-size: 0.6875rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }
  /* the row checkbox and the empty-state cell carry no label */
  .dt-table :deep(tbody td:not([data-label]))::before {
    content: none;
  }
  .dt-table :deep(tbody td[colspan]) {
    display: block;
    padding: 0 12px;
  }
}
</style>
