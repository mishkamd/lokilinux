---
title: "Enterprise Compliance Product — domain clarification, UX, and gap closure"
date: 2026-08-23
type: feature
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
product_contract_source: ce-plan-bootstrap
---

# Enterprise Compliance Product — domain clarification, UX, and gap closure

## Summary

LokiLinux already has a substantial, production-hardened compliance core: 24 agent collectors reporting BLAKE3-hashed normalized facts, a Go hot-path service (snapshot ingest → drift detection → CEL rule evaluation → scoring), versioned baselines, remediation with verification, and a rule catalog with framework mappings. This plan does **not** rebuild any of it.

What it ships instead is the missing **product layer**: a browsable Findings experience (today evaluations are visible only as per-rule coverage aggregates), a first-class **Standards** page with honest executable-vs-reference coverage, explicit **UNKNOWN** evaluation semantics, a severity-**weighted score**, granular **RBAC**, an enterprise **Overview dashboard**, a guided **Policy wizard**, and the **cleanup of confirmed dead concepts** — all while freezing v1 behavior and reusing every existing engine.

Ten phases, each independently shippable and verifiable; no phase breaks the previous one.

## Problem Frame

- **In scope:** dead-code removal; Configuration/Compliance separation at UI/API naming level; Standards page + honest coverage; rule states incl. `REFERENCE_ONLY`; Findings read-model + detail UI; UNKNOWN verdicts; weighted scoring; granular permissions mapped onto existing roles; Overview aggregate endpoint + dashboard; policy creation wizard; remediation mode settings (MONITOR/ASSISTED/AUTOMATIC); reporting feature-gating; incident integration boundary stub.
- **Out of scope:** any engine rewrite (`ComplianceEngineV2` etc. forbidden); agent collector changes; multi-tenancy implementation (only tenant-readiness preserved); Git/IaC sync; Configuration Profiles implementation (separate plan — split-plan document); workflow YAML changes.
- **Hard constraints:** `/api/v1/compliance/*` existing endpoints keep their contracts; published `yaml_source`s / immutable snapshots untouched; all existing tests stay green after every phase.

## Requirements

- R1: An administrator can open **Findings**, filter by severity/domain/rule/host/result/time, open one finding, see expected vs observed vs evidence vs snapshot, and act on it (acknowledge / suppress-with-reason / request exception / start remediation) without understanding internals.
- R2: A **Standards** page lists every framework+version with total rules, executable rules, reference-only rules, and execution coverage %; reference-only rules never contribute to scores, findings, or "coverage".
- R3: Rules carry an explicit status ∈ {ACTIVE, DISABLED, REFERENCE_ONLY, DEPRECATED}; only ACTIVE+CEL rules evaluate.
- R4: Evaluations produce PASS / FAIL / NOT_APPLICABLE / **UNKNOWN**; UNKNOWN has a reason ("required fact not collected") and is never counted as PASS anywhere.
- R5: The score is severity-weighted (CRITICAL=10, HIGH=5, MEDIUM=2, LOW=1), exposed with overall/category/severity breakdown, and reports an unknown-share so it cannot silently look complete.
- R6: Every sensitive compliance route enforces granular permissions (`compliance.view`, `…policies.manage`, `…exceptions.approve`, `…remediation.execute`, …) mapped deterministically onto the five existing roles.
- R7: One aggregate **Overview** endpoint powers the enterprise dashboard (overall %, findings by severity, systems compliant/at-risk/non-compliant/unknown, top failed controls/servers, recent assessments).
- R8: A new-policy wizard (8 steps) works over existing APIs with sensible defaults.
- R9: Remediation modes MONITOR/ASSISTED/AUTOMATIC exist as policy-level settings; AUTOMATIC additionally requires the global kill-switch from the Autopilot design and never runs outside maintenance windows.
- R10: Reporting keeps JSON/CSV always; XLSX/PDF become feature-gated (settings flag).
- R11: Confirmed dead concepts are removed or explicitly quarantined, with repo-wide reference checks before each removal.
- R12: All existing compliance tests remain green in every phase; new behavior has unit + integration tests per the strategy below.

