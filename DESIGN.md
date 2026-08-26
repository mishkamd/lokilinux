---
name: LokiLinux
description: Enterprise Linux Operations Platform — a command-center control plane for fleet operations, security, PKI/KMS, observability, and compliance drift across a Linux fleet
colors:
  tactical-forest: "#2D6A4F"
  tactical-forest-hover: "#3A7D5D"
  signal-green: "#4FAF74"
  field-white: "#FAFAFA"
  blackout: "#050507"
  panel-black: "#111117"
  panel-black-raised: "#15151D"
  faded-gray: "#A1A1AA"
  hairline: "rgba(255, 255, 255, 0.07)"
  threat-red: "#D34D4D"
  caution-amber: "#D6A44D"
  recon-blue: "#5A8DFF"
  signal-violet: "#8B5CF6"
  neutral-gray: "#71717A"
  signal-orange: "#f97316"
typography:
  display:
    fontFamily: "Iceberg, Inter, ui-sans-serif, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 300
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  display-wordmark:
    fontFamily: "Iceberg, Inter, ui-sans-serif, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 300
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Iceberg, Inter, ui-sans-serif, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 300
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "0.08em"
  field-value:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, sans-serif"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.4
  tooltip:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.4
  badge-micro:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, sans-serif"
    fontSize: "10px"
    fontWeight: 500
    lineHeight: 1.4
  widget-body:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.4
  metadata:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, sans-serif"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.4
  widget-link:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, sans-serif"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1.4
  widget-stat:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 700
    lineHeight: 1.2
rounded:
  sm: "10px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  2xl: "24px"
  full: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
components:
  button-primary:
    backgroundColor: "{colors.tactical-forest}"
    textColor: "{colors.field-white}"
    rounded: "{rounded.lg}"
    padding: "0 12px"
    height: "32px"
  button-primary-hover:
    backgroundColor: "{colors.tactical-forest-hover}"
  button-destructive:
    backgroundColor: "{colors.threat-red}"
    textColor: "#ffffff"
    rounded: "{rounded.lg}"
    padding: "0 12px"
    height: "32px"
  button-outline:
    backgroundColor: "transparent"
    textColor: "inherit"
    rounded: "{rounded.lg}"
    padding: "0 12px"
    height: "32px"
  badge-soft:
    backgroundColor: "color-mix(oklch, {colors.threat-red} 16%, transparent)"
    textColor: "{colors.threat-red}"
    rounded: "{rounded.full}"
    padding: "2px 8px"
  badge-blue:
    backgroundColor: "color-mix(oklch, {colors.recon-blue} 16%, transparent)"
    textColor: "{colors.recon-blue}"
    rounded: "{rounded.full}"
    padding: "2px 8px"
  card:
    backgroundColor: "{colors.panel-black}"
    rounded: "{rounded.md}"
    padding: "16px"
  input:
    backgroundColor: "{colors.panel-black}"
    textColor: "{colors.field-white}"
    rounded: "{rounded.sm}"
    padding: "4px 10px"
    height: "32px"
  dialog:
    backgroundColor: "{colors.panel-black}"
    rounded: "{rounded.xl}"
---

# Design System: LokiLinux

## Overview

**Creative North Star: "Precision Terminal"**

LokiLinux is a command-center dashboard, not a marketing surface — its users are IT/DevOps admins scanning a Linux fleet daily for problems: unpatched CVEs, drifted compliance, failed jobs. Every design decision defers to that job. The system runs dark-by-default (near-black canvas, `initialValue: 'dark'` in the color-mode config) with a single, disciplined forest-green accent that appears only where something needs a decision or a status. Typography carries the operational weight: a distinctive light-weight display face (Iceberg) marks page identity and section titles, everything else is set in Inter, and numeric data uses tabular figures so columns of packages, CVEs, and metrics line up like a real instrument panel.

Nothing here reaches for glassmorphism, gradients, skeuomorphism, or playful SaaS ornamentation — the codebase's own comment on its card surface states the intent directly: **"Terminal-precision surface: no glass/blur, just crisp borders + subtle shadow."** Depth is structural, not decorative — a component sits flush at rest and lifts 1px only as feedback (hover, elevation, an open overlay), never as passive polish.

