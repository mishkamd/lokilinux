export const meta = {
  name: "design-audit-r2",
  description: "Round 2 of the LokiLinux frontend design debt: verify every open UI Audit ticket against the code, fix the real ones by area, align DESIGN.md, then land one commit per area",
  phases: [
    { title: "Areas", detail: "per-area verification and targeted fixes for the open UI Audit tickets" },
    { title: "Doc", detail: "align DESIGN.md with the implementation and add the safe guard rules" },
    { title: "Verify", detail: "guard, typecheck, tests, runtime audit" },
    { title: "Residual", detail: "fix whatever the guard or the audit still reports" },
    { title: "Land", detail: "commit per area, comment on every ticket, close what is verified" },
  ],
};

const RESULT = {
  type: "object",
  required: ["tickets", "files", "verdicts", "summary", "checks"],
  properties: {
    tickets: { type: "array", items: { type: "string" } },
    files: { type: "array", items: { type: "string" } },
    verdicts: {
      type: "array",
      items: {
        type: "object",
        required: ["ticket", "status", "evidence"],
        properties: {
          ticket: { type: "string" },
          status: { type: "string" },
          evidence: { type: "string" },
        },
      },
    },
    summary: { type: "string" },
    checks: { type: "string" },
    notes: { type: "string" },
  },
};

// Files another session owns right now. Never edit them, never stage them.
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
  "frontend/stores/compliance.ts",
];

const BASE = [
  "You work in /opt/lokilinux (LokiLinux), a FastAPI + Nuxt monorepo.",
  "How to work:",
  "- Read every assigned ticket first: bb linear issue <KEY>. Each one names the site it is about.",
  "- Verify it against the CURRENT code. A ticket can already be satisfied by a previous round: if it is, do not touch anything for it, just report it as verified with the evidence (file:line or a grep or a guard output).",
  "- If it is still real, fix exactly the named site and nothing else. Minimal diff, no new dependencies, no redesign, existing tokens and primitives only.",
  "- Do NOT do sweeping migrations. This repo has 198 Tailwind radius utilities and 66 rhythm utilities that are documented and intentional; only the specific sites the tickets name are in scope. Changing them all would be a large unreviewed visual change.",
  "- Touch ONLY the files listed in your task, plus the file a named site lives in. Sibling agents edit other files in the same tree at the same time.",
  "- These files belong to another session: never edit them, never stage them; if a ticket needs one, report it as blocked:",
  BUSY.join(", "),
  "- Never run git add, git commit, git push, git stash, git checkout. Never change Linear state (the landing phase does that).",
  "- Before you finish, from /opt/lokilinux/frontend run: node scripts/check-design-system.mjs, then npx vue-tsc --noEmit, then npm test. All three must pass.",
  "- Your final message IS the return value: a JSON object, no prose around it.",
].join("\n");

