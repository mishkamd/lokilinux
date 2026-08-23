---
title: "Workflow YAML v2 + unified canvas↔YAML source module"
date: 2026-08-23
type: feature
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
product_contract_source: ce-plan-bootstrap
---

# Workflow YAML v2 + unified canvas↔YAML source module

## Summary

The workflow authoring surface has two halves that must stay in lockstep: the YAML text editor and the visual canvas. Today both work, but only in `lokilinux/v1` shape — and v1 is verbose (explicit `edges:` for every link, double dispatch via `type:` + `config.action:`, deep `metadata`/`spec` nesting). This plan ships two things as one coherent change:

1. **`lokilinux/v2`** — a drastically simplified YAML dialect (GitHub Actions / Ansible inspired): one sugar key per step decides its type (`install: [nginx]`, `service: nginx`, `check: <cmd>`), steps chain implicitly top-to-bottom, conditions are inline (`when:`), metadata is flattened. Implemented purely as a **desugarer in the backend compiler**: v2 expands to exactly the same internal `WorkflowDocument`/`CompiledGraph` the engine already runs — zero engine, DB, or API-contract changes.
2. **A version-aware canvas↔YAML sync layer** — the existing surgical `apply*` functions (`frontend/utils/workflow/yaml.ts`) keep working for v1 documents unchanged, and learn to read *and write* v2 sugar so that adding a block on the canvas appends a matching line to the YAML and vice versa, regardless of document version. All ops are exposed through a single facade module (`utils/workflow/source.ts`) instead of 15 scattered functions.

## Problem Frame

- **In scope:**
  - Backend: v2 detection + desugaring in `workflow_compiler.py`; schema export of the sugar table; golden tests proving v2 ≡ hand-written v1.
  - Frontend: v2-aware parsing (sugar → logical nodes) and writing (canvas ops emit sugar when possible) in `utils/workflow/yaml.ts`; new facade `utils/workflow/source.ts`; store/component refactor onto the facade; registry defaults shared by palette and writers; vitest goldens.
  - Docs: `docs/modules/05-workflow-engine.md` gains a YAML dialect section.
- **Out of scope:**
  - Engine semantics (`workflow_engine.py`) — untouched; it only ever sees compiled graphs.
  - Any v1 behavior change — v1 documents parse, validate, edit, and run byte-for-byte as today. Published `yaml_source` is immutable anyway (`models/workflow.py` docstring).
  - Rolling/canary strategy modes, wait mode `condition` — still unsupported, rejected identically in both dialects.
  - Variable interpolation into step params (`{{ }}`) — deliberately still absent; `vars` remain readable from condition expressions only.

## Requirements

- R1: A workflow written in v2 sugar compiles to a `CompiledGraph` identical (modulo auto-generated step ids) to the equivalent hand-written v1 document.
- R2: v1 documents continue to compile/validate/run with zero behavioral or textual change.
- R3: Adding a node on the canvas to a v2 document appends the corresponding sugar line/block to the YAML text; removing/connecting/moving/config-editing behave symmetrically.
- R4: Editing a v2 document's YAML text updates the canvas with inferred node types and configs (mirror of the backend desugar rules).
- R5: Canvas edits never rewrite untouched parts of the document: comments outside the edited step survive; layout/view sections are preserved; edits are idempotent (`parse(apply(apply(x))) == parse(apply(x))`).
- R6: Every palette drag produces valid YAML immediately (validatable server-side without further edits).
- R7: `GET /workflows/schema` exposes enough information (sugar table + per-type defaults) for frontend autocomplete of both dialects.
- R8: Both directions are covered by golden round-trip tests on representative v1 and v2 documents.

## Key Technical Decisions

