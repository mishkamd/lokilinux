<script setup lang="ts">
import { EditorView, basicSetup } from 'codemirror'
import { yaml } from '@codemirror/lang-yaml'
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language'
import { tags as t } from '@lezer/highlight'

const props = defineProps<{ modelValue: string; tall?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [string] }>()

const container = ref<HTMLDivElement | null>(null)
let view: EditorView | null = null

// All colors reference the app's CSS custom properties (assets/css/global.css)
// so the editor follows light/dark automatically — var() resolves at runtime,
// so flipping the .dark class on <html> re-themes the editor with no rebuild.
const lokiTheme = EditorView.theme({
  '&': {
    fontSize: '13px',
    backgroundColor: 'var(--card)',
    color: 'var(--foreground)',
    height: '100%',
  },
  '.cm-content': {
    fontFamily: 'var(--font-mono, "IBM Plex Mono", monospace)',
    caretColor: 'var(--primary-active)',
  },
  '.cm-cursor, .cm-dropCursor': {
    borderLeftColor: 'var(--primary-active)',
    borderLeftWidth: '2px',
  },
  '.cm-scroller': {
    fontFamily: 'var(--font-mono, "IBM Plex Mono", monospace)',
    overflow: 'auto',
  },
  '&.cm-focused': { outline: 'none' },
  '.cm-selectionBackground, ::selection': {
    backgroundColor: 'color-mix(in oklch, var(--primary-active) 22%, transparent) !important',
  },
  '.cm-activeLine': {
    backgroundColor: 'color-mix(in oklch, var(--foreground) 4%, transparent)',
  },
  '.cm-gutters': {
    backgroundColor: 'var(--card)',
    color: 'var(--muted-foreground)',
    border: 'none',
    borderRight: '1px solid var(--border)',
  },
  '.cm-activeLineGutter': {
    backgroundColor: 'color-mix(in oklch, var(--primary-active) 10%, transparent)',
    color: 'var(--primary-active)',
  },
  '.cm-lineNumbers .cm-gutterElement': {
    paddingLeft: '4px',
    paddingRight: '10px',
  },
  '.cm-matchingBracket, .cm-nonmatchingBracket': {
    backgroundColor: 'color-mix(in oklch, var(--primary-active) 22%, transparent)',
    outline: '1px solid var(--primary-active)',
  },
  '.cm-tooltip': {
    backgroundColor: 'var(--popover)',
    border: '1px solid var(--border)',
    color: 'var(--popover-foreground)',
  },
})

// Restrained 3-accent syntax palette pulled from the app's status colors:
// green keys, gold scalars, blue numbers, muted comments — same language as
// the badges elsewhere, and each color exists in both themes.
const lokiHighlight = HighlightStyle.define([
  { tag: t.propertyName, color: 'var(--primary-active)', fontWeight: '600' },
  { tag: t.definition(t.propertyName), color: 'var(--primary-active)', fontWeight: '600' },
  { tag: [t.string, t.special(t.string)], color: 'var(--warning)' },
  { tag: [t.number, t.bool, t.atom], color: 'var(--info)' },
  { tag: t.comment, color: 'var(--muted-foreground)', fontStyle: 'italic' },
  { tag: t.meta, color: 'var(--muted-foreground)' },
  { tag: t.punctuation, color: 'color-mix(in oklch, var(--foreground) 60%, transparent)' },
  { tag: t.invalid, color: 'var(--destructive)', textDecoration: 'underline' },
])

onMounted(() => {
  if (!container.value) return
  view = new EditorView({
    doc: props.modelValue,
    extensions: [
      basicSetup,
      yaml(),
      lokiTheme,
      syntaxHighlighting(lokiHighlight),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) emit('update:modelValue', update.state.doc.toString())
      }),
    ],
    parent: container.value,
  })
})

// External changes (e.g. switching which file is being edited) sync back into
// the editor without fighting the update listener above.
watch(() => props.modelValue, (value) => {
  if (view && value !== view.state.doc.toString()) {
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value } })
  }
})

onBeforeUnmount(() => view?.destroy())
</script>

<template>
  <!-- max-w-full + overflow-hidden keep long lines from pushing the editor
       past the viewport; the .cm-scroller inside scrolls horizontally. -->
  <div
    ref="container"
    class="w-full max-w-full overflow-hidden rounded-lg border border-input bg-card"
    :class="props.tall ? 'h-[65vh]' : 'h-80'"
  />
</template>
