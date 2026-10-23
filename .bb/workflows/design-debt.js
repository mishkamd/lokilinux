export const meta = {
  name: "design-debt",
  description: "Close the LokiLinux frontend design debt: parallel fixers per ticket, then verify, fix residual, and land one commit per ticket",
  phases: [
    { title: "Wave A", detail: "hit areas, dashboard widget overflow, close-without-code tickets" },
    { title: "Wave B", detail: "severity map, shadows, hand-rolled textareas, progress bars" },
    { title: "Wave C", detail: "empty states, headers and labels, section titles" },
    { title: "Verify", detail: "design-system guard, typecheck, tests, runtime audit" },
    { title: "Residual", detail: "fix whatever the runtime audit still reports" },
    { title: "Land", detail: "one commit per ticket, Linear comment, move to In Review" },
  ],
};

const RESULT = {
  type: "object",
  required: ["ticket", "files", "summary", "checks"],
  properties: {
    ticket: { type: "string" },
    files: { type: "array", items: { type: "string" } },
    summary: { type: "string" },
    checks: { type: "string" },
    notes: { type: "string" },
  },
};

// Files another session is editing right now. Never edit them, never stage them.
const BUSY = [
  "frontend/components/ComplianceWizard.vue",
  "frontend/pages/compliance.vue",
  "frontend/pages/compliance/drift/index.vue",
  "frontend/pages/compliance/findings/index.vue",
  "frontend/pages/compliance/index.vue",
  "frontend/pages/compliance/policies/[id].vue",
  "frontend/pages/compliance/policies/index.vue",
  "frontend/pages/compliance/rules/[id].vue",
  "frontend/pages/compliance/rules/index.vue",
  "frontend/stores/compliance.test.ts",
  "frontend/stores/complinux.ts",
  "frontend/stores/compliance.ts",
];

const BASE = [
  "You work in /opt/lokilinux (LokiLinux), a FastAPI + Nuxt monorepo. Read the ticket first: bb linear issue <KEY>.",
  "Ground rules:",
  "- Touch ONLY the files listed in your task. Sibling agents edit other files in the same tree at the same time.",
  "- These files are owned by another session, do not edit them, do not stage them, and if your task needs one, report the site as blocked:",
  BUSY.join(", "),
  "- Never run git add, git commit, git push, git stash, git checkout. Never change Linear state except where the task says so explicitly.",
  "- Keep the diff minimal: no new dependencies, no redesign, no drive-by refactors. Use the existing tokens, primitives and cva variants.",
  "- Before you finish, from /opt/lokilinux/frontend run: node scripts/check-design-system.mjs, then npx vue-tsc --noEmit, then npm test. All three must pass.",
  "- Your final message IS the return value: a JSON object, no prose around it.",
].join("\n");