phase("Areas");
const areas = await parallel([
  () => agent(BASE + [
    "",
    "Area: dashboard widgets and the dashboard page.",
    "Files you own: every file under frontend/components/dashboard/, plus frontend/pages/index.vue.",
    "Assigned tickets: MIS-124 (OS Distribution donut is a hand-rolled SVG, the three siblings use the Unovis primitive), MIS-131 (non-hairline borders, border-border/60), MIS-137 (InfrastructureInventory uses a hand-rolled Select/MultiSelect instead of the Select primitive), MIS-108 (the severity donut value needs tabular numerals and a consistent value typography), MIS-119 (KPI/stat numeral scale), MIS-114 (the last custom pill markup instead of the Badge primitive), MIS-253 (verify the widget tables still fit their card).",
    "Notes: MIS-119 is cross-cutting, so for your area only check the widgets; the doc agent handles the global rule. MIS-108 names VulnerabilitySeverityDonut plus a couple of value/timestamp spots. If a ticket needs a file in components/ui/, report it and stop for that ticket, the next agent owns that folder.",
  ].join("\n"), { label: "A1 - dashboard widgets", schema: RESULT }),

  () => agent(BASE + [
    "",
    "Area: the UI primitives.",
    "Files you own: every file under frontend/components/ui/ (except the chart folder and DataTable.vue, which the next agent owns).",
    "Assigned tickets: MIS-101 (custom bordered containers instead of the Card primitive), MIS-105 (text/search inputs that reimplement the Input primitive), MIS-116 (grid gaps that deviate from gap-3), MIS-122 (a native checkbox instead of the Checkbox primitive), MIS-120 (the login form is double-padded inside the Card body), MIS-121 (the mobile navigation backdrop uses the wrong tint and an unsanctioned backdrop-blur), MIS-124 (the donut sibling), MIS-111 (an actions column that is still sortable), MIS-121 again only if the backdrop lives here.",
    "Notes: keep the primitives themselves token-driven: a primitive is the definition of the system, so the fix for a primitive ticket is usually to make the primitive match the documented spec, not to change every call site.",
  ].join("\n"), { label: "A2 - ui primitives", schema: RESULT }),

  () => agent(BASE + [
    "",
    "Area: the workflow builder, the DataTable and the workflow pages.",
    "Files you own: frontend/components/workflow/, frontend/components/ui/DataTable.vue, frontend/components/ui/chart/, frontend/pages/workflows/, frontend/pages/automation/, frontend/components/JobDetail.vue, frontend/components/PlaybookEditor.vue.",
    "Assigned tickets: MIS-126 (a raw button where a Button or DataTable-row primitive belongs, no focus ring), MIS-129 (interactive controls without a visible focus ring), MIS-99 (the status-to-colour map is duplicated and inconsistent across pages), MIS-100 (fixed grid-cols rows without a responsive breakpoint), MIS-111 (the actions column is still sortable), MIS-120 (the login form double padding, if the card is here), MIS-136 (vertical rhythm that uses mb-4, mb-6 or gap-4 instead of the 12px system, only for the named sites).",
    "Notes: MIS-99 asks for one canonical status-to-colour map. composables/useSeverity.ts is canonical for severity; if no canonical map exists for workflow statuses, add one in composables/ and use it from the pages that own the named sites. Do not migrate files outside your area.",
  ].join("\n"), { label: "A3 - workflow + datatable", schema: RESULT }),

  () => agent(BASE + [
    "",
    "Area: the compliance pages and widgets (except the files another session owns).",
    "Files you own: every file under frontend/pages/compliance/ that is NOT in the busy list, frontend/components/compliance/, frontend/components/ComplianceWizard.vue is busy, do not touch.",
    "Assigned tickets: MIS-109 (ad-hoc warning/error banners instead of the Alert primitive), MIS-115 (destructive inline actions styled as ghost or outline), MIS-125 (page vertical rhythm that deviates from the 12px section gap), MIS-133 (the mb-6 spacing outlier on the remediation execution panel), MIS-134 (status badges sized inconsistently across the admin tables), MIS-135 (sub-minimum text-[9px] labels), MIS-100 (fixed grid-cols rows), MIS-112 (a 32px section rhythm with space-y-8), MIS-116 (grid gaps that deviate from gap-3), MIS-117 (hand-built progress bars, only the ones in files you own: pages/compliance/index.vue is busy, so those three bars are blocked and you report them as blocked).",
  ].join("\n"), { label: "A4 - compliance area", schema: RESULT }),

  () => agent(BASE + [
    "",
    "Area: the observe and security pages.",
    "Files you own: frontend/pages/events/, frontend/pages/signals/, frontend/pages/correlation/, frontend/pages/alerts/, frontend/pages/vulnerabilities/, frontend/pages/jobs/, frontend/pages/incidents/, frontend/pages/topology/, frontend/pages/plugins/, frontend/components/server/, frontend/components/dashboard/ files that A1 did not take, frontend/pages/security/.",
    "Assigned tickets: MIS-98 (the text-primary accent text is missing its dark-mode variant), MIS-108 (value and timestamp typography without tabular numerals), MIS-112 (a 32px section rhythm), MIS-116 (grid gaps), MIS-130 (the launch action is tinted text-success inconsistently), MIS-132 (the primary CTA size is inconsistent between list pages), MIS-134 (status badge sizes), MIS-136 (vertical rhythm for the named sites), MIS-122 (a native checkbox), MIS-135 (sub-minimum labels).",
    "Notes: MIS-132 is one line: every list page uses the same size for its primary action. MIS-98: the accent text must follow the theme, so use the theme-aware token (text-primary-text) exactly as DESIGN.md describes, and never remove a dark variant that is already needed.",
  ].join("\n"), { label: "A5 - observe area", schema: RESULT }),

  () => agent(BASE + [
    "",
    "Area: fleet, agents, admin, account, auth and the app shell.",
    "Files you own: frontend/pages/servers/, frontend/pages/agents/, frontend/pages/account/, frontend/pages/admin/, frontend/pages/auth/, frontend/pages/policies/, frontend/pages/plugins/index.vue, frontend/layouts/, frontend/pages/policies/index.vue, frontend/pages/policies/[id].vue.",
    "Assigned tickets: MIS-113 (the auth wordmark headline uses an unsanctioned display size, text-4xl), MIS-120 (the login form double padding inside the Card body), MIS-121 (the mobile navigation backdrop tint and backdrop-blur), MIS-128 (the Iceberg display face used at undocumented sizes), MIS-134 (status badge sizes across the admin tables), MIS-136 (vertical rhythm for the named sites), MIS-125 (page vertical rhythm), MIS-116 (grid gaps), MIS-122 (a native checkbox), MIS-135 (sub-minimum labels), MIS-119 (the KPI numeral scale, only for the sites in your area).",
    "Notes: DESIGN.md says the display face is used at one size only (the display wordmark 1.5rem, the page title 1.25rem). Fix the size, do not change the face. The auth wordmark is the one sanctioned exception for a larger wordmark, so check the doc before changing it.",
  ].join("\n"), { label: "A6 - fleet + shell", schema: RESULT }),
]);