**Key Characteristics:**
- Dark-by-default, near-black canvas with a single disciplined green accent
- Crisp hairline borders and 1px-lift feedback — no blur, no glass, no gradients
- A light-weight display face (Iceberg) marks identity and structure; Inter carries every working word
- Tabular numerals everywhere data is compared — packages, CVEs, metrics, timestamps
- Density over whitespace: this is a daily instrument, not an onboarding surface

## Colors

Quiet and exact: one accent, four semantic status colors, and a near-black neutral scale that does almost all of the work.

### Primary
- **Tactical Forest** (`#2D6A4F`): the resting-state accent — primary buttons, active nav items, focus rings, links. Used sparingly; this is the one color the eye is meant to catch.
- **Tactical Forest — Hover** (`#3A7D5D`): primary-button hover state only.
- **Signal Green** (`#4FAF74`): the "activated/live" state of the primary accent (hover-glow on the sidebar logo, active nav text) — and, not by coincidence, the exact same hex used for the Success semantic color below. Green means "good" and "engaged" everywhere in this system; there is no separate palette for the two ideas.

### Semantic / Status
- **Signal Green** (`#4FAF74`) — success, healthy, active, resolved.
- **Threat Red** (`#D34D4D`) — destructive actions, critical severity, failed jobs.
- **Caution Amber** (`#D6A44D`) — warnings, medium severity, pending states.
- **Recon Blue** (`#5A8DFF`) — informational, running/in-progress states, one chart series.
- **Signal Orange** (`#f97316`, token `--severity-high`) — HIGH severity specifically, one step down from Threat Red on the vulnerability severity scale (LOW → Recon Blue, MEDIUM → Caution Amber, HIGH → Signal Orange, CRITICAL → Threat Red — verified directly against `VulnerabilitySeverityDonut.vue`'s `SEVERITY_COLOR` map). Same hex in both themes; promoted from a repeated literal to a real token so no call site hardcodes it. `Badge.vue` now has a `blue` color (mapped to `--info`) so LOW renders in its real Recon Blue instead of falling back to gray. This scale is centralized in `composables/useSeverity.ts` (`severityColor`/`severityLabel`) — the canonical source; `pages/alerts/index.vue`, `pages/index.vue`, and `TopVulnerableServers.vue` all read from it instead of restating their own map.
- **Signal Violet** (`#8B5CF6`) — reserved for chart data only (the 4th trend series); never used as a UI/status color.

### Neutral
- **Blackout** (`#050507`): the base canvas — page background.
- **Panel Black** (`#111117`): card and popover surfaces, one step up from Blackout.
- **Panel Black — Raised** (`#15151D`): the elevated variant of Panel Black, for surfaces that sit visually above ordinary cards.
- **Field White** (`#FAFAFA`): primary text and icon color on dark surfaces.
- **Faded Gray** (`#A1A1AA`): secondary/muted text — labels, captions, timestamps, placeholder text.
- **Hairline** (`rgba(255,255,255,0.07)`): every border and input outline in dark mode. Never a solid neutral gray — always this translucent white hairline over Panel Black.

A parallel light-mode palette exists (`:root`, unprefixed) built from Tailwind's neutral OKLCH scale rather than named Blackout/Panel tokens, toggled via a `.dark` class swap (`storageKey: 'lokilinux-color-mode'`). Dark is the product's default (the boot script still seeds `dark` on first visit, deliberately not following OS preference) — but light is now a fully first-class alternate, not a half-finished fallback: every card's resting/hover elevation, the sidebar/table hover states, and every chart color are correct in both themes. The four `.status-*` classes (a pre-`.dark`-era status-pill vocabulary, unreferenced anywhere in the app) were removed rather than ported.

### Named Rules
**The One Accent Rule.** Tactical Forest/Signal Green is the only color that means "brand." Every other hue on screen (red, amber, blue, violet) is load-bearing status information, never decoration — if a color appears, it is telling the admin something is true about their fleet.

**The Hairline Rule.** Borders are never a flat gray. They are always `rgba(255,255,255,0.07)` over the dark neutral surfaces — translucent, so they read as "an edge in this material" rather than "a drawn line."

**The Text-Contrast Rule.** Tactical Forest (`#2D6A4F`) and Signal Green (`#4FAF74`) are not interchangeable — each passes WCAG AA text contrast (4.5:1) on only one theme. Tactical Forest reads at 6.0–6.4:1 on light-mode backgrounds but only 3.19:1 on dark-mode Blackout (fails AA for body text). Signal Green is the inverse: 7.48:1 on dark-mode Blackout, but only 2.6–2.7:1 on light-mode backgrounds (fails badly). Any link or text-colored accent uses `text-primary dark:text-primary-active` — never a bare `text-primary` alone once it crosses into dark mode. `bg-primary` (button fills) is unaffected by this rule: a 3:1 floor applies to UI-component/large-surface contrast, not 4.5:1, so Tactical Forest stays the correct resting-state button color in both themes.

## Typography

**Display Font:** Iceberg (with Inter, ui-sans-serif fallback)
**Body Font:** Inter (with ui-sans-serif, system-ui fallback)
**Label/Data Font:** Inter, set with `font-variant-numeric: tabular-nums` wherever numbers are compared

**Character:** Iceberg is a narrow, geometric, faintly technical display face used exclusively at light weight (300) — it reads as an identity mark, not a headline font, and is confined to the app's own name/page-titles/section-titles. Inter carries every sentence of working UI text at a normal, unforced weight; the pairing is one quiet workhorse face plus one distinctive light accent face, never two competing voices.

### Hierarchy
- **Display** (300, 1.25rem/20px, line-height 1.2, `-0.02em` tracking): page titles in the app header (`.page-title`). Nudged 3px down from its natural baseline — Iceberg sits visually high in its line box and needed manual optical centering in the 64px header.
- **Display — Wordmark** (300, 1.5rem/24px, tracking-tight): the "LokiLinux" sidebar logo specifically — one step larger than the header's Display size since it stands alone as the app's identity mark rather than sharing a row with other controls. Nudged 4px down (`mt-1`) for the same Iceberg optical-centering reason as Display.
- **Title** (300, 0.9375rem/15px, line-height 1.2, `-0.01em` tracking): section headings inside cards and panels (`.section-title`).
- **Body** (400, 14px, line-height 1.5): the working font size for buttons, inputs, table cells, and most UI copy — set as `text-[14px]` at most call sites rather than a Tailwind step, on a `106%` root font-size base.
- **Label** (600, 0.6875rem/11px, `0.08em` tracking, uppercase): section eyebrows and metric labels (`.label-caps`) — bold, tiny, spaced-out caps in a muted gray, always paired with a `.data-value` number beneath it.
- **Field Value** (500, 13px): a compact step between Label and Body for dense read-only data — server detail fields (OS, kernel, IP, FQDN, agent version, last seen), package version strings, user lists. Reused consistently (9 sites on the server detail page alone); not a one-off.
- **Tooltip** (400, 12px): floating tooltip text on chart/donut hover — shared verbatim across `ChartTooltip.vue` and both donut components' Unovis crosshair templates.
- **Badge Micro** (500, 10px): the smallest step, used only inside `MetricCard.vue`'s status-badge row (`text-[10px]`) where multiple badges must fit one line without wrapping — one step below Label, deliberately tighter, never used for standalone text.
- **Widget Body** (400, 12px, `text-xs`): the dominant body size *inside* dashboard widgets — row labels, list values, stat breakdowns (`OsDistributionDonut`, `AgentStatusDonut`, `TopVulnerableServers`, `SecurityOverview`, `ComplianceOverviewCard`, and others). Distinct from the 14px Body role: Body is for standalone UI controls (buttons, inputs, table cells); Widget Body is specifically the denser size a `.surface-card` dashboard widget uses for its own internal rows — confirmed consistent across 10+ files, not a single-widget one-off.
- **Metadata** (400, 11px, no tracking, no uppercase): plain secondary text — percentages, timestamps, sub-captions (`text-[11px]` in `OsDistributionDonut`, `AgentStatusDonut`, `RecentActivityFeed`, `SecurityOverview`'s trend delta). Easy to confuse with Label at a glance since both sit at 11px, but Metadata is never uppercase/tracked/bold — it's a quieter, plainer register than Label's eyebrow treatment.
- **Widget Link** (500, 12px, `text-primary dark:text-primary-active`): the "View All →" / "View full report →" pattern, reused verbatim across 6 dashboard widgets (`MetricCard`, `JobsTrendChart`, `RecentActivityFeed`, `TopVulnerableServers`, `SecurityOverview`, `ComplianceOverviewCard`) plus 5 sites in `pages/index.vue` — one consistent role, not restated per-widget by accident. Theme-conditional color, see The Text-Contrast Rule below.
- **Widget Stat** (700, 1.125rem/18px): the secondary-tier headline number/label inside the bottom "system status" grid (`SecurityOverview`'s risk-level word, `ComplianceOverviewCard`'s compliance percentage) — deliberately smaller than a top-row `MetricCard`'s 30px headline (that row is the primary KPI tier; this grid is the secondary status tier, per the layout pass's rhythm work), but large enough to read as a real stat, not buried body text.

### Named Rules
**The Tabular Numerals Rule.** Anywhere a number can be compared to another number in the same view — metric cards, table columns, CVE counts — `font-variant-numeric: tabular-nums` is set (globally on `body`, reinforced on `.data-value`). Digits must line up; this is an ops tool, not prose.

**The One Display Face Rule.** Iceberg never appears below `.section-title` size and never at a weight heavier than 300. If something needs emphasis at body scale, that's Inter at a heavier weight — not a bigger or bolder display face.

## Layout

The shell is a fixed 232px sidebar plus a fluid content column (`flex h-screen`, sidebar `fixed lg:static` — an overlay drawer under the `lg` breakpoint, a static rail above it). The content header is a flush 64px bar (`h-16`) holding the page title, a centered search field, and utility icons. Below it, pages default to `p-3 sm:p-4` and a `space-y-3` rhythm between stacked sections — tight, consistent 12–16px gaps rather than generous whitespace.

Dashboard/detail pages compose from a small set of repeating grid shapes: a `grid-cols-1 sm:grid-cols-2 xl:grid-cols-4` row of metric cards, a `grid-cols-1 md:grid-cols-2` pair of donuts/charts, and full-width trend charts and tables beneath. Tables and cards never exceed the content column's width; nothing goes full-bleed. Mobile collapses the sidebar into a `bg-black/60` backdrop-drawer; density does not relax on small screens, the layout just stacks to one column — confirmed live at 390px: a 2-up KPI grid with no `sm` step truncated card labels ("Servers"→"SER…") because the label + "View all" link had no room at half-width on a narrow phone; the `sm:` step is load-bearing, not decorative.

The header row (page tabs + range/filter controls, `flex items-center justify-between gap-2`) needs the same defensive shape as any other flex row with a `truncate`-adjacent child: the scrollable/shrinkable element (`AppTabs`) needs `min-w-0` on itself as the flex item, or a flex child's default `min-width: auto` silently blocks it from ever shrinking below its own content width — confirmed live at 768px, where a 6-item tab strip pushed the range selector button off the right edge of the viewport with no way to reach it. `AppTabs` now scrolls horizontally within its own bounds (`overflow-x-auto` on the tablist, `shrink-0` per tab button) instead of pushing sibling controls off-screen.

## Elevation & Depth

Flat at rest, lifted only as feedback — not ambient decoration. Every raised surface starts at `--shadow-surface`. Depth escalates in three concrete steps only when a surface actually changes state: hover, an open dialog, or a toast/overlay.

The four shadow tokens are theme-scoped (`:root` + `.dark`, not global) — dark leans on a bright hairline ring for edge definition plus black drop shadows for depth; light inverts that: the hairline is nearly invisible on a white surface, so light-mode shadows lean on a soft, low-alpha, dark-tinted shadow alone for both edge and depth.

### Shadow Vocabulary
- **Surface** — dark `0 0 0 1px rgba(255,255,255,0.03)` (a hairline, barely a shadow); light `0 1px 2px rgba(16,24,32,0.04), 0 0 0 1px rgba(16,24,32,0.04)`. Resting state for every card, table, and container.
- **Raised** — dark `0 4px 12px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.05)`; light `0 4px 12px rgba(16,24,32,0.1), 0 0 0 1px rgba(16,24,32,0.06)`. Hover state for cards and interactive surfaces, paired with a 1px `translateY` in code.
- **Overlay** — dark `0 8px 32px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.06)`; light `0 8px 32px rgba(16,24,32,0.14), 0 0 0 1px rgba(16,24,32,0.07)`. Toasts and floating popovers.
- **Dialog** — dark `0 12px 48px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.08)`; light `0 12px 48px rgba(16,24,32,0.18), 0 0 0 1px rgba(16,24,32,0.08)`. Modals — the deepest, rarest shadow in the system.

### Named Rules
**The Flat-By-Default Rule.** Surfaces are flat (Surface shadow only) at rest. Raised/Overlay/Dialog shadows appear exclusively in response to state — hover, open, or floating above the page — never as a static "card looks fancy" treatment.

**The Reduced-Motion Rule.** `@media (prefers-reduced-motion: reduce)` (`global.css`, after the Unovis tooltip block) collapses every animation/transition duration to near-zero and stops looping animations (`.animate-pulse`) outright. Every motion in this system is decorative feedback, not information-carrying — nothing is lost by reaching the end state instantly, so this is the correct fix, not a compromise. Any new animation added to the system must degrade the same way; it should never need a bespoke reduced-motion exception.

## Shapes

Radius scales with what a component *is*, not with arbitrary rounding taste — every value derives from one base (`--radius: 16px`) via `calc()`, so the whole system resizes from one token. Smaller, denser controls get tighter corners; larger, more modal surfaces get looser ones.

- **10px** (`--radius-sm`): inputs, selects, checkboxes — the tightest corner, for the smallest interactive controls.
- **12px** (`--radius-md`): cards, alerts.
- **16px** (`--radius-lg`, the base): buttons, tables, the DataTable's outer frame.
- **20px** (`--radius-xl`): dialogs and modals.
- **24px** (`--radius-2xl`): special/large containers (rare).
- **Full** (`9999px`): badges/pills and the scrollbar thumb — anything that's a capsule, not a box.

Borders are hairlines, never heavy strokes (see Colors → The Hairline Rule). Nothing in the system uses a hard-edged square corner or an asymmetric radius; every shape is uniformly rounded per its tier.

### Named Rules
**The One Radius Family Rule.** Every corner value is `calc(var(--radius) ± Npx)` from the single `--radius` base — never a radius invented in isolation for one component.

## Components

Buttons, cards, and inputs share one restrained material language: dark panel surfaces, hairline borders, a single accent color used only where it's earned. Nothing glows or textures for its own sake — the quiet reads as trustworthy, not boring, because every deviation from flat/quiet is meaningful (a state change, a status color, a focus ring).

### Buttons
- **Shape:** `16px` radius (`--radius-lg`), matching the table/button tier.
- **Primary:** Tactical Forest background, Field White text, `h-8` (32px) / `px-3` at default size, hover shifts to Tactical Forest — Hover and the whole button lifts `-translate-y-0.5`.
- **Destructive:** Threat Red background, white text — same shape and motion as Primary.
- **Outline / Secondary / Ghost:** transparent or muted background at rest, `bg-accent` on hover — same hairline-bordered restraint as every other surface.
- **Sizes:** `xs` (24px, tighter `--radius-sm` corner), `sm` (28px), default (32px), `lg` (36px), `icon` (32px square).
- **Hover / Focus:** every variant lifts 1px on hover and returns to flush on `active`; focus shows a 2px ring in the accent color. Motion always runs on `--ease-out-expo` at `--duration-normal` (200ms).

### Badges
- **Shape:** fully rounded pill (`rounded-full`) for `soft`/`solid`; the `plain` variant drops the pill shape entirely (bold colored text, no fill, no border) for badges packed into a KPI card's number row where a background would compete with the headline figure.
- **Soft variant (default):** a 14–16% tint of the status color as background, the full-strength status color as text — this is how severity/status reads in every table row.
- **Solid variant:** full-strength status color as background, white text — used for emphasis, sparingly.
- **Colors:** `red`/`green`/`gray`/`amber`/`orange` (Signal Orange, HIGH severity) plus `blue` (Recon Blue, `--info`) — added so LOW severity and RUNNING-adjacent info states render in their real hue instead of falling back to gray.
- **Sizes:** `xs` (10px text, tightest padding), `sm` (12px text) — visually distinct now, not aliased to the same size.

### Cards / Containers
- **Corner Style:** `12px` (`--radius-md`).
- **Background:** Panel Black, hairline border.
- **Shadow Strategy:** Surface at rest, Raised + 1px lift on hover (see Elevation & Depth).
- **Internal Padding — two legitimate roles, not a single value:**
  - `Card.vue` primitive (used standalone, e.g. KPI cards outside the dashboard grid): `16px` body, `10px/16px` (vertical/horizontal) header and footer strips when present, each divided by a hairline border.
  - Dashboard-widget `.surface-card` pattern (every widget on the main dashboard — `MetricCard`, `OsDistributionDonut`, `VulnerabilitySeverityDonut`, `AgentStatusDonut`, `JobsTrendChart`, `RecentActivityFeed`, `TopVulnerableServers`, `RecentFailedJobs`, `ComplianceOverviewCard`): `12px` uniformly, including `MetricCard` itself — it now shares the class directly rather than hand-rolling its own border/shadow/hover in Tailwind. Denser than the standalone `Card.vue` primitive on purpose.

### Inputs / Fields
- **Style:** Panel Black background, hairline border, `10px` radius (`--radius-sm`), `32px` height, `14px` text.
- **Focus:** border shifts to Tactical Forest and a soft 3px accent-tinted glow appears (`box-shadow: 0 0 0 3px color-mix(...primary 15%...)`) alongside the standard focus ring — a deliberately visible, colored focus state, not just an outline.
- **Disabled:** 50% opacity, cursor disabled.

### DataTable (signature component)
The central instrument of the whole product — every fleet, CVE, job, and package list runs through it. Outer frame at `16px` radius (button/table tier, not card tier) with a hairline border and Surface shadow, `overflow-hidden` so the header row's corners stay crisp. Loading state replaces the entire table with a centered spinner rather than skeleton rows. Optional row-selection checkboxes and a `rows-clickable` cursor state are the table's only interactive embellishments — everything else is plain, dense rows of tabular data.

### Table-in-Widget (signature pattern)
Dashboard widgets that need a real table (`ActiveIncidents`, `InfrastructureInventory`) never wrap `DataTable.vue` — its outer frame is already a card (border, shadow, `16px` radius), and nesting it inside a `.surface-card` would stack two card frames, which the system forbids (see Cards / Containers). Instead they compose the raw `Table`/`TableHeader`/`TableRow`/`TableHead`/`TableBody`/`TableCell` primitives directly inside the standard `.surface-card` widget shell (icon-in-tinted-square header, `label-caps` title, "View all →" link, error → loading `Skeleton` → empty → content), with the table itself in a plain `overflow-x-auto` wrapper for narrow viewports — one card frame total, not two.

### Icon-in-Tinted-Square (signature pattern)
Every dashboard widget and card header pairs a small Lucide icon inside a rounded square tinted at 15% opacity of its semantic color (`bg-[color-mix(in_oklch,var(--x)_15%,transparent)]`) with an uppercase `.label-caps` heading beside it — small, muted, color-coded by meaning, never a large illustrative icon. Two deliberate sizes, not one:
- **Widget-header tier** (`size-5` square, `size-3` glyph): every card/list header, and each per-row icon inside `TopVulnerableServers`/`RecentFailedJobs` (`size-7` square, `size-3.5` glyph — one step up, since a list row reads as its own small unit).
- **KPI-hero tier** (`size-10` square, `size-5` glyph): `MetricCard` only, one per top-row KPI. Larger and, unlike every other widget, colored **per card** via its `chartColor` (green/red/blue/yellow) rather than a fixed tint — the four top-row cards are meant to read as distinct at a glance before their numbers are even parsed.

### Workflow Builder (signature pattern)
The visual DAG editor (`components/workflow/*`) layers its own naming conventions on top of the shared system — five named rules, all enforced in code, not just convention:
- **The One Node Shell Rule.** Every node type renders through `WorkflowNodeBase.vue`, driven by a `NodeDefinition` (`utils/workflow/registry.ts`) — icon-in-tinted-square + label + status ring. `WorkflowNodeCondition.vue`/`WorkflowNodeApproval.vue` are the only exceptions, because their SHAPE differs (two labeled outputs; a gate visual), not their color or icon. A new node type is a registry entry, never a new `.vue` component.
- **The Honest Palette Rule.** A palette entry either maps to a type the engine can genuinely dispatch, or it doesn't appear at all — no "PRESET" badge dressing up a shortcut, no silently-broken entry. `NodeDefinition.executable` mirrors the backend's real dispatch coverage exactly; an entry not yet wired shows a muted `soon` tag instead of pretending to work.
- **The Layout-Is-Cosmetic Rule.** Dragging a node writes exclusively to the YAML's `layout:` block; pinning which side an edge enters/exits (Partea II) writes exclusively to `view:`. Neither ever touches `spec:` — a diff that touches `spec:` always means a semantic change, never a cosmetic one. This is what makes a workflow YAML reviewable in a PR.
- **The Invalid-YAML Freeze Rule.** While the YAML tab holds unparseable text, the canvas goes read-only and the model is never partially applied — the alternative (reconciling two diverging edit streams once the text becomes valid again) has no correct answer.
- **The Compile-Down Rule.** A Linux/Check node (`service`/`system`/`file`/`check`, `package`'s non-native actions) declares intent — an `action`/`type` discriminant plus parameters — never a shell string. Translation into the actual command lives exclusively server-side (`_compile_*` in `workflow_engine.py`), so the visual language stays stable even as the execution target changes underneath it (shell today, a native agent module later). The one interaction surface this creates: `showIf` on `FieldSpec` hides every field that doesn't apply to the current discriminant value, so a 9-variant node like `check` never shows more than the 2-4 fields relevant to whichever `type` is selected.

Canvas interaction specifics (Partea II): nodes expose all **four sides** as connection handles (`ConnectionMode.Loose`), visible on hover only — not permanent chrome, to keep the resting canvas quiet. A dropped or reconnected edge defaults to `bottom → top` unless manually re-pinned, so no existing workflow's rendering changes on upgrade. Edge selection opens the same right-side properties slot a node selection would (`on`/`label`/delete) — one slot, one occupant, never both a node panel and an edge panel at once.

### Navigation
- **Style:** sidebar sections grouped under `.label-caps` eyebrows (Overview, Infrastructure, Automation, Security, Compliance, Observability, Administration); active item gets a Tactical Forest tinted background and green text, inactive items are muted-foreground with a hover accent background.
- **User profile card** (sidebar footer): two lines, not one — display name on top, role label beneath in a smaller muted line. Avatar shows the user's first-initial (`Avatar`'s `fallback` prop), not a generic person icon.
- **Mobile:** the sidebar becomes a `-translate-x-full` drawer sliding in over a `bg-black/60` backdrop, same visual treatment as desktop otherwise — density and hairline styling do not relax for touch.

## Do's and Don'ts

### Do:
- **Do** keep the accent color rare — Tactical Forest/Signal Green earns attention because it appears almost nowhere else on screen.
- **Do** use `font-variant-numeric: tabular-nums` on any number that sits in a column or gets compared to another number.
- **Do** derive every corner radius from `calc(var(--radius) ± Npx)` — never invent a one-off radius value.
- **Do** treat elevation as a state response (hover, open, floating) — a resting surface stays at the barely-there Surface shadow.
- **Do** use the soft-tint badge style (14–16% status color background) as the default way to show severity/status in a table row; reserve solid badges for real emphasis.

### Don't:
- **Don't** add glass, blur, or gradient fills to any surface — the system's own code comments state this explicitly as a rejected direction.
- **Don't** use Iceberg below section-title size or heavier than weight 300 — it is an identity mark, not a general headline face.
- **Don't** introduce a second accent color. Every non-neutral hue besides Tactical Forest/Signal Green is semantic status information, not brand decoration.
- **Don't** draw a border as a flat solid gray — dark-mode borders are always the translucent `rgba(255,255,255,0.07)` hairline over Panel Black.
- **Don't** relax density or hairline precision on mobile; the drawer and stacked layout change, the visual language does not.