- KTD1: **Desugar, don't fork.** v2 is expanded to the existing v1-shaped `WorkflowDocument` before Pydantic validation. The engine, dry-run, graph JSONB, canvas reads (`WorkflowVersionResponse.graph`) all stay untouched. No migration.
- KTD2: **Version is opt-in per document** via `apiVersion`. Absent/`lokilinux/v1` → legacy path, byte-identical. Only literal `lokilinux/v2` takes the desugar path. No silent upgrades.
- KTD3: **Sugar keys are the type discriminator.** Each v2 step has exactly one primary key drawn from a fixed table (see U1). This replaces `type:`+`config.action` double dispatch and gives the canvas writer a single decision point ("does this edit fit the sugar form?").
- KTD4: **Implicit chaining with explicit override.** By default step *i* gets an implicit success-edge from step *i-1*. A step declaring `needs:` receives exactly those edges instead of the implicit one (GitHub Actions `needs:` semantics, flattened to linear lists).
- KTD5: **`when:` desugars to a CONDITION node**, preserving engine semantics: `<step_id>-when` CONDITION inserted before the step; incoming edges retarget to it; its `success` edge goes to the step, its `failure` edge goes to END (v2.0 limitation — skip-to-next-step refinement deferred; documented in schema help text).
- KTD6: **Auto-generated ids** follow `slug(primary-key-value-or-key)[-<ordinal>]` clamped to `^[a-z0-9_-]{1,64}$`, uniquified by ordinal suffix. Deterministic on both sides (backend compiler, frontend parser) so goldens can compare graphs modulo a documented id-normalization.
- KTD7: **Frontend mirrors the inference table locally** (`utils/workflow/registry.ts`), not via an API fetch at parse time — parsing must stay synchronous and offline-capable. Drift between the two tables is caught by shared golden fixtures (same YAML files asserted against backend output and frontend output).
- KTD8: **yamlSource stays the single source of truth** in the frontend store (proven architecture: free undo/redo via `useManualRefHistory`, comment-preserving CST edits). No model-based regeneration layer.
- KTD9: **Mixed granularity inside a v2 document is legal.** A step may be sugar (`install: [nginx]`) while its sibling is full-form (`{id, type, name, config}`) — the desugarer handles both shapes per-item. This lets canvas writers fall back to full form whenever an edit doesn't fit a sugar template without rewriting the whole file.
- KTD10: **One facade.** Components stop importing `apply*` directly; `utils/workflow/source.ts` exposes typed operations (`addNode/removeNode/connect/disconnect/moveNode/renameNode/duplicateNode/setStepConfig/setStepField/changeStepType/setEdge`). The store shrinks to state + history + API calls.

## Current State Reference (verified)

| Fact | Location |
|---|---|
| Compiler pipeline: parse → validate → build_graph | `backend/lokilinux/services/workflow_compiler.py:78-107,336` |
| Action constant sets | `workflow_compiler.py:245-250` |
| Per-type config validation (publish-time) | `workflow_compiler.py:262-336` |
| Condition context language: `steps.<id>.{status,exit_code,duration_seconds}`, `vars.<name>`, `targets.count` | `backend/lokilinux/services/workflow_engine.py:519-541`, `backend/lokilinux/utils/expr.py` |
| Node types enum incl. permanent legacy aliases | `backend/lokilinux/schemas/workflow.py:28-68` |
| Schema endpoint exports Pydantic schema verbatim | `schemas/workflow.py:2-8`, `routers/workflows.py:42` |
| Frontend loose parser (CST, comment-preserving) | `frontend/utils/workflow/yaml.ts:21-94` |
| Surgical apply* family (add/remove/rename/duplicate/connect/layout/config) | `yaml.ts:96-394` |
| Store: yamlSource single-truth + undo/redo capacity 50 | `frontend/stores/workflow.ts:66-74,164,211,218,318` |
| Palette/node definitions + defaults | `frontend/utils/workflow/registry.ts`, `components/workflow/WorkflowPalette.vue` |
| Starter YAML template (v1) | `frontend/pages/workflows/index.vue:31-40` |

## Implementation Units

### U1. Backend desugarer `_desugar_v2`

**Goal:** `compile_workflow(yaml)` accepts `apiVersion: lokilinux/v2` and returns the same `(WorkflowDocument, CompiledGraph, ValidationResult)` triple the v1 path produces for the equivalent document.
**Requirements:** R1, R2
**Dependencies:** none
**Files:**
- `backend/lokilinux/services/workflow_compiler.py`
- `backend/tests/unit/services/test_workflow_compiler_v2.py` (new)

**Tasks:**
1. Add `SUGAR_TABLE` — the authoritative mapping (also exported by U2):

   | Primary key | Node type | Config mapping |
   |---|---|---|
   | `run: <cmd>` | command | `{command}` |
   | `install: [pkgs]` | package | `{action: install, packages}` |
   | `update: [pkgs]` | package | `{action: update, packages}` |
   | `remove: [pkgs]` | package | `{action: remove, packages}` |
   | `service: <name>` (+ `state:` ∈ start/stop/restart/reload/enable/disable) | service | `{action: state, name}` |
   | `copy: {src→source, dest→path}` | file | `{action: copy, source, path}` |
   | `create: {path, content}` / `delete: <path>` / `chmod: {path, mode}` / `chown: {path, user}` | file | respective `{action, ...}` |
   | `sysctl: {key, value}` / `hostname: <v>` / `timezone: <v>` | system | `{action, ...}` |
   | `check: <cmd>` (+ `expect_exit:`) | check | `{type: command, command, expect_exit_code}` |
   | `check_service:` / `check_port:` / `check_package:` / `check_file:` / `check_disk_gb:` / `check_process:` | check | respective `{type, ...}` |
   | `approval: <label?>` | approval | `{}` (label → step name) |
   | `notify: <channel>` (+ `message:`) | notification | `{channel, message}` |
   | `webhook: <url>` | webhook | `{url}` |
   | `wait_seconds: <n>` / `wait_agents: {}` | wait | `{mode: duration, seconds}` / `{mode: agent}` |

   Step-level passthrough keys (any dialect): `id?`, `name?`, `disabled?`, `timeout?`, `retry: {attempts, delay}`, `on_failure:`, plus v2-only `needs?: [ids]`, `when?: <expr>`.