phase("Doc");
const doc = await agent([
  "You work in /opt/lokilinux. Documentation and guard only: no component, page or layout file may be edited.",
  "Files you own: DESIGN.md and frontend/scripts/check-design-system.mjs.",
  "",
  "Task 1 - make DESIGN.md true without changing the app's look. Two claims in the doc are not what the code does, and the code is the intended look:",
  "  a) The radius section lists one family (sm 10, md 12, lg 16, xl 20, 2xl 24, full 9999) but the code also uses Tailwind's 4px scale (rounded, rounded-sm, rounded-md, rounded-lg) for small chrome: icon squares, chips, inline code blocks. State the two tiers explicitly: the token family for the primitives (button 16, input 10, card 12) and the 4px Tailwind steps for small chrome. Keep the One Radius Family Rule but make it describe the real rule.",
  "  b) The vertical rhythm section says 12px section gaps, while the code uses mb-4 (16px) and gap-4 in many places. The doc also says 12-16px gaps. Rewrite the rhythm rule to the range the code actually uses, and say which one is the default for stacked sections.",
  "  c) If a type size or a numeral scale in the doc contradicts the code (the KPI headline role, the widget stat role), state the code's scale.",
  "Do not remove any rule that the code satisfies.",
  "",
  "Task 2 - add only the guard rules that are cheap and safe (a rule that would flag hundreds of legitimate sites is NOT safe and must be skipped):",
  "  - ban sub-minimum font sizes: text-[9px] and smaller (the doc's smallest step is the badge-micro 0.625rem).",
  "  - ban the 32px section rhythm: space-y-8.",
  "  - ban non-hairline borders on widget chrome: border-border/60 and border-border/40.",
  "  - ban the unsanctioned display sizes: text-4xl and larger, except on the auth wordmark (the one sanctioned exception).",
  "  Keep the existing rules, the report format and the exit behaviour untouched. If one of the four rules would fire on more than a handful of sites, do not add it; say so in your report instead.",
  "Then run from /opt/lokilinux/frontend: node scripts/check-design-system.mjs, npx vue-tsc --noEmit, npm test. Report the exact outcome of each.",
  "If a new guard rule fires on a site, fix that site only if it is inside a file you own (DESIGN.md, the guard). Otherwise report the site as a violation for the residual phase.",
  "Never run git add, git commit, git push. Never change Linear state.",
  "Your final message IS the return value: a JSON object with tickets, files, verdicts, summary, checks, notes.",
].join("\n"), { label: "D1 - doc + guard", schema: RESULT });

