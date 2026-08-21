<script setup lang="ts" generic="T extends Record<string, unknown>">
import { Loader2 } from 'lucide-vue-next'

const props = defineProps<{
  rows: T[]
  columns: { key: string; label: string }[]
  loading?: boolean
  rowsClickable?: boolean
  selectable?: boolean
  selected?: (string | number)[]
  rowKey?: string
}>()

const emit = defineEmits<{
  'row-click': [T]
  'update:selected': [(string | number)[]]
}>()

const slots = useSlots()

const keyField = computed(() => props.rowKey ?? 'id')
const selectedSet = computed(() => new Set(props.selected ?? []))
const allSelected = computed(() =>
  props.rows.length > 0 && props.rows.every((row) => selectedSet.value.has(row[keyField.value] as string | number)),
)

function toggleAll(checked: boolean) {
  emit('update:selected', checked ? props.rows.map((row) => row[keyField.value] as string | number) : [])
}

function toggleRow(row: T, checked: boolean) {
  const key = row[keyField.value] as string | number
  const next = new Set(selectedSet.value)
  if (checked) next.add(key)
  else next.delete(key)
  emit('update:selected', [...next])
}
</script>

<template>
  <div class="rounded-[var(--radius-lg)] border border-border bg-card shadow-[var(--shadow-surface)] overflow-hidden">
    <div v-if="loading" class="flex justify-center items-center py-8">
      <Loader2 class="size-5 animate-spin text-primary" />
    </div>
    <div v-else class="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead v-if="selectable" class="w-10">
              <Checkbox :model-value="allSelected" @update:model-value="toggleAll" />
            </TableHead>
            <TableHead v-for="col in columns" :key="col.key">{{ col.label }}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <template v-if="rows.length">
            <TableRow
              v-for="(row, i) in rows"
              :key="i"
              :class="rowsClickable ? 'cursor-pointer' : ''"
              @click="rowsClickable && emit('row-click', row)"
            >
              <TableCell v-if="selectable" @click.stop>
                <Checkbox
                  :model-value="selectedSet.has(row[keyField] as string | number)"
                  @update:model-value="(checked) => toggleRow(row, checked)"
                />
              </TableCell>
              <TableCell v-for="col in columns" :key="col.key">
                <template v-if="slots[`${col.key}-data`]">
                  <slot :name="`${col.key}-data`" :row="row" />
                </template>
                <span v-else>{{ row[col.key] != null ? String(row[col.key]) : '—' }}</span>
              </TableCell>
            </TableRow>
          </template>
          <TableRow v-else>
            <TableCell :colspan="columns.length + (selectable ? 1 : 0)" class="text-center py-6 text-muted-foreground">
              No data
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>
  </div>
</template>