## Key Technical Decisions

- KTD1 (**Findings = read-model, not new tables**): `GET /compliance/findings` is a query over `rule_evaluations` joined to `agents`/`compliance_rules` (result=FAIL default view). Zero migration, zero duplication; the "finding" is a projection, its lifecycle fields (`acknowledged_*`) already live where possible on the evaluation row or via audit. Alternative (new `findings` table) rejected: duplicates `rule_evaluations` 1:1.
- KTD2 (**Rule status derived then materialized**): `status` column added to `compliance_rules`; backfill derives it from `is_enabled`+`check_source` (`is_enabled=false → DISABLED`, `check_source='OVAL_UNMAPPED' → REFERENCE_ONLY`, else ACTIVE). Evaluator skips non-ACTIVE before CEL compilation; scorer counts only ACTIVE.
- KTD3 (**UNKNOWN computed at evaluation time**): `rules/engine.go` gains `Verdict{Result: UNKNOWN, Reason}` produced when any evidence-path required by the rule is absent from facts (paths already declared per rule via `evidencePathsForRules`). NOT_APPLICABLE stays platform-derived (`scope.PlatformID`). Scoring denominators exclude UNKNOWN but expose `unknown_count`.
- KTD4 (**Weighted score additive**): new nullable columns `weighted_score NUMERIC(5,2)` + `severity_breakdown JSONB` on `compliance_scores`; legacy `score` keeps being written unchanged for one release (consumers switch, then legacy becomes derived). No destructive change.
- KTD5 (**Permissions = table-driven mapping over roles**): a single `PERMISSIONS` registry maps each permission to allowed roles (ADMIN→all; AUDITOR→view/export only; …). `require_permission("x")` FastAPI dependency resolves role→permissions; routes migrate incrementally; role semantics never change for existing callers.
- KTD6 (**Standards read-only aggregation first**): the Standards page is pure aggregation over existing `compliance_frameworks→versions→controls→rule_mappings` + rule statuses. Framework `publisher/status/description` columns added nullable (no backfill needed). Creating custom standards in-UI is out of scope.
- KTD7 (**Importer quarantined, not deleted**): `POST /policy-sets/import` (XCCDF) keeps working but imported rules land with `status=REFERENCE_ONLY` + `is_enabled=false` and the UI labels the source "Reference catalog — not executable". A follow-up may move it to CLI; API contract preserved meanwhile.
- KTD8 (**Remediation modes = settings, not schema fork**): policy-level JSONB `remediation {mode, allowed[], forbidden[]}` on `policy_sets` (nullable → defaults ASSISTED); AUTOMATIC additionally gated by global `compliance.auto_remediation_enabled` (Autopilot S2/A2). MONITOR = findings-only, no plan creation path.
- KTD9 (**Overview = one cached aggregate**): `GET /compliance/overview` computes the §R7 payload in a single service call with Redis cache TTL 60s; heavy sub-queries reuse existing dashboard SQL patterns; no cross-request N+1.
- KTD10 (**Dead code removed behind reference checks**): each removal item gets a scripted grep across backend/frontend/tests/migrations/docs; anything with a live consumer is quarantined (documented as reserved) instead of deleted.

## Current State Audit (verified, commit `77c4220`)