phase("Verify");
const verify = await parallel([
  () => agent([
    "You work in /opt/lokilinux. Verification only, no file edits, no git commands.",
    "Run from /opt/lokilinux/frontend: node scripts/check-design-system.mjs, then npx vue-tsc --noEmit, then npm test.",
    "Report the exact outcome of each of the three, and every violation the guard reports (file, line, rule).",
    "Your final message IS the return value: a JSON object with tickets, files, verdicts, summary, checks, notes.",
  ].join("\n"), { label: "V1 - gates" }),

  () => agent([
    "You work in /opt/lokilinux. Runtime verification only, no file edits, no git commands.",
    "The stack is running: frontend on http://127.0.0.1:3000, credentials in /opt/lokilinux/.env (ADMIN_EMAIL, ADMIN_PASSWORD).",
    "Use the agent-browser CLI (installed). Log in, then measure at 1440x900 and 390x844, in the dark and the light theme (localStorage key lokilinux-color-mode):",
    "1. interactive controls under 24x24 (ignore the 16px checkbox, whose hit area is 32px, and the skip link),",
    "2. every table: table.scrollWidth versus its wrapper clientWidth,",
    "3. interactive controls without an accessible name,",
    "4. text contrast below 4.5:1 on any leaf text node.",
    "Report the raw numbers per page and per theme, and list the concrete remaining offenders.",
    "Your final message IS the return value: a JSON object with tickets, files, verdicts, summary, checks, notes.",
  ].join("\n"), { label: "V2 - runtime audit" }),
]);

phase("Residual");
const residual = await agent([
  "You work in /opt/lokilinux. Cleanup pass after a multi-agent design round.",
  "The gates and the runtime audit of the current tree:",
  JSON.stringify(verify),
  "",
  "Fix only what those two reports flag as a defect, and only in files no other session owns:",
  BUSY.join(", "),
  "Scope: guard violations, sub-24px interactive targets, tables that scroll horizontally, interactive controls without an accessible name, text under 4.5:1 contrast.",
  "Then re-run from /opt/lokilinux/frontend: node scripts/check-design-system.mjs, npx vue-tsc --noEmit, npm test.",
  "Never run git add, git commit, git push. Never change Linear state.",
  "Your final message IS the return value: a JSON object with tickets, files, verdicts, summary, checks, notes.",
].join("\n"), { label: "R1 - residual fixes", schema: RESULT });

phase("Land");
const land = await agent([
  "You work in /opt/lokilinux. You are the landing phase: the fixes are done and verified, you commit them and you update Linear.",
  "",
  "Agent results:",
  JSON.stringify({ areas, doc, residual }),
  "",
  "Steps:",
  "1. One commit per agent (area agents and the doc agent and the residual agent). For each: stage ONLY the files that agent reported (git add with explicit paths, never git add -A, never git add .), then commit with a conventional message in the repo style: fix(frontend): <short Romanian summary> (MIS-xxx, MIS-yyy). The body is Romanian with a short bullet list of what changed.",
  "2. If a file in your list also contains changes from another session, do not stage it: run git diff on the file and skip it if the diff has hunks unrelated to the agent summary; report it as blocked.",
  "3. For every ticket the agents reported: add a comment with what changed or what verified it (file:line, grep or guard output) and move it to Done. If an agent reported a ticket as blocked or as still violating, do NOT move it to Done: move it back to Backlog and say in the comment exactly what is left.",
  "4. Never edit a file. Never amend. Never push.",
  "",
  "Your final message IS the return value: a JSON object with tickets, files, verdicts (per ticket: ticket, sha or empty, state, evidence), summary, checks, notes.",
].join("\n"), { label: "L1 - land" });

return { areas, doc, verify, residual, land };