phase("Wave A");
const waveA = await parallel([
  () => agent(BASE + [
    "",
    "Task: MIS-252, part 1 of 2 (another agent owns the component files listed in the ticket, do not touch them).",
    "Files you own: frontend/pages/admin/agent-policies.vue, frontend/pages/workflows/runbooks.vue, frontend/pages/correlation/index.vue, frontend/pages/compliance/file-integrity/index.vue, frontend/pages/vulnerabilities/[cve].vue",
    "Fix: every <button> in these files that renders under 24px tall gets a hit area of at least 24x24 while keeping the visual size. Use the pattern already in components/ui/DataTable.vue: the sort button got py-1 -my-1, so the box grows 8px and the negative margin cancels the layout shift.",
    "Acceptance: in these files no button renders under 24x24, except the 16px checkbox (its hit area is already 32px via a before pseudo-element) and the skip link.",
  ].join("\n"), { label: "A1 - MIS-252 pages", schema: RESULT }),

  () => agent(BASE + [
    "",
    "Task: MIS-252, part 2 of 2 (another agent owns the page files, do not touch them).",
    "Files you own: frontend/components/ui/SavedViews.vue, frontend/components/ui/TagInput.vue, frontend/components/workflow/WorkflowProperties.vue, frontend/components/workflow/WorkflowEdgeProperties.vue, frontend/scripts/check-design-system.mjs",
    "Fix 1: the same hit-area fix as part 1 for every button under 24px in the four components.",
    "Fix 2: add a rule to the design-system guard in frontend/scripts/check-design-system.mjs: an interactive tag (button, a, NuxtLink) that carries a small text class (text-xs) and declares no size at all (no h-*, min-h-*, size-*, py-*, p-*) renders under 24px and is a violation. The message points at the 24px target floor and the py-1 -my-1 pattern. Keep the existing rules and the report format untouched.",
    "Fix 2b: one file is owned by the in-flight compliance work and still violates the new rule: frontend/pages/compliance/rules/[id].vue. Add it to a small documented exception list in the guard (a const with a comment naming MIS-252 and saying it must be removed when the compliance work lands), so the guard stays green. Do not edit that file.",
    "Negative test: the rule fires on a text-xs button with no size class and does not fire on a text-xs link that has a size class.",
  ].join("\n"), { label: "A2 - MIS-252 components + guard", schema: RESULT }),

  () => agent(BASE + [
    "",
    "Task: MIS-253.",
    "Files you own: every file under frontend/components/dashboard/. Two jobs: (1) the table overflow below, (2) every widget link that renders under 24px (the View all -> style links, text-xs with no size class) gets a hit area of at least 24x24, same py-1 -my-1 pattern. Do not touch frontend/components/dashboard/VulnerabilitySeverityDonut.vue, another agent owns it in the next wave.",
    "Context: on the dashboard, a widget table renders 1061px wide inside a card of 550px, so the widget gets a horizontal scrollbar at 1440px. The DataTable already has column visibility preferences and a noSort flag; use them instead of new markup. A widget may also span two grid columns if that is the honest fix.",
    "Acceptance: at 1440px no dashboard widget has table.scrollWidth greater than its wrapper clientWidth, and no data is silently dropped (if a column is hidden, the widget says how to see everything).",
  ].join("\n"), { label: "A3 - MIS-253 dashboard widgets", schema: RESULT }),

  () => agent([
    "You work in /opt/lokilinux. This task is Linear bookkeeping only, no file edits, no git commands.",
    "Task: six UI Audit tickets look already satisfied by the design-system guard or by the current code: MIS-106 (literal radius), MIS-118 (hardcoded palette colours), MIS-123 (native window.confirm), MIS-100 (fixed grid-cols without a responsive breakpoint), MIS-108 (KPI numeral scale / tabular numerals), MIS-114 (custom pill markup instead of the Badge primitive).",
    "For each one: verify it against the CURRENT code (read the ticket, grep the tree, run the guard: cd frontend && node scripts/check-design-system.mjs). If it is genuinely satisfied, add a comment with the concrete evidence and move it to Done (bb linear move <KEY> Done). If it is NOT satisfied, leave the state alone and say in your summary exactly which sites still violate it.",
    "Never close a ticket you could not verify with a file, a grep result or a guard output.",
    "Your final message IS the return value: a JSON object with ticket, files (empty array), summary, checks, notes.",
  ].join("\n"), { label: "A4 - close 6 without code", schema: RESULT }),
]);

