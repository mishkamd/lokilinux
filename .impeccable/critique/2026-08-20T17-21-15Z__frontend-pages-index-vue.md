---
target: the LokiLinux dashboard
total_score: 28
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 1
timestamp: 2026-08-20T17-21-15Z
slug: frontend-pages-index-vue
---
Method: dual-agent (A: a2e4a7487d0ce420e · B: ad64fe4fdc8ad4afe)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 4 | Skeletons on every widget, global error+retry, per-widget empty-state copy. |
| 2 | Match System / Real World | 4 | Real ops vocabulary throughout (`PACKAGE_UPDATE`, `drift_event`, "patchable"), not genericized. |
| 3 | User Control and Freedom | 3 | Range selector is the only control; nothing traps the user, but no per-widget customization. |
| 4 | Consistency and Standards | 3 | Three different "view more" link conventions coexist on one screen. |
| 5 | Error Prevention | 3 | Read-only page; little to prevent, retry action is safe. |
| 6 | Recognition Rather Than Recall | 2 | Job Execution chart forces recall of an unstated 3-line color code — verified broken legend, see P0. |
| 7 | Flexibility and Efficiency | 2 | ⌘K search + range filter exist; no saved views, no widget reordering for daily power users. |
| 8 | Aesthetic and Minimalist Design | 4 | Disciplined single-accent system holds up live — no decorative color anywhere. |
| 9 | Error Recovery | 2 | Global fetch failure handled well; per-widget failure is not (P1) — renders as false "all clear." |
| 10 | Help and Documentation | 1 | No contextual help anywhere — Risk Score, "patchable," and remediation math are all unexplained. |
| **Total** | | **28/40** | **Good (low end)** |

## Design Specificity Verdict

**LLM assessment:** The page's content is genuinely authored for Linux fleet ops — real domain vocabulary, a disciplined single-accent palette, tabular data columns, and a restrained icon-in-tinted-square pattern. It does not read as a re-skinned generic SaaS template at the detail level. But the page's *shape* — KPI row → two ranked lists → 4-up gauge/donut grid → two summary cards → one trend chart → activity feed — is the standard fleet-dashboard grammar shared by Datadog, Grafana, and nearly every ops tool. That's the correct call for a time-pressured sysadmin (novelty in structure would cost, not earn, trust here), but it means distinctiveness lives entirely in content and material language, not in composition — worth naming plainly.

**Deterministic scan:** `detect.mjs --json` against all 12 touched files (the page plus every dashboard widget it composes) returned exit code 0 and an empty result set — zero mechanical anti-patterns. No false positives to flag, since nothing fired.

**Visual overlays:** Browser-injection overlay flow was not run this pass (no live-server injection step was exercised by either assessment); both assessments instead used direct screenshots and DOM/console/contrast evidence gathered live in the running app at http://localhost:3000/, which is reported inline below.

## Overall Impression

The redesign genuinely resolves the brief: the six thin, unequal-density tabs are gone, replaced by one page whose hierarchy actually reads CRITICAL → ATTENTION → HEALTH → TRENDS → ACTIVITY, with no artificial filler and no leftover navigation duplicating the sidebar. The biggest opportunity left on the table isn't structural — it's that two of the page's real widgets currently lie to the user under failure conditions in ways a security/ops tool specifically cannot afford, and the one chart meant to show "are automation jobs healthy" (Phase 7's core question) is unreadable without guessing a color code.

## What's Working

1. **The "10 patchable" badge** on the Vulnerabilities KPI card — a deliberate, well-placed piece of actionable signal folded into the page's most alarming number, not just more alarm.
2. **Empty-state copywriting** — "No failed jobs — automation is healthy" reframes an empty list as good news instead of a bare "No data," exactly right for an ops tool.
3. **Restraint in the color system** — severity/status color stays reserved for meaning across the whole page; verified live, holds up under inspection, no decorative color anywhere.

## Priority Issues

**[P0] Job Execution trend chart has no legend — three color-coded lines are unreadable.**
**Why it matters:** Phase 7's central question ("are automation jobs healthy, what's running vs. failing") is answered by exactly this chart, and it currently cannot be read without memorizing an undocumented color convention. Verified live: the rendered page contains no instance of "Successful," "Failed," or "Running" anywhere in either viewport.
**Root cause (confirmed in source):** `JobsTrendChart.vue` renders `<ChartLegend />` as a *sibling* of `<ChartContainer>`, not inside its default slot. `ChartContainer.vue` calls `provide(ChartConfigKey, props.config)` in its own `setup()`, which Vue only propagates to *descendant* components — a sibling in the parent template is never in that chain, so `ChartLegend.vue`'s `inject(ChartConfigKey, {})` falls through to its empty default and the `v-for` renders zero items. I confirmed this directly by reading all three files (`JobsTrendChart.vue:44-53`, `ChartContainer.vue`, `ChartLegend.vue`) — not a maybe, a reproducible logic bug.
**Fix:** Move `<ChartLegend />` inside `<ChartContainer>`'s default slot (as a sibling of the `<VisLine>`/`<VisAxis>` elements), so it sits in the same provide/inject subtree.
**Suggested command:** `/impeccable harden`

**[P1] Silent per-widget fetch failures render as false "all clear."**
**Why it matters:** `TopVulnerableServers.vue`, `RecentFailedJobs.vue`, and all four Fleet Posture donuts branch only on `loading`/`empty`, never `error`. If one of those fetches fails while the page's global `dashboard.summary` succeeds, the widget shows "No vulnerable servers detected" — indistinguishable from a genuinely clean fleet. `RecentActivityFeed.vue` already does this correctly (`v-else-if="error"`); the other widgets don't follow its own pattern. For a security dashboard, a false-negative "all clear" during a real backend degradation is close to the worst failure mode available.
**Fix:** Extend `RecentActivityFeed.vue`'s existing error-state pattern to `TopVulnerableServers`, `RecentFailedJobs`, and the four Fleet Posture widgets.
**Suggested command:** `/impeccable harden`

