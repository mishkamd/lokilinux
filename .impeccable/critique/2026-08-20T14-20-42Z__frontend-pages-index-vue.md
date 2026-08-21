---
target: the LokiLinux dashboard
total_score: 21
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
timestamp: 2026-08-20T14-20-42Z
slug: frontend-pages-index-vue
---
Method: dual-agent (A: a71b199973a7cdcd4 · B: a8819a30a0e1e3596)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2/4 | Skeletons/loading states work, but nothing surfaces agent heartbeat staleness despite PRODUCT.md Principle #1 explicitly requiring it |
| 2 | Match System / Real World | 2/4 | Severity vocabulary is correct, but the KPI card's own color-coding contradicts the donut chart right beside it |
| 3 | User Control and Freedom | 3/4 | Retry on error, reversible range filter, no traps |
| 4 | Consistency and Standards | 1/4 | Untranslated "Vezi tot" string, HIGH-severity color diverges between two components 8 lines apart, delta badges wired for only 1 of 4 KPI cards |
| 5 | Error Prevention | 3/4 | Read-only surface, little to prevent |
| 6 | Recognition Rather Than Recall | 3/4 | Consistent icon/label vocabulary, "TOTAL" center-label aids recall |
| 7 | Flexibility and Efficiency | 2/4 | No shortcuts, no widget reorder/collapse, one fixed layout for novice and power user alike |
| 8 | Aesthetic and Minimalist Design | 2/4 | Individual widgets are clean; 13 widgets stacked with zero progressive disclosure is not |
| 9 | Error Recovery | 2/4 | Generic error copy doesn't distinguish "API down" from "agents haven't heartbeated" |
| 10 | Help and Documentation | 1/4 | No tooltip disclosing that "Risk Score" is a client-derived heuristic, not a real score |
| **Total** | | **21/40** | **Acceptable — significant improvements needed** |

## Design Specificity Verdict

**LLM assessment:** Mixed. The color system, Iceberg/Inter pairing, hairline borders, tabular-nums, and the icon-in-tinted-square pattern are genuinely product-specific and consistently executed across nine independent widget files with zero drift — that discipline could not be dropped unchanged into a generic SaaS dashboard. But the information architecture (KPI row → donut pair → trend line → activity feed → status grid) is the generic ops-dashboard template used everywhere; nothing about the *layout* says "Linux fleet tool" specifically — there's no heartbeat/staleness affordance anywhere, despite that being a named, confirmed product principle. The severity-color handling actively works against specificity: a fleet-security tool is exactly the domain where CRITICAL vs HIGH needs to be instantly legible, and one of the four KPI widgets flattens that distinction anyway.

**Deterministic scan:** `detect.mjs --json` against `pages/index.vue` + all 14 files in `components/dashboard/` returned exit code 0, zero findings. The scanner's function was verified with a positive control (a synthetic file with gradient text + bounce easing correctly triggered 2 findings) — this is a genuine clean result, not a broken tool. Read literally: none of the detector's 28 "AI-slop" signature patterns (gradient text, glow, marquees, pulsing dots, cream palettes, nested-card borders, overused stock fonts) are present. It is not a general-purpose design linter, so a clean scan doesn't contradict Assessment A's substantive findings below — they're checking different things.

**Visual overlays:** Not available this run. Live browser confirmation was blocked before it could start — login to `http://192.168.0.110:3000/` 401'd on the documented `.env` credentials (`Autentificare eșuată — Invalid email or password`), a pre-existing credential mismatch unrelated to this critique, flagged earlier this session and not yet resolved. No screenshot, no console capture, no injected overlay exists. Everything below is a source-level review, not an observed one.

## Overall Impression