phase("Wave B");
const waveB = await parallel([
  () => agent(BASE + [
    "",
    "Task: MIS-97.",
    "Files you own: frontend/pages/workflows/index.vue, frontend/components/dashboard/VulnerabilitySeverityDonut.vue",
    "Fix: both files define a local SEVERITY_COLOR map. The canonical one is in frontend/composables/useSeverity.ts. Replace the local maps with the canonical composable and keep the rendered colours identical.",
    "Acceptance: no second severity-to-colour map exists outside composables/useSeverity.ts, and the dashboard still shows the same severity colours.",
  ].join("\n"), { label: "B1 - MIS-97 severity map", schema: RESULT }),

  () => agent(BASE + [
    "",
    "Task: MIS-110.",
    "Files you own: frontend/pages/vulnerabilities/list.vue",
    "Fix: replace the foreign shadow utility (hover:shadow-md) with the shadow vocabulary from DESIGN.md (the --shadow-surface, --shadow-raised, --shadow-overlay, --shadow-dialog tokens).",
    "Acceptance: no foreign shadow utility remains in the file, and the card still reads as raised on hover.",
  ].join("\n"), { label: "B2 - MIS-110 shadows", schema: RESULT }),

  () => agent(BASE + [
    "",
    "Task: MIS-102, part 1.",
    "Files you own: frontend/pages/automation/ansible/playbooks/[id].vue, frontend/pages/automation/ansible/playbooks/index.vue, frontend/pages/automation/ansible/templates/index.vue",
    "Fix: replace every hand-rolled <textarea> with the Textarea primitive in frontend/components/ui (it carries the right radius, focus ring and height). Keep the model binding, the rows attribute and any monospace class.",
    "Acceptance: no raw <textarea> element remains in these three files.",
  ].join("\n"), { label: "B3 - MIS-102 ansible textareas", schema: RESULT }),

  () => agent(BASE + [
    "",
    "Task: MIS-102, part 2.",
    "Files you own: frontend/pages/compliance/baselines/index.vue, frontend/pages/compliance/baselines/[id].vue, frontend/pages/compliance/remediation/index.vue, frontend/pages/compliance/remediation/[id].vue, frontend/pages/compliance/file-integrity/index.vue, and any other compliance page with a raw <textarea> that is NOT in the busy list.",
    "Fix: replace every hand-rolled <textarea> with the Textarea primitive in frontend/components/ui, keeping the model binding, the rows attribute and any monospace class.",
    "Acceptance: no raw <textarea> element remains in the files you own.",
  ].join("\n"), { label: "B4 - MIS-102 compliance textareas", schema: RESULT }),

  () => agent(BASE + [
    "",
    "Task: MIS-117.",
    "Files you own: every page that hand-builds a progress bar with a width percentage, except the busy files (frontend/pages/compliance/index.vue is busy, so report its two bars as blocked instead of editing it).",
    "Fix: use the Progress primitive in frontend/components/ui/Progress.vue instead of a div with an inline width style.",
    "Acceptance: no inline width-percentage progress bar remains in the files you own, and each replaced bar keeps its value and colour.",
  ].join("\n"), { label: "B5 - MIS-117 progress bars", schema: RESULT }),
]);

phase("Wave C");
const c1 = await agent(BASE + [
  "",
  "Task: MIS-96.",
  "Files you own: every page and widget that renders an empty, loading or error state as bare text, except the busy files.",
  "Fix: use the Skeleton, EmptyState and Alert primitives that already exist in frontend/components/ui for those states. Keep the same copy and the same conditions.",
  "Acceptance: no empty/loading/error state is rendered as a bare paragraph any more.",
].join("\n"), { label: "C1 - MIS-96 empty states", schema: RESULT });

const c2 = await agent(BASE + [
  "",
  "Task: MIS-103 + MIS-104 + MIS-107.",
  "Files you own: the content pages that build their header without the PageHeader primitive (frontend/pages/agents/index.vue, frontend/pages/security/index.vue, frontend/pages/workflows/index.vue, frontend/pages/workflows/[id].vue, frontend/pages/vulnerabilities/index.vue, and any other non-busy page that uses an ad-hoc h2 instead of PageHeader), plus the three unlabelled search inputs (frontend/pages/admin/users/index.vue, frontend/pages/admin/agent-policies.vue, frontend/pages/compliance/rules/index.vue is busy, so report that one as blocked), plus the pages that author section headings ad-hoc instead of the .section-title role.",
  "Fix: use the PageHeader primitive (title, description, actions slot) for the page header, give every form control a programmatic accessible label (aria-label or a real label element), and use the .section-title class for section headings.",
  "Acceptance: those pages render a PageHeader, no input is without an accessible name, and section headings use the shared role class.",
].join("\n"), { label: "C2 - MIS-103/104/107 headers and labels", schema: RESULT });

