---
title: "fix: Donut chart tooltips show undefined instead of label/value/percent"
date: 2026-08-14
type: fix
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
product_contract_source: ce-plan-bootstrap
---

# fix: Donut chart tooltips show undefined instead of label/value/percent

## Summary

Hovering over the dashboard's "Agent Status" and "Vulnerabilities by Severity" donut charts shows a tooltip reading `undefined: undefined (undefined%)` instead of the segment's name, count, and percentage. Root cause: Unovis's `Donut` component wraps each datum in a d3 pie-arc object (`{ ...pieArc, data: originalDatum, index, innerRadius, outerRadius }`) before binding it to the DOM segment; `VisTooltip`'s trigger callback receives that wrapper, not the original datum. Both chart components' tooltip template functions read fields (`d.name`, `d.count`, `d.pct`) directly off the wrapper instead of `d.data`.

## Problem Frame

- **In scope:** Fix the tooltip template functions in `AgentStatusDonut.vue` and `VulnerabilitySeverityDonut.vue` so they read the original segment fields via the wrapper's `.data` property.
- **Out of scope:** `OsDistributionDonut.vue` — it renders a hand-rolled SVG donut with no `VisTooltip`/Unovis dependency, so it is not affected and needs no change. No visual/styling changes. No changes to `ChartTooltip.vue` (used by line/area/bar charts via `VisCrosshair`, which passes the raw row datum directly — not subject to this wrapping).

## Requirements

- R1: Hovering a segment in `AgentStatusDonut.vue` shows the correct status name, count, and percentage.
- R2: Hovering a segment in `VulnerabilitySeverityDonut.vue` shows the correct severity name, count, and percentage.

## Key Technical Decisions

- KTD1: Fix by reading `d.data` (the original `Segment`) inside each `template()` function, rather than changing what's passed to `VisDonut`/`VisTooltip` — the wrapping is internal Unovis `Donut` rendering behavior (`arcData = pieGen(data).map(d => ({ ...d, data: d.data.datum, ... }))`), not something the caller configures.
- KTD2: Type the tooltip template parameter using Unovis's own pie-arc datum type wrapping `Segment` (or a local minimal shape `{ data: Segment }`) rather than `any`, so the `.data` access is type-checked instead of silently `any`.

## Implementation Units

### U1. Fix AgentStatusDonut tooltip data access

**Goal:** Tooltip shows real "Online"/"Offline" name, count, and pct instead of undefined.
**Requirements:** R1
**Dependencies:** none
**Files:**
- `frontend/components/dashboard/AgentStatusDonut.vue`
**Approach:**
- In `template(d)` (frontend/components/dashboard/AgentStatusDonut.vue:24), change the parameter type from `Segment` to the wrapped pie-arc shape (e.g. `{ data: Segment }`) and read fields off `d.data` (`d.data.name`, `d.data.count`, `d.data.pct`) instead of `d` directly.
- Leave `value`/`color` accessors (frontend/components/dashboard/AgentStatusDonut.vue:21-22) unchanged — those are called by `VisDonut` with the *original* `Segment` per-datum (via `config.value`/`config.color`, evaluated on `d.datum` before wrapping), not the tooltip wrapper, so they are unaffected by this bug.
**Patterns to follow:** Same fix shape as U2 (VulnerabilitySeverityDonut.vue) — keep both consistent.
**Test scenarios:**
- Happy path: hover the "Online" segment with `byStatus = { ACTIVE: 2 }` (total 2) → tooltip reads "Online: 2 (100%)".
- Happy path: hover the "Offline" segment with `byStatus = { ACTIVE: 1, OFFLINE: 1 }` → tooltip reads "Offline: 1 (50%)".
- Edge case: single non-zero segment (only "Online" rendered, `Offline` filtered out since `count` is 0) → hovering the visible segment does not show a stale/undefined second entry.
**Verification:** Manually hover each rendered segment in the browser and confirm the tooltip text matches the sidebar row's name/count/pct for that segment.

### U2. Fix VulnerabilitySeverityDonut tooltip data access

**Goal:** Tooltip shows real severity name, count, and pct instead of undefined.
**Requirements:** R2
**Dependencies:** none
**Files:**
- `frontend/components/dashboard/VulnerabilitySeverityDonut.vue`
**Approach:**
- In `template(d)` (frontend/components/dashboard/VulnerabilitySeverityDonut.vue:37), apply the same fix as U1: type the parameter as the wrapped pie-arc shape and read `d.data.name`, `d.data.count`, `d.data.pct`.
- Leave `value`/`color` accessors (frontend/components/dashboard/VulnerabilitySeverityDonut.vue:34-35) unchanged for the same reason as U1.
**Patterns to follow:** Identical fix shape to U1.
**Test scenarios:**
- Happy path: hover "Critical" segment with `bySeverity = { CRITICAL: 56, MEDIUM: 32, LOW: 12 }` → tooltip reads "Critical: 56 (56%)", matching the screenshot's sidebar values.
- Happy path: hover "Low" segment in the same data → tooltip reads "Low: 12 (12%)".
- Edge case: a severity with `count: 0` (e.g. HIGH absent from `bySeverity`) is filtered out of `segments` and never renders a segment/tooltip.
**Verification:** Manually hover each rendered segment in the browser and confirm the tooltip text matches the sidebar row's name/count/pct for that segment.

## Verification Contract

- Both fixed components render tooltips with real name/count/pct on hover for every visible segment, verified manually in-browser (frontend has no existing unit tests for these presentational chart components, and Unovis's DOM/hover rendering is not practically unit-testable without a browser).
- No regression in the sidebar list rendering (unaffected by this change — sidebar reads `segments` directly, never through the tooltip wrapper).

## Definition of Done

- [ ] U1 and U2 implemented.
- [ ] Dashboard loaded in a browser with real or seeded agent/vulnerability data; hovering each donut segment in both charts shows correct label, count, and percentage (no `undefined`).
- [ ] `OsDistributionDonut.vue` unchanged (confirmed out of scope, no regression risk since it has no tooltip).