The component-level craft is genuinely disciplined — nine dashboard widgets independently reimplement the same icon-square/label-caps/tabular-nums vocabulary with zero drift, and empty-state copy is specific per-widget rather than a copy-pasted "No data." But the page as a whole doesn't know what it wants to be: it's still a six-tab structure (`TABS` array, `AppTabs`, `dashboard.ts`'s `DashboardTab` union all still wired, `frontend/pages/index.vue:10-30,80,91-229`) whose Overview tab already duplicates almost everything the other five tabs show — so the flagship screen greets an admin with 9 upfront navigation choices (6 tabs + 3-range selector) before any content is even read, then floods them with 13 simultaneous widgets regardless of which tab they picked. The single biggest opportunity: collapse this into one committed information architecture (Overview-only or tabs-that-actually-partition, not both) and fix the two concrete inconsistency bugs (severity color drift, untranslated string) that are currently shipping.

## What's Working

1. **The design system is holding under real, organic growth.** Nine independently-authored dashboard widgets (`MetricCard`, both donuts, `JobsTrendChart`, `InfrastructureHealth`, `SecurityOverview`, etc.) each reimplement the exact same `size-5 rounded-md bg-[color-mix(...15%,transparent)]` icon treatment and `.label-caps` heading — zero drift across nine files is a real signal that DESIGN.md's system is being followed in practice, not just documented on paper.
2. **Empty states are calm and specific, not generic.** "No servers registered," "No open vulnerabilities," "Not enough history yet — trend appears once jobs run" — each is worded for its actual data condition. This is good UX writing discipline that's easy to skip and wasn't skipped here.
3. **The `OsDistributionDonut`'s "Unknown" handling** deliberately sorts unreported-OS agents last in a muted color, protecting the real signal (OS diversity) from being diluted by agents that haven't checked in yet — a small, thoughtful, product-aware detail.

## Priority Issues

**[P1] Severity color diverges between the dashboard KPI card and the donut chart eight lines away.** `pages/index.vue`'s `SEVERITY_COLOR` maps `HIGH: 'red'` (same as CRITICAL) and folds MEDIUM/LOW into `'gray'`, while `VulnerabilitySeverityDonut.vue` correctly uses `HIGH: '#f97316'` (Signal Orange) per DESIGN.md's own documented severity scale (LOW→green, MEDIUM→amber, HIGH→orange, CRITICAL→red). An admin scanning the KPI row sees "everything red," then looks at the donut immediately below and sees a graduated scale for the same data — the two widgets disagree about what the fleet's own severity taxonomy is.
*Why it matters:* This is exactly the moment the product exists for — triage at a glance — and the flagship widget actively degrades it by collapsing the one distinction (HIGH vs CRITICAL) an admin needs first.
*Fix:* Change `SEVERITY_COLOR` in `index.vue` to `HIGH: 'orange', MEDIUM: 'amber', LOW: 'gray'`, matching the donut and DESIGN.md. `Badge.vue` already supports both variants.
*Suggested command:* `/impeccable clarify`

**[P1] Untranslated Romanian string ships on every load of the primary dashboard.** `MetricCard.vue`'s `viewAllLabel` default is `'Vezi tot'`; none of the four KPI-card call sites in `index.vue` override it, so all four top cards read "Vezi tot" while every other widget on the same page uses "View All" / "View all."
*Why it matters:* This is the first screen a user opening the English-language default sees — it reads as a shipped bug, not a design choice, on the single most-viewed surface in the product.
*Fix:* Change the default to `'View all'`.
*Suggested command:* `/impeccable clarify`

**[P2] The six-tab structure duplicates the Overview grid without partitioning anything.** Infrastructure/Security/Automation/Compliance/Observability each re-show a subset of widgets Overview already contains. The tabs cost 6 upfront navigation decisions and communicate "these are different views" when they aren't — Overview alone already answers "what would I click a tab for." A prior effort this session to consolidate this into one unified view exists as an open, unmerged branch (`fix/dashboard-remove-category-tabs`, PR #8) — it never landed in what's currently on disk.
*Why it matters:* Extra navigation cost with no informational payoff is the definition of avoidable cognitive load, and it's compounding with the KPI/donut severity mismatch above — the tabs make the page feel more complex than the underlying information actually is.
*Fix:* Merge PR #8 (or redo the equivalent consolidation against current `main`) so the six-tab structure collapses to one committed Overview.
*Suggested command:* `/impeccable distill`

**[P2] No heartbeat-staleness signal exists anywhere on the flagship surface.** PRODUCT.md Principle #1 states plainly: "the UI should surface 'waiting for the agent' honestly rather than pretend real-time." None of `MetricCard`, `AgentStatusDonut`, or `InfrastructureHealth` show last-heartbeat age or distinguish "agent offline" from "agent hasn't reported since heartbeat's last tick." For a 60-second heartbeat-pull architecture that the product explicitly differentiates itself on, the one screen an admin checks every morning says nothing about it.
*Why it matters:* This is a confirmed product principle, not a nice-to-have — its absence on the dashboard is a gap between what the product promises and what the flagship surface actually does.
*Fix:* Add a last-heartbeat-age indicator (relative time, e.g. "Servers: 2 active · updated 12s ago") to the Servers KPI card or `AgentStatusDonut`.
*Suggested command:* `/impeccable clarify`

**[P3] Every dashboard widget gets a hover-lift affordance whether or not it's clickable.** `global.css`'s `.surface-card:hover` (translateY + shadow-raised) applies to every card via the shared class, including donuts and status widgets that have no card-level link — only their internal "View all" text is clickable. Hovering the whole card promises interactivity that isn't there.
*Why it matters:* Minor, but it trains users to expect clicks that do nothing, which erodes trust in affordances elsewhere on the same page.
*Fix:* Scope the hover-lift to only cards with a card-level click target, or make the whole card clickable when a destination exists.
*Suggested command:* `/impeccable polish`

## Persona Red Flags

**Alex (Power User)** — morning "is anything on fire" check: Alex has to scan all 13 widgets with no way to jump to "what changed since yesterday" — the trend/delta badge exists in code but is wired for the Vulnerabilities KPI card only (and is effectively unreachable there too, since `MetricCard`'s badge-vs-trend logic always prefers severity badges when present). Servers/Jobs/Alerts show sparkline shapes with no anchoring number. Alex also can't distinguish CRITICAL from HIGH on the KPI card at all (P1 above) — forced into a second look at the donut just to triage, which is exactly the kind of extra step Alex abandons over.

**Sam (Accessibility-Dependent User)** — same task via keyboard/screen reader: `AppTabs.vue`'s tab strip is plain `<button>` elements with no `role="tablist"`/`role="tab"`/`aria-selected` — a screen reader announces six unrelated buttons, not a tab group, giving no signal about which view is active or what switching does. On the positive side, severity isn't color-only — badge text (`CRITICAL: 5`) carries the information redundantly, so Sam isn't fully blocked by the P1 color issue, just given a worse KPI-card experience than a sighted user gets from the (correct) donut chart.

## Minor Observations

- `MetricCard.vue` renders values with no thousands-separator (`12345` not `12,345`) — undercuts the system's own Tabular Numerals intent at fleet scale.
- `SecurityOverview.vue`'s "Risk Score: Minimal/Critical" is a client-derived worst-severity-present heuristic (per its own code comment) but is presented with the visual confidence of a real computed score, with no disclosing tooltip.
- `InfrastructureHealth.vue` reuses the CPU/memory/disk 75%/90% percentage thresholds for network latency against a flat 200ms ceiling — an arbitrary carry-over, not a latency-specific scale.

## Questions to Consider

1. If Overview already contains everything the other five tabs show, what does a tab actually buy the admin besides an extra click?
2. Given PRODUCT.md names heartbeat honesty as a confirmed principle, why does the one screen checked every morning have zero staleness affordance across nine widgets?
3. Was the KPI-card vs. donut severity-color divergence intentional simplification, or drift that nobody caught — and if drift, what would catch the next one?