| Spec concept | State | Evidence |
|---|---|---|
| Agent collectors / facts | EXISTS — do not touch | `agent/internal/compliance/*_collector.go` (24 domains), canonical BLAKE3 |
| Ingest pipeline | EXISTS | `services/compliance/internal/ingest/ingest.go:100` verify→store→drift→evaluate→score |
| Drift incidents | EXISTS (+dead states) | `ingest.go:221-323`; dead: `IN_REMEDIATION`/`EXCEPTION` writers |
| Rules / CEL | EXISTS | `rules/engine.go`; constants `workflow_compiler`-adjacent sets in Go service |
| Policy sets / assignments | EXISTS | `routers/compliance/policy_engine.py` (16 endpoints) |
| Assessments | EXISTS | `ingest/assessment.go` — evaluation-over-snapshot semantics documented |
| Findings browsing | MISSING (data exists) | `rule_evaluations` surfaced only as coverage aggregates (`policy_engine.py:194-250`, `rules/[id].vue`) |
| Standards | PARTIAL — tables exist, no product surface | `models/compliance_framework.py` (framework→version→control→mapping); importer produces inert OVAL_UNMAPPED rules |
| UNKNOWN | MISSING | evaluator emits PASS/FAIL/N_A only |
| Weighted score | MISSING | `computeCategoryScores` unweighted |
| Exceptions | EXISTS (+unwired propagation) | `routers/compliance/exceptions.py`; drift EXCEPTION state unset |
| Remediation ASSISTED | EXISTS | plans/actions/windows/verification workers |
| Remediation AUTOMATIC | DESIGNED, not built | `docs/modules/10-compliance-autopilot.md` A2 |
| Granular RBAC | MISSING | roles only; `require_role` absent on read routes (`dashboard.py`, `inventory.py`, `file_integrity.py`) |
| Dead inventory | PRESENT | `DESIRED_STATE` (`detector.go:18`, zero producers), `changed_by_user`/`root_cause` (`models/drift.py:34-35`, zero writers), NATS topics `nats_topics.py:35-36` (no producer/consumer), `trigger_type` AUTOMATIC enum unused until Phase 8 |

Reusable-as-is (explicitly frozen): collectors, facts schema, hashing, ingest consumer + Term-permanent handling, drift detector/correlation, baseline resolver, assessment poller, remediation workers, workflow/Ansible execution, audit plumbing, CursorPage conventions.

## Implementation Units

### U1 — Phase 1: Dead-code cleanup

**Goal:** Remove confirmed-dead concepts with verifiable safety; quarantine the rest explicitly.
**Requirements:** R11
**Dependencies:** none
**Files:** `services/compliance/internal/drift/detector.go`, `backend/lokilinux/models/drift.py`, `backend/lokilinux/schemas/drift.py`, `backend/lokilinux/nats_topics.py`, `docs/modules/04-compliance.md`

**Tasks:**
1. For each candidate run a scripted reference sweep (backend Go+Py, frontend, tests, migrations, docs):
   `DESIRED_STATE`, `changed_by_user`, `root_cause`, NATS topics `.drift.detected`/`.score.updated`.
2. Remove zero-consumer items: delete constant + enum comment references; drop columns via **new Alembic migration** using `ALTER TABLE … DROP COLUMN IF EXISTS` on the hypertable (safe: no reader/writer). Keep `correlation_key` etc. untouched.
3. Quarantine-with-documentation items: NATS topics get a "reserved — Autopilot N3" code comment + doc note instead of deletion (they are the designed future boundary).
4. Do NOT touch `trigger_type` AUTOMATIC (consumed by U7) or drift dead *states* (fixed by U6 wiring, not removal).
5. Tests: go test ./… ; pytest backend/tests/unit -q; vitest run; plus a new pytest asserting `/compliance/drift-events` schema no longer exposes removed fields.

### U2 — Phase 2: Domain separation at product surface

**Goal:** Configuration and Compliance become visibly separate products; cross-links replace coupling.
**Requirements:** R12 (no behavior break)
**Dependencies:** none
**Files:** `frontend/layouts/*` nav config, `frontend/pages/configuration/**` (new shell reusing compliance components where read-only), `backend/lokilinux/api/v1/__init__.py` (optional `/configuration/*` alias routers), docs.

**Tasks:**
1. Navigation splits into **Configuration** (Baselines, Drift, History; Profiles placeholder linking to split-plan) and **Compliance** (Standards, Policies, Findings, Assessments, Exceptions, Reports).
2. Add thin alias routers `GET /configuration/baselines|drift` delegating to existing services (contract-compatible responses) so future divergence doesn't force UI rewrites.
3. Finding detail gains `[View configuration drift]` link when the same fact has an open drift event (join on agent+domain, evidence path prefix match) — display-only.
4. No engine moves; no table renames.

### U3 — Phase 3a: Rule status materialization