2. Detection: load YAML once (`parse_yaml_text`); if top-level `apiVersion == "lokilinux/v2"` → run desugar; else current path untouched (KTD2).
3. Desugar steps: resolve primary key (exactly one required — otherwise `ValidationIssue` `AMBIGUOUS_SUGAR`); build `{id?, type, name?, config}` items; auto-id per KTD6 when absent.
4. Desugar chaining: build the edge list per KTD4/KTD5; explicit `spec.edges` is **not part of v2** — its presence raises `EDGE_IN_V2`.
5. Flatten header: top-level `name/description/severity/tags` → `metadata.*`; scalar/map `targets` → canonical `WorkflowTargets` (`all` / `[uuid…]` → `agent_ids` / map → `filters`); `defaults` passthrough; `layout`/`view` passthrough untouched.
6. Feed result through the existing Pydantic models + `validate_graph` + `build_graph` — zero new validation logic beyond sugar-shape errors.
7. Tests (goldens under `tests/unit/services/fixtures/workflow_v2/`):
   - `linear.yaml` (the README-style patch example) vs hand-written v1 twin → equal `CompiledGraph` after id normalization.
   - branching with `needs:` + two `when:` steps → expected CONDITION nodes and failure-to-END edges.
   - every sugar key ≥1 positive case; each malformed case (two primaries, unknown key, `edges:` present, bad `state`) → exact issue code.
   - v1 regression: existing compiler test suite passes unmodified.

### U2. Schema export of the sugar table

**Goal:** Autocomplete/help for both dialects from one endpoint.
**Requirements:** R7
**Dependencies:** U1
**Files:** `backend/lokilinux/api/v1/routers/workflows.py` (`GET /schema`)

**Tasks:**
1. Extend response: `{"pydantic_schema": …(existing)…, "dialects": {"v1": {"steps": …}, "v2": {"sugar": SUGAR_TABLE, "passthrough_keys": […], "notes": {"when": "failure edge goes to END"}}}}`.
2. Test: endpoint 200, contains all SUGAR_TABLE keys.

### U3. Frontend reader — parse v2 into canvas nodes

**Goal:** `parseWorkflowYaml` renders v2 documents on the canvas.
**Requirements:** R4
**Dependencies:** U1 (table parity)
**Files:** `frontend/utils/workflow/yaml.ts`, `frontend/utils/workflow/registry.ts`

**Tasks:**
1. Port `SUGAR_TABLE` + auto-id algorithm into `registry.ts` (KTD7) as `V2_SUGAR` with types.
2. In `parseWorkflowYaml`: branch on `data.apiVersion`; for v2 walk `steps[]`, detect primary key, infer `{id, type, name, config}` identically to backend; edges come from `needs:`/implicit chaining (pure function `inferEdges(steps)` shared by reader and writer).
3. Unknown primary key → canvas shows a generic error node + ValidationIssue (never freeze — freeze rule applies to YAML *syntax* errors only).
4. Tests in `yaml.test.ts`: same golden fixtures as U1 (copied), assert identical node/edge sets (mod id normalization).

### U4. Frontend writers — version-aware apply\*

**Goal:** Canvas ops on v2 documents produce minimal, valid, idiomatic v2 text.
**Requirements:** R3, R5, R6
**Dependencies:** U3
**Files:** `frontend/utils/workflow/yaml.ts`

**Tasks:**
1. Version detection helper `docDialect(doc): 'v1' | 'v2'` used by every apply function.
2. v1 path: return existing implementations untouched (R2).
3. v2 path:
   - `applyAddStep` → append minimal sugar block from registry default for the type (e.g. palette "Package install" → `- install: [pkg]`); honor drop position only via `layout` (unchanged rule: positions live in `layout.<id>`, `yaml.ts:182`).
   - `applyStepConfigPatch` → if the (step, key, value) fits the sugar template for its primary key, mutate the sugar fields in place; else expand **that item only** to full-form `{id, type, name, config}` mapping and patch there (KTD9).
   - `applyAddEdge`/`applyRemoveEdge`/`applyUpdateEdge` → translate to `needs:` list surgery on the target step (implicit chain = absence of `needs:`); removing the implicit edge means materializing `needs:` for the affected suffix… **simplification:** any explicit edge op first materializes `needs:` on all steps of the affected component (idempotent, local diff).
   - `changeStepType(stepId, newType)` (new op): swap primary key + reset config to registry defaults, preserve `id/name/timeout/retry/when/needs`.