**[P2] Dead space in "Attention Required" at desktop widths.**
**Why it matters:** Both assessments independently flagged this. `TopVulnerableServers` has only 2 rows (the fleet has 2 servers) while its sibling `RecentFailedJobs` has 5; the `grid-cols-1 md:grid-cols-2` parent stretches both to equal height, leaving ~150-200px of visually empty card body under "rocky — 82 vulnerabilities" at 1440px. At a glance this reads as a loading glitch, not "there are only 2 servers" — confirmed in the live full-page screenshot.
**Fix:** `align-items: start` on the parent grid, or size each card to its own content height instead of stretching to the tallest sibling.
**Suggested command:** `/impeccable layout`

**[P2] "LokiLinux" logo/home link has no visible keyboard-focus indicator.**
**Why it matters:** Verified via real Tab keystrokes (not synthetic `.focus()`) across two independent checks: every other tested interactive element (sidebar nav links, metric cards, the range select, the account button) shows a clear focus ring; the header logo — the very first Tab stop on the page — shows none, despite `getComputedStyle` reporting the identical `outline: auto 1px` value that renders visibly on sibling nav links. A keyboard-only user (Sam) tabbing from page load has no visual confirmation their first Tab press landed anywhere.
**Fix:** Investigate why this specific link suppresses the rendered outline where siblings with identical computed values don't (likely an `overflow`/`isolation`/stacking-context issue on an ancestor, since the computed value itself isn't the problem); add an explicit visible focus style if the root cause can't be resolved cleanly.
**Suggested command:** `/impeccable audit`

**[P3] Unstyled default chart gridlines outweigh the data they support.**
**Why it matters:** The Job Execution chart's vertical gridlines render as full-height, near-white default Unovis chrome, visually heavier than the 2px data lines they're meant to support — no custom gridline styling exists in the codebase (confirmed via grep), so this is unstyled library default, not a deliberate choice, and it works against DESIGN.md's own "quiet, exact" hairline philosophy that the rest of the page follows.
**Fix:** Style or suppress the default Unovis axis gridlines to match the page's hairline-border weight.
**Suggested command:** `/impeccable quieter`

**[P3] Inconsistent "view more" link copy across one screen.**
**Why it matters:** Three conventions coexist and are visible together in one viewport: "View all" (`MetricCard.vue`, `RecentActivityFeed.vue`), "View All" (`TopVulnerableServers.vue`, `RecentFailedJobs.vue`, `JobsTrendChart.vue`), and "View full report →" (`SecurityOverview.vue`, `ComplianceOverviewCard.vue`). Minor, but cheap to unify.
**Fix:** Standardize on one casing/copy convention across all dashboard widgets.
**Suggested command:** `/impeccable polish`

## Persona Red Flags

**Alex (Power User):** Reads the top-line numbers fast (166/red, "High" risk, 2/2 online) — good triage speed for the primary "assess fleet health in 3-5 seconds" task. Red flag: hits the Job Execution chart's colorless legend and either already knows the convention or gives up on that section; the TopVulnerableServers dead space (P2) briefly reads as "did this break" before Alex reasons past it.

**Sam (Accessibility):** Every severity badge and donut correctly pairs color with a text label — genuinely good practice, held up under a 12-pair contrast spot-check (all passed WCAG AA, see below). But the Job Execution chart is a real "use of color alone" failure — three lines differentiated only by hue, no legend, no dash-pattern fallback. The missing focus ring on the header logo (P2) is a second, independent accessibility gap for this persona specifically.

**Riley (Stress Tester):** During an actual incident — one backend endpoint flaking while others succeed — "No vulnerable servers detected" and "No failed jobs — automation is healthy" become actively misleading (P1) rather than merely unhelpful, because nothing in those widgets or the four donuts distinguishes "empty because clean" from "empty because broken."

## Minor Observations

- Risk Score (`SecurityOverview.vue`) colors "Critical" and "High" identically (`text-destructive`) — differentiable only by reading the word, not by looking.
- At 390px, `RecentActivityFeed` action names truncate hard ("admin.age...", "vulnerability.remediation_requ...") because the row also reserves space for a badge and a right-aligned timestamp — confirmed in the live 390px screenshot.
- The Vulnerabilities KPI card's `deltaLabel(vulnsSpark)` trend computation is bound via `v-bind` but never visually surfaces, since `MetricCard`'s badge-precedence rule hides the trend whenever badges are present — dead computation, not a user-facing bug, but worth deleting rather than leaving as inert code.
- 12-pair live contrast spot-check (badges, links, muted text, nav, score labels) all passed WCAG AA (ratios 5.8–18.4); not exhaustive, but no failing pair was found among sampled text/background combinations.
- Console is clean of errors; the only warning present is the previously-known, harmless Unovis Crosshair "Y accessors not configured" message (10-15 repeats, non-blocking).

## Questions to Consider

1. If "10 patchable" is valuable enough to earn a badge, why is there no one-click "patch now" affordance anywhere on the dashboard — is Attention Required actually actionable, or just better-labeled awareness?
2. Given this redesign explicitly prioritized "actionable information over historical analytics" (Phase 2), does the Job Execution trend chart even earn its place on Overview if it can't currently be read at a glance — or does fixing the legend make it earn that place?
3. Ten-plus independent async widgets on one page currently share one failure mode (silent false-clean). Is a differentiated per-widget "couldn't load" state genuinely more work than the risk of a false negative during a real incident?