**Goal:** Explicit rule lifecycle states; reference-only rules provably inert.
**Requirements:** R3
**Dependencies:** none
**Files:** migration, `models/compliance_rule.py`, `rules/engine.go` skip logic, `policy_engine.py`, rules UI pages, curated loader.

**Tasks:**
1. Migration: add `status VARCHAR(20)` default `'ACTIVE'`; backfill per KTD2; index `(status)` partial on ACTIVE for hot queries.
2. Go evaluator: skip non-ACTIVE before compile cache lookup; REFERENCE_ONLY/DEPRECATED never reach `evaluateAndRecord`.
3. Scorer (`computeCategoryScores`) filters ACTIVE only; coverage endpoints report `executable` vs `reference_only` counts separately.
4. Curated loader writes `status='ACTIVE'`; importer path (U8) writes `REFERENCE_ONLY`.
5. API: rule responses expose `status`; list filter `?status=`; UI badges (gray REFERENCE_ONLY, amber DISABLED).
6. Tests: unit (backfill mapping matrix), integration (REFERENCE_ONLY excluded from score & coverage numerator).

### U4 — Phase 3b+4: Findings read-model + detail + UNKNOWN

**Goal:** The operational findings surface and honest evaluation semantics.
**Requirements:** R1, R4
**Dependencies:** U3 (status filter)
**Files:** `routers/compliance/findings.py` (new), `schemas/compliance_finding.py` (new), `rules/engine.go`, `ingest.go` passthrough of unknown reason, frontend `stores/compliance.ts`, `pages/compliance/findings/index.vue` + `[id].vue` (new).

**Tasks:**
1. Backend read-model: `GET /compliance/findings?severity=&domain=&rule_id=&agent_id=&result=FAIL&since=&cursor=` → CursorPage over latest `rule_evaluations` per (agent, rule) joined hostname/rule key/severity; `GET /compliance/findings/{agent_id}/{rule_id}/{time}` returns full row + evidence + snapshot pointer (`inventory_snapshots`→blob hash) + linked open drift event if any.
2. Actions wired to existing flows: acknowledge/suppress reuse drift-style audit patterns where they map to evaluations (acknowledge stored as evaluation annotation column `acknowledged_by/at` nullable — additive migration); exception creation prefills rule+agent; remediate opens existing plan flow pre-populated.
3. UNKNOWN: extend Go `Verdict.Result` enum with `UNKNOWN` + `Reason string`; produced when required evidence paths missing from facts (paths from `evidencePathsForRules`); persisted in `rule_evaluations.result` (value `UNKNOWN` — check constraint widened in migration); scoring/UI treat distinctly (U5).
4. Frontend findings list: severity chips, domain/rule/host filters, relative times, bulk acknowledge (scoped ≤100); detail page renders the spec's finding card incl. `Why: reason` block for UNKNOWN with last-successful-collection timestamp from snapshots.
5. Tests: unit UNKNOWN matrix (missing single/multiple paths; platform N_A precedence), API contract tests, vitest store/page tests.

### U5 — Phase 5: Weighted score

**Goal:** Risk-reflective score with explicit unknown share.
**Requirements:** R5
**Dependencies:** U3 (ACTIVE filter), U4 (UNKNOWN)
**Files:** migration (additive columns), `internal/scoring/scoring.go` (+weights), `ingest.go:updateComplianceScores`, dashboard/overview consumers, docs (scoring model).