4. Idempotency guard: every writer re-parses its own output in tests; second identical apply must be a no-op diff (R5).
5. Tests: per-op goldens on `linear.yaml` v2 (add/remove/connect/move/config-patch/type-change), asserting exact resulting text snippets + comment survival on untouched neighbors.

### U5. Facade `utils/workflow/source.ts` + call-site refactor

**Goal:** One typed entry point; store and components decoupled from raw yaml utilities.
**Requirements:** R3, R6
**Dependencies:** U4
**Files:** `frontend/utils/workflow/source.ts` (new), `frontend/stores/workflow.ts`, `frontend/components/workflow/*.vue`, `frontend/pages/workflows/[id].vue`, `index.vue`

**Tasks:**
1. Export `WorkflowSourceOps` interface: `addNode(def, position?)`, `removeNode(id)`, `connect(from, to, on?)`, `disconnect(id)`, `moveNode(id, x, y)`, `renameNode(oldId, newId)`, `duplicateNode(id)`, `setStepConfig(id, key, value)`, `setStepField(id, field, value)`, `changeStepType(id, type)`, `setEdge(from, to, patch)`.
2. Implement as thin wrappers choosing the right apply* per dialect; all commit through the store's existing history mechanism (no new snapshot machinery — KTD8).
3. Refactor `stores/workflow.ts` action bodies to call the facade (store keeps state/history/API only); update component imports (palette, canvas, properties, edge properties, node config form, run panel, pages).
4. `STARTER_YAML` in `pages/workflows/index.vue` switches to the v2 patching example (~12 lines).

### U6. Registry defaults & palette wiring

**Goal:** Every palette item carries the data needed to emit valid v2 instantly.
**Requirements:** R6
**Dependencies:** U3
**Files:** `frontend/utils/workflow/registry.ts`, `frontend/components/workflow/WorkflowPalette.vue`

**Tasks:**
1. Per-type `defaultConfig` + `sugarKey` fields on `NodeDefinition`; palette groups unchanged (legacy aliases stay hidden, `registry.ts:256`).
2. Drag payload carries `{sugarKey, defaultConfig}`; facade consumes it — no stringly-typed switch in components.

### U7. Golden round-trip suite (frontend)

**Goal:** Machine-checked guarantee that both directions never diverge.
**Requirements:** R5, R8
**Dependencies:** U3–U6
**Files:** `frontend/utils/workflow/goldens/` (fixtures), `frontend/utils/workflow/source.test.ts` (new)

**Tasks:**
1. Fixtures: `patch-nginx.v2.yaml`, `branching-needs-when.v2.yaml`, `mixed-granularity.v2.yaml`, plus their v1 twins; copied into backend fixture dir (single source in repo, referenced by both suites).
2. Property tests: for each op × fixture → `parse(result)` succeeds; applying twice changes nothing; undo (restore prior text) restores identical parse tree.
3. CI command documented in Verification below.

### U8. Documentation

**Goal:** The dialect and the sync contract are discoverable.
**Requirements:** none (docs)
**Dependencies:** U1, U4
**Files:** `docs/modules/05-workflow-engine.md`, `README.md` (one-line mention)

**Tasks:**
1. New section „Dialecte YAML (v1/v2)" in `05-workflow-engine.md`: before/after example, sugar table, `when:/needs:` semantics, mixed-granularity rule, compatibility statement (v1 frozen forever).
2. Section „Editor & sincronizare canvas↔YAML": the yamlSource-as-truth diagram, facade op list, idempotency/comment guarantees.
3. README workflows paragraph links to both.

## Verification

```bash
# Backend (desugarer + schema)
cd backend && pytest tests/unit/services/test_workflow_compiler.py tests/unit/services/test_workflow_compiler_v2.py -q

# Frontend (reader/writer/facade/goldens)
cd frontend && npx vitest run utils/workflow

# Full safety net
cd backend && pytest tests/unit -q
cd frontend && npm test
```

Manual smoke: create workflow from new starter → drag palette blocks → observe YAML lines appear; paste v2 example from docs → canvas renders; publish → dry-run → run against a test agent.

## Compatibility & Rollout

- No migration; no API breaking change (`/workflows/schema` response grows additively).
- Existing published workflows remain v1 forever (immutable sources) and keep rendering/editing exactly as today.
- New documents created from the UI default to v2; users can still paste v1 freely — the editor detects dialect per document.
- Rollback = revert frontend starter/facade commits independently of backend desugarer (v2 documents already saved would need apiVersion flipped back to v1-expanded form; acceptable, documented in U8).
