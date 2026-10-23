#!/usr/bin/env node
/**
 * Design-system guard.
 *
 * No ESLint, no dependencies: this is a regex pass over the Vue sources plus
 * a WCAG contrast check over the token file. It runs in well under a second,
 * which is the whole point — the rules have to be cheap enough to run on every
 * commit.
 *
 * Rules
 *   1. no raw hex colors outside assets/css/global.css
 *   2. no Tailwind palette colors (red-500, green-100, …) — tokens only
 *   3. no arbitrary radii (rounded-[Npx]) — --radius-* only
 *   4. no <h1> outside layouts/ (the chrome owns the page heading)
 *   5. no window.confirm / alert / prompt (use ConfirmDeleteDialog)
 *   6. every interactive element carries a focus ring
 *   7. the token pairs in global.css pass WCAG AA in both themes
 *   8. the size contract (32px controls), the 24px target floor, rem-only type
 *   9. no sub-minimum type — the smallest step is badge-micro (0.625rem / 10px)
 *  10. no 32px section rhythm (space-y-8) — the band is 12–16px
 *  11. no faded borders on chrome (border-border/40, border-border/60)
 *  12. no unsanctioned display sizes (text-4xl and up; auth wordmark excepted)
 *
 * Usage: node scripts/check-design-system.mjs
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const ROOT = new URL('..', import.meta.url).pathname
const SCAN_DIRS = ['components', 'pages', 'layouts', 'composables', 'utils', 'stores', 'server']
const SKIP_DIRS = ['node_modules', '.nuxt', '.output', '.gstack', '.impeccable', 'dist']
const EXTS = ['.vue', '.ts']

const violations = []
function report(file, line, rule, message) {
  violations.push({ file: relative(ROOT, file), line, rule, message })
}

function walk(dir, out = []) {
  let entries
  try {
    entries = readdirSync(dir)
  } catch {
    return out
  }
  for (const entry of entries) {
    if (SKIP_DIRS.includes(entry)) continue
    const full = join(dir, entry)
    const st = statSync(full)
    if (st.isDirectory()) walk(full, out)
    else if (EXTS.some((e) => entry.endsWith(e))) out.push(full)
  }
  return out
}

const files = SCAN_DIRS.flatMap((d) => walk(join(ROOT, d)))

// ── 1-5, 6: source rules ─────────────────────────────────────────────────────
const PALETTE = /\b(?:text|bg|border|ring|from|to|via|fill|stroke|shadow|outline|decoration|accent|caret|divide|placeholder)-(?:red|green|blue|yellow|amber|gray|zinc|slate|orange|purple|indigo|emerald|sky|rose|lime|teal|cyan|fuchsia|pink|violet)-\d{2,3}\b/
const HEX = /#[0-9a-fA-F]{3,8}\b/
const RADIUS = /rounded-\[\d+px\]/
const SPACING = /\b(?:gap|p|px|py|pt|pb|pl|pr|mt|mb|ml|mr|space-[xy])-\[\d+px\]/
const FONT_SIZE = /\btext-\[\d+px\]/
const CONFIRM = /(?<!function\s)(?<!const\s)(?<!let\s)(?<!var\s)(?<!=>\s)(?:window\.)?(?:confirm|alert|prompt)\s*\(/
// Elements that already carry their own ring.
const RING_CARRIERS = ['Button', 'Input', 'Select', 'Textarea', 'Checkbox', 'Switch', 'Stepper', 'AppTabs', 'TabNav', 'DataTable', 'FileInput', 'ColorModeButton']
const INTERACTIVE = /<(button|a|NuxtLink|input|select|textarea)\b/

for (const file of files) {
  const raw = readFileSync(file, 'utf8')
  // strip comments so prose about the rules doesn't trip them
  const lines = raw.split('\n')
  const code = lines.map((l) => l.replace(/(^|[^:])\/\/.*$/, '$1').replace(/<!--.*?-->/, ''))

  code.forEach((line, i) => {
    if (HEX.test(line)) report(file, i + 1, 'hex', `raw hex color — use a token (${line.trim().slice(0, 60)})`)
    if (PALETTE.test(line)) report(file, i + 1, 'palette', `Tailwind palette color — use a token (${line.trim().slice(0, 60)})`)
    if (RADIUS.test(line)) report(file, i + 1, 'radius', `arbitrary radius — use --radius-* (${line.trim().slice(0, 60)})`)
    if (SPACING.test(line)) report(file, i + 1, 'spacing', `arbitrary spacing — use the 4/8/12/16/24 scale (${line.trim().slice(0, 60)})`)
    if (FONT_SIZE.test(line)) report(file, i + 1, 'font-size', `arbitrary font size — use the scale (text-xs/sm/label/field/micro) (${line.trim().slice(0, 60)})`)
    if (CONFIRM.test(line) && !file.endsWith('.test.ts')) {
      report(file, i + 1, 'confirm', `window.confirm/alert/prompt — use ConfirmDeleteDialog (${line.trim().slice(0, 60)})`)
    }
    if (/<h1\b/.test(line) && !file.includes('/layouts/')) {
      report(file, i + 1, 'heading', `<h1> outside layouts/ — the chrome owns the page heading`)
    }
  })

  // rule 6 — focus rings (the class attribute may span several lines)
  // The primitives (Button/Input/…) carry their ring in their own base
  // class, which the source scan cannot see.
  if (RING_CARRIERS.includes(file.split('/').pop().replace('.vue', ''))) continue
  const joined = raw.replace(/(^|[^:])\/\/.*$/gm, '$1')
  const tagRe = /<(button|a|NuxtLink|input|select|textarea)\b((?:"[^"]*"|'[^']*'|[^>"'])*)>/g
  let m
  while ((m = tagRe.exec(joined))) {
    const tag = m[1]
    const attrs = m[2] || ''
    if (/focus-ring|focus-visible/.test(attrs)) continue
    // a component that carries its own ring
    if (RING_CARRIERS.includes(tag)) continue
    // elements whose focus is handled by a parent (label, summary) are fine
    if (tag === 'input' && /type="(hidden|checkbox|radio|file)"/.test(attrs)) continue
    const line = joined.slice(0, m.index).split('\n').length
    report(file, line, 'focus', `<${tag}> has no focus ring — add .focus-ring (or focus-visible:)`)
  }
}

// ── 7: contrast ──────────────────────────────────────────────────────────────
function parseColor(str) {
  const s = str.trim()
  if (s.startsWith('#')) {
    let h = s.slice(1)
    if (h.length === 3) h = [...h].map((c) => c + c).join('')
    return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
  }
  let m = s.match(/oklch\(\s*([\d.]+)(%?)\s+([\d.]+)(%?)\s+([\d.]+)/)
  if (m) {
    const L = parseFloat(m[1]) / (m[2] ? 100 : 1)
    const C = parseFloat(m[3]) / (m[4] ? 100 : 1)
    return oklchToRgb(L, C, parseFloat(m[5]))
  }
  m = s.match(/rgba?\(([^)]+)\)/)
  if (m) {
    const p = m[1].split(',').map((x) => parseFloat(x))
    return p.slice(0, 3).map((c) => (c > 1 ? c / 255 : c))
  }
  return null
}

function gamma(c) {
  const v = Math.max(0, Math.min(1, c))
  return v > 0.0031308 ? 1.055 * Math.pow(v, 1 / 2.4) - 0.055 : 12.92 * v
}

function oklchToRgb(L, C, hDeg) {
  const h = (hDeg * Math.PI) / 180
  const a = C * Math.cos(h)
  const b = C * Math.sin(h)
  const l_ = L + 0.3963377774 * a + 0.2158037573 * b
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b
  const s_ = L - 0.0894841775 * a - 1.291485548 * b
  const l = l_ ** 3
  const m = m_ ** 3
  const s = s_ ** 3
  return [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ].map(gamma)
}

function luminance(rgb) {
  const lin = (c) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4))
  const [r, g, b] = rgb.map(lin)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(fg, bg) {
  const l1 = luminance(fg)
  const l2 = luminance(bg)
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)
}

const css = readFileSync(join(ROOT, 'assets/css/global.css'), 'utf8')
function blockOf(selector) {
  const i = css.indexOf(selector)
  if (i < 0) return ''
  return css.slice(i, css.indexOf('\n}', i))
}
function tokensOf(block) {
  const out = {}
  for (const m of block.matchAll(/--([\w-]+):\s*([^;]+);/g)) out[m[1]] = m[2].trim()
  return out
}
function resolve(tokens, name, seen = 0) {
  const v = tokens[name]
  if (!v || seen > 5) return null
  if (v.startsWith('var(')) return resolve(tokens, v.slice(4, -1).trim(), seen + 1)
  return v
}

const themes = { light: tokensOf(blockOf(':root {')), dark: tokensOf(blockOf('.dark {')) }

// The type scale is rem-only: a px token is the one step that ignores both
// `html { font-size: 106% }` and the user's browser font size (MIS-249).
for (const name of ['--text-label', '--text-field', '--text-micro']) {
  const m = css.match(new RegExp(`${name}:\\s*([^;]+);`))
  if (m && !m[1].trim().endsWith('rem')) {
    report(join(ROOT, 'assets/css/global.css'), 0, 'type-scale', `${name}: ${m[1].trim()} — the type scale is rem-only`)
  }
}
// text colors on the card, and the foreground that sits on a status surface
const PAIRS = [
  ['foreground', 'card', 4.5],
  ['muted-foreground', 'card', 4.5],
  ['primary-text', 'card', 4.5],
  ['destructive', 'card', 4.5],
  ['success', 'card', 4.5],
  ['warning', 'card', 4.5],
  ['info', 'card', 4.5],
  ['severity-high', 'card', 4.5],
  ['destructive-foreground', 'destructive', 4.5],
  ['success-foreground', 'success', 4.5],
  ['warning-foreground', 'warning', 4.5],
  ['info-foreground', 'info', 4.5],
  ['severity-high-foreground', 'severity-high', 4.5],
]

for (const [theme, tokens] of Object.entries(themes)) {
  for (const [fgName, bgName, min] of PAIRS) {
    const fgRaw = resolve(tokens, fgName)
    const bgRaw = resolve(tokens, bgName)
    if (!fgRaw || !bgRaw) continue
    const fg = parseColor(fgRaw)
    const bg = parseColor(bgRaw)
    if (!fg || !bg) continue
    const ratio = contrast(fg, bg)
    if (ratio < min) {
      report(
        join(ROOT, 'assets/css/global.css'),
        0,
        'contrast',
        `${theme}: ${fgName} on ${bgName} is ${ratio.toFixed(2)}:1 (needs ${min}:1)`,
      )
    }
  }
}

// ── 8-11: size contract, target size, rem-only type scale ──────────────────
// Independent pass: unlike rule 6 this applies to the primitives too, since
// a hand-rolled button in a primitive file still has to respect the contract.
const TINY_HEIGHT = /\bh-[0-5]\b/
const BIG_ICON = /\bsize-(?:9|1[0-2])\b/
const PX_FONT = /font-size:\s*\d+(?:\.\d+)?px|fontSize:\s*['"]\d+(?:\.\d+)?px['"]/
// A text-xs link or button that declares no size at all renders at the line
// box (~17px) — under the 24px target floor. `py-1 -my-1` grows the hit area
// to 24px without moving the text, `min-h-6` when the box may grow.
const SMALL_TEXT = /\btext-xs\b/
const SIZE_CLASS = /\b(?:min-h|size|h|py|p)-(?:\d|\[)/
// Files owned by an in-flight change — the entry goes away with that change.
const TARGET_FLOOR_EXCEPTIONS = [
  // MIS-252 — the compliance rework owns this file; remove this entry when
  // that work lands.
  'pages/compliance/rules/[id].vue',
]

for (const file of files) {
  const raw = readFileSync(file, 'utf8')
  const joined = raw.replace(/(^|[^:])\/\/.*$/gm, '$1')
  const rel = relative(ROOT, file)
  const tagRe = /<(button|a|NuxtLink|input|select|textarea)\b((?:"[^"]*"|'[^']*'|[^>"'])*)>/g
  let m
  while ((m = tagRe.exec(joined))) {
    const attrs = m[2] || ''
    const line = joined.slice(0, m.index).split('\n').length
    if (TINY_HEIGHT.test(attrs) && !/min-h-6/.test(attrs)) {
      report(file, line, 'target', `<${m[1]}> is under the 24px target floor — use min-h-6 (or the primitive)`)
    }
    if (
      (m[1] === 'button' || m[1] === 'a' || m[1] === 'NuxtLink') &&
      SMALL_TEXT.test(attrs) &&
      !SIZE_CLASS.test(attrs) &&
      !TARGET_FLOOR_EXCEPTIONS.includes(rel)
    ) {
      report(file, line, 'target', `<${m[1]}> is text-xs with no size class — under the 24px target floor; use py-1 -my-1 (or min-h-6)`)
    }
    if (BIG_ICON.test(attrs)) {
      report(file, line, 'size', `<${m[1]}> icon box outside the 32px contract — use size-8`)
    }
  }
  raw.split('\n').forEach((l, i) => {
    if (PX_FONT.test(l)) {
      report(file, i + 1, 'type-scale', `px font size — the type scale is rem-only (${l.trim().slice(0, 60)})`)
    }
  })
}

// ── 12-15: size floors and the display-size cap ─────────────────────────────
// Four rules, one regex each. They are the mechanical half of four rules that
// until now existed only as prose in DESIGN.md.
const SUB_MIN_FONT = /\btext-\[(\d+(?:\.\d+)?)(px|rem)\]/
// The vertical rhythm is the 12–16px band (space-y-3 / space-y-4).
const BIG_RHYTHM = /(?<![\w.-])space-y-8(?![\w.-])/
// Chrome borders are the hairline (border-border) — not a faded one.
const FADED_BORDER = /\bborder-border\/(?:40|60)\b/
// The type scale tops out at text-3xl (1.875rem) for numbers.
const BIG_DISPLAY = /\btext-(?:4xl|5xl|6xl|7xl|8xl|9xl)\b/
// The auth wordmark is the one sanctioned exception to the display-size cap.
const DISPLAY_EXCEPTIONS = ['layouts/auth.vue']

for (const file of files) {
  const raw = readFileSync(file, 'utf8')
  const rel = relative(ROOT, file)
  raw.split('\n').forEach((l, i) => {
    const font = SUB_MIN_FONT.exec(l)
    if (font) {
      const v = parseFloat(font[1])
      const below = font[2] === 'px' ? v <= 9 : v < 0.625
      if (below) {
        report(file, i + 1, 'min-font', `sub-minimum font size (${font[0]}) — the smallest step is badge-micro (0.625rem / 10px)`)
      }
    }
    if (BIG_RHYTHM.test(l)) {
      report(file, i + 1, 'rhythm', `space-y-8 (32px) — the vertical rhythm is the 12–16px band (space-y-3 / space-y-4)`)
    }
    if (FADED_BORDER.test(l)) {
      report(file, i + 1, 'border', `faded border — chrome borders are the hairline (border-border), not border-border/40 or /60`)
    }
    if (BIG_DISPLAY.test(l) && !DISPLAY_EXCEPTIONS.includes(rel)) {
      report(file, i + 1, 'display-size', `unsanctioned display size — the scale tops out at text-3xl (the auth wordmark excepted)`)
    }
  })
}

// ── report ───────────────────────────────────────────────────────────────────
if (!violations.length) {
  console.log(`design-system guard: OK (${files.length} files scanned)`)
  process.exit(0)
}

const byRule = violations.reduce((acc, v) => ((acc[v.rule] = (acc[v.rule] ?? 0) + 1), acc), {})
console.error(`design-system guard: ${violations.length} violation(s)`)
for (const [rule, count] of Object.entries(byRule)) console.error(`  ${rule}: ${count}`)
for (const v of violations.slice(0, 40)) {
  console.error(`  ${v.file}${v.line ? ':' + v.line : ''}  [${v.rule}] ${v.message}`)
}
if (violations.length > 40) console.error(`  … and ${violations.length - 40} more`)
process.exit(1)