**Tasks:**
1. Weights constant: CRITICAL=10, HIGH=5, MEDIUM=2, LOW=1; document formula: `weighted_score = 100 × Σ(w_i·pass_i) / Σ(w_i·applicable_i)` where applicable excludes UNKNOWN and NOT_APPLICABLE; `unknown_share = unknown/(total)`.
2. Write both legacy `score` (unchanged formula) and new `weighted_score` + `severity_breakdown {critical:{passed,failed}, …}` + `unknown_count` during ingest score update.
3. Overview/dashboard prefer weighted when present; tooltip explains difference; after one release a cleanup task may retire legacy computation (tracked as follow-up, not in this plan's scope).
4. Tests: golden scoring fixtures (mixed severities incl. UNKNOWN-heavy set proving score honesty guardrail).

### U6 — Phase 3c: Incident state wiring (exceptions/remediation propagation)

**Goal:** Close the phantom-state gap inside compliance's own domain edges.
**Requirements:** R12
**Dependencies:** none
**Files:** `workers/remediation_scheduler.py` (or plan-transition service), `routers/compliance/exceptions.py` approve handler, `remediation_verification.py` rollback branch.

**Tasks:**
1. Plan EXECUTING → `drift_events.status='IN_REMEDIATION'` for referenced `drift_event_id`s (open ones); FAILED/ROLLED_BACK → revert to OPEN (`last_seen=now()`).
2. Exception APPROVED → covered open incidents (same rule domain + agent scope) → `EXCEPTION`, `suppressed_by=approver`; expiry (existing Expirer) does not reopen history — next failing snapshot creates a fresh incident (dedup semantics already correct).
3. Tests: integration transitions incl. rollback-revert; assert correlation dedup unaffected.

### U7 — Phase 8: Remediation modes (MONITOR / ASSISTED / AUTOMATIC)

**Goal:** Policy-level enforcement choice with safe defaults, reusing Autopilot design.
**Requirements:** R9
**Dependencies:** U3–U5 recommended but independent
**Files:** migration (policy_sets.remediation JSONB nullable), `policy_engine.py` settings surface, `RemediationSchedulerWorker` extension (per Autopilot A2 preconditions), frontend policy form section.

**Tasks:**
1. `policy_sets.remediation = {mode: MONITOR|ASSISTED|AUTOMATIC, allowed: [domains], forbidden: [domains]}` default NULL ⇒ ASSISTED (current behavior).
2. AUTOMATIC executes only when ALL hold: global kill-switch on (S2 setting), domain ∈ allowed ∧ ∉ forbidden, template active with non-empty rollback, active maintenance window covers agent, dry-run PASS, daily cap not exceeded — full precondition list per Autopilot A2.
3. MONITOR short-circuits remediation creation for that policy's findings (UI hides action buttons with explanation tooltip).
4. Audit every automatic transition with actor `system:autopilot`.
5. Tests: mode matrix unit tests + one end-to-end integration (finding→auto plan→dry-run→execute→verify→resolved) behind test settings.

### U8 — Phase 3d+9: Standards page, importer quarantine, reporting gate

**Goal:** Honest standards coverage; importer demoted to reference catalog; reporting complexity contained.
**Requirements:** R2, R10, KTD7
**Dependencies:** U3 (statuses)
**Files:** `routers/compliance/standards.py` (new aggregation endpoints), `pages/compliance/standards/index.vue` + `[key]/[version].vue` (new), `policy_engine.py` import endpoint labeling, `report_service.py` + settings flag, reports UI toggle.

**Tasks:**
1. `GET /compliance/standards` → frameworks×versions with `{rules_total, executable, reference_only, coverage_executable_pct}` (executable = mapped rules with status ACTIVE∧CEL); `GET /compliance/standards/{key}/{version}` → controls with mapped-rule drill-down.
2. Optional framework metadata columns (`publisher`, `description`, `status`) added nullable; UI displays when present.
3. Import endpoint: response + UI badge “Imported as Reference catalog (not executable)”; imported rows forced `status=REFERENCE_ONLY, is_enabled=false` regardless of payload.
4. Reporting: settings key `reports.xlsx_pdf_enabled` (default true today to avoid surprise; flip default documented as ops decision) gates XLSX/PDF serializers; JSON/CSV always available; 415/403-free degradation — format list endpoint reflects availability.
5. Tests: coverage math goldens (mixed statuses), import-forces-reference-only regression, report gating.

### U9 — Phase 6: Granular RBAC

**Goal:** Least-privilege enforcement without changing role semantics.
**Requirements:** R6
**Dependencies:** U4/U8 routes exist to protect
**Files:** `backend/lokilinux/auth/permissions.py` (new registry), `auth/dependencies.py` (`require_permission`), route-by-route adoption across `routers/compliance/**`, tests.

**Tasks:**
1. Registry `PERMISSIONS: dict[str, set[role]]` implementing §24 list; ADMIN superset; AUDITOR view/export-only; OPERATOR no approvals; MANAGER approvals+manage; VIEWER view-only.
2. `require_permission(p)` dependency resolves current user role → permissions (cached per-request); audit-denied attempts (403 + audit log entry).
3. Adopt incrementally: write-sensitive routes first (exceptions.approve, remediation.execute/approve, policies.manage, standards.manage), then reads (findings.view etc. defaulting any-authenticated until roles tightened — documented per-route in PR description).
4. Tests: parametrized RBAC matrix (role × permission × endpoint class) — every sensitive route covered.

### U10 — Phase 7: Enterprise Overview + wizard polish

**Goal:** The first screen answers “how compliant are we?” instantly.
**Requirements:** R7, R8
**Dependencies:** U4 (findings), U5 (weighted score), U8 (standards coverage)
**Files:** `routers/compliance/overview.py` (aggregate endpoint), Redis-cached service, `pages/compliance/index.vue` rebuild, `pages/compliance/policies/wizard.vue` (new stepper component).

**Tasks:**
1. `GET /compliance/overview` payload: overall weighted %, findings by severity (open), systems {compliant, at_risk, non_compliant, unknown} thresholds documented, top failed controls (7d), top affected servers, per-standard coverage, recent assessments (5). Cache TTL 60s + invalidation on score-update NATS hook point reserved (Autopilot N3).
2. Dashboard implements the §10 layout with progressive disclosure: technical detail (expressions, hashes) only inside Evidence drawer.
3. Wizard: 8 steps per spec over existing APIs (create policy_set → attach rules by standard filter → assignment scope builder reusing target-resolution → schedule via Autopilot A1 settings → remediation mode from U7 → review). Draft persists client-side (Pinia) until final create.
4. Tests: overview aggregate correctness vs seeded fixture DB; wizard happy-path E2E (vitest + manual smoke script).

## Testing strategy

- **Unit:** CEL verdict matrix incl. UNKNOWN/N_A precedence; weight math; backfill mapping; permission resolution; sugar-free compiler untouched.
- **Integration:** heartbeat snapshot → ingest → findings visible via API; exception approval → EXCEPTION state; auto-remediation E2E (gated); overview aggregates vs raw SQL truth.
- **RBAC:** parametrized role×permission×route matrix (U9).
- **Regression:** full `pytest backend/tests`, `go test ./...` (both modules), `npm test` green at every phase boundary; v1 API contracts snapshotted before Phase 1 and diffed after each phase.

## Observability

New Prometheus counters (Go service + API): `compliance_findings_total{severity}`, `compliance_unknown_total{domain}`, `compliance_remediation_total{mode,result}`, `compliance_assessment_duration_seconds` (histogram), `compliance_overview_cache_hit_total`. Labels limited to severity/domain/mode/result — no host cardinality.

## Compatibility & Rollout

- Every unit is independently deployable; phases land in order 1→10 but U3/U4 can proceed parallel to U2.
- No destructive migration: dropped drift columns are the only removals (proven unwritten/unread); all other changes additive.
- Legacy `score` column keeps populating through the entire plan; weighted becomes primary in UI immediately, retirement of legacy computation is an explicit follow-up decision.
- Rollback per unit = git revert + (for U1) restore-from-migration-downgrade; feature flags (reporting gate, remediation AUTOMATIC kill-switch) provide runtime off-switches.

## Success criteria (mapped)

An administrator can: open Compliance → see weighted risk instantly (U10) → browse Findings (U4) → open evidence with expected/observed/snapshot (U4) → understand UNKNOWN reasons (U4) → pick a Standard with honest coverage (U8) → build a policy via wizard (U10) → assign visually (existing targets + wizard) → assess on schedule (Autopilot A1) → remediate ASSISTED/AUTOMATIC safely (U7) → watch finding resolve on verification (existing worker + U6 states) → export JSON/CSV always, office formats when enabled (U8) — all under granular permissions (U9) with a complete audit trail, while CEL/NATS/JetStream/BLAKE3 stay invisible unless deliberately inspected.