phase("Verify");
const verify = await parallel([
  () => agent([
    "You work in /opt/lokilinux. Verification only, no file edits, no git commands.",
    "Run from /opt/lokilinux/frontend: node scripts/check-design-system.mjs, then npx vue-tsc --noEmit, then npm test.",
    "Report the exact outcome of each of the three (pass or fail, plus the failure output if any).",
    "Your final message IS the return value: a JSON object with ticket, files, summary, checks, notes.",
  ].join("\n"), { label: "V1 - guard typecheck tests" }),

  () => agent([
    "You work in /opt/lokilinux. Runtime verification only, no file edits, no git commands.",
    "The stack is already running: the frontend is on http://127.0.0.1:3000, credentials in /opt/lokilinux/.env (ADMIN_EMAIL and ADMIN_PASSWORD).",
    "Use the agent-browser CLI (already installed). Log in, then measure at 390x844 and at 1440x900, in the dark theme and in the light theme (localStorage key lokilinux-color-mode):",
    "1. every interactive control under 24x24 (button, a, input, select, textarea, role=button): report the selector, the label and the size, but ignore the 16px checkbox (its hit area is 32px) and the skip link.",
    "2. every table: table.scrollWidth versus the wrapper clientWidth, on /servers, /jobs, /alerts, /incidents, /compliance and on the dashboard widgets.",
    "3. every interactive control without an accessible name (no aria-label, no label element, no text).",
    "4. text contrast below 4.5:1 on any leaf text node.",
    "Report the raw numbers, per page and per theme, and list the concrete remaining offenders.",
    "Your final message IS the return value: a JSON object with ticket, files, summary, checks, notes.",
  ].join("\n"), { label: "V2 - runtime audit" }),
]);

phase("Residual");
const residual = await agent([
  "You work in /opt/lokilinux. You are the cleanup pass after a multi-agent design fix round.",
  "Here is the runtime audit of the result:",
  JSON.stringify(verify),
  "Fix only what the audit still reports as a defect, and only in files no other session is editing:",
  "frontend/components/ComplianceWizard.vue, frontend/pages/compliance.vue, frontend/pages/compliance/drift/index.vue, frontend/pages/compliance/findings/index.vue, frontend/pages/compliance/index.vue, frontend/pages/compliance/policies/[id].vue, frontend/pages/compliance/policies/index.vue, frontend/pages/compliance/rules/[id].vue, frontend/pages/compliance/rules/index.vue, frontend/stores/compliance.test.ts, frontend/stores/compliance.ts",
  "Scope: sub-24px interactive targets, tables that scroll horizontally, interactive controls without an accessible name, text under 4.5:1 contrast.",
  "Then re-run from /opt/lokilinux/frontend: node scripts/check-design-system.mjs, npx vue-tsc --noEmit, npm test.",
  "Never run git add, git commit, git push. Never change Linear state.",
  "Your final message IS the return value: a JSON object with ticket, files, summary, checks, notes.",
].join("\n"), { label: "R1 - residual fixes", schema: RESULT });

phase("Land");
const land = await agent([
  "You work in /opt/lokilinux. You are the landing phase. Everything below is already implemented and verified; your job is to commit it, one commit per ticket, and to update Linear.",
  "",
  "Results of the fix agents:",
  JSON.stringify({ waveA, waveB, waveC: [c1, c2], residual }),
  "",
  "Steps:",
  "1. For each distinct ticket in the results above: stage ONLY the files that agent reported for that ticket (git add with explicit paths, never git add -A, never git add .), then commit with a conventional message in the repo style: fix(frontend): <short Romanian summary> (MIS-xxx), body in Romanian with a short bullet list of what changed.",
  "2. If a file in your list also contains changes from another session, do not stage it: run git diff on the file, and if the diff contains hunks unrelated to the agent summary, skip that file and report it as blocked.",
  "3. After each commit: bb linear comment <KEY> \"<what changed, files, commit sha>\" and bb linear move <KEY> \"In Review\".",
  "4. The agent A4 task already closed some tickets: do not touch them again.",
  "5. Do not change any file. Do not amend. Do not push.",
  "",
  "Your final message IS the return value: a JSON object with ticket, files, summary (a per-ticket table: ticket, sha, message, state), checks, notes (anything blocked or failed).",
].join("\n"), { label: "L1 - land commits" });

return { waveA, waveB, waveC: [c1, c2], verify, residual, land };
