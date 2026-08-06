<!-- generated-by: claude -->
# API Specification — `/api/v1/compliance/*`

All new endpoints live in `backend/lokilinux/api/v1/routers/compliance/` (a sub-package, since
this module has more surface area than any existing single-file router) and mount into
`backend/lokilinux/api/v1/__init__.py` the same way every other router does:

```python
# backend/lokilinux/api/v1/__init__.py — additions
from .routers.compliance import router as compliance_router
router.include_router(compliance_router, prefix="/compliance", tags=["compliance"])
```

Every endpoint follows the conventions already established by `routers/policies.py` and
`routers/cves.py`: `CursorPage[T]` responses for lists (`schemas/common.py:13-37` —
UUID-keyed resources use the `"{created_at.isoformat()}:{id}"` composite cursor), `Depends(get_db)`/
`Depends(get_cache)`/`Depends(get_nats)`, `Depends(get_current_user)` for reads, and
`Depends(require_role(...))` for mutations. `AUDITOR` gets read access everywhere in this
module (mirroring `admin.py:255`'s `require_role("ADMIN", "AUDITOR")` on audit-log reads) since
compliance state is exactly what an auditor role exists to see.

## 1. Baseline Manager

```yaml
openapi: 3.1.0
info: { title: LokiLinux Compliance API, version: "1.0.0" }
paths:
  /api/v1/compliance/baselines:
    get:
      summary: List baselines
      parameters:
        - { name: cursor, in: query, schema: { type: string } }
        - { name: limit, in: query, schema: { type: integer, default: 20, maximum: 100 } }
        - { name: scope_type, in: query, schema: { type: string, enum: [GLOBAL, OS, ROLE, ENVIRONMENT, DATACENTER, CLUSTER, APPLICATION] } }
      responses:
        "200":
          description: OK
          content:
            application/json:
              schema: { $ref: "#/components/schemas/CursorPageBaseline" }
    post:
      summary: Create baseline (DRAFT version 1)
      security: [{ bearerAuth: [ADMIN, OPERATOR] }]
      requestBody:
        content:
          application/json:
            schema: { $ref: "#/components/schemas/BaselineCreate" }
      responses:
        "201": { description: Created }
  /api/v1/compliance/baselines/{baseline_id}/versions:
    post:
      summary: Create a new DRAFT version from the current PUBLISHED one
      security: [{ bearerAuth: [ADMIN, OPERATOR] }]
      responses: { "201": { description: Created } }
  /api/v1/compliance/baselines/{baseline_id}/versions/{version_id}/submit:
    post:
      summary: DRAFT -> PENDING_APPROVAL
      security: [{ bearerAuth: [ADMIN, OPERATOR] }]
      responses: { "200": { description: OK } }
  /api/v1/compliance/baselines/{baseline_id}/versions/{version_id}/approve:
    post:
      summary: PENDING_APPROVAL -> APPROVED (records baseline_approvals row)
      security: [{ bearerAuth: [ADMIN] }]
      responses: { "200": { description: OK } }
  /api/v1/compliance/baselines/{baseline_id}/versions/{version_id}/publish:
    post:
      summary: APPROVED -> PUBLISHED (signs content_hash, publishes lokilinux.compliance.baseline.published)
      security: [{ bearerAuth: [ADMIN] }]
      responses: { "200": { description: OK } }
  /api/v1/compliance/baselines/{baseline_id}/versions/{version_id}/rollback:
    post:
      summary: Re-publish an older version as the new current PUBLISHED version (no history mutation)
      security: [{ bearerAuth: [ADMIN] }]
      responses: { "200": { description: OK } }
  /api/v1/compliance/agents/{agent_id}/effective-baseline:
    get:
      summary: Resolved baseline_effective for one agent, with the version chain used (for "explain")
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/EffectiveBaseline" }
```

## 2. Policy Engine

```yaml
  /api/v1/compliance/policy-sets:
    get: { summary: List policy sets (CIS/STIG/PCI/NIST/ISO27001/internal) }
    post:
      summary: Create custom policy set
      security: [{ bearerAuth: [ADMIN, OPERATOR] }]
  /api/v1/compliance/policy-sets/import:
    post:
      summary: Import a ComplianceAsCode profile (07-POLICY-ENGINE.md pipeline)
      security: [{ bearerAuth: [ADMIN] }]
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                source: { type: string, enum: [complianceascode] }
                profile_id: { type: string, example: "xccdf_org.ssgproject.content_profile_cis" }
                content_version: { type: string, example: "v0.1.75" }
  /api/v1/compliance/policy-sets/{id}/export:
    get: { summary: Export policy set as JSON/YAML for git-tracked change review }
  /api/v1/compliance/policy-assignments:
    get: { summary: List scope -> policy-set assignments }
    post:
      summary: Assign a policy set to a scope
      security: [{ bearerAuth: [ADMIN, OPERATOR] }]
  /api/v1/compliance/rules:
    get:
      summary: Search rules
      parameters:
        - { name: search, in: query, schema: { type: string } }
        - { name: severity, in: query, schema: { type: string } }
        - { name: domain, in: query, schema: { type: string } }
        - { name: framework, in: query, schema: { type: string }, description: filters via standard_refs JSONB containment }
  /api/v1/compliance/rules/{rule_id}/coverage:
    get: { summary: "check_source breakdown (CEL / OVAL_UNMAPPED / OSCAP_FALLBACK) for this rule across the fleet" }
```

## 3. Drift & Inventory

```yaml
  /api/v1/compliance/agents/{agent_id}/inventory/{domain}:
    get: { summary: Latest normalized facts document for one domain, plus content_hash and taken_at }
  /api/v1/compliance/agents/{agent_id}/inventory/{domain}/history:
    get: { summary: Cursor-paginated inventory_deltas for this agent/domain }
  /api/v1/compliance/drift-events:
    get:
      summary: List drift events, fleet-wide or filtered
      parameters:
        - { name: severity, in: query, schema: { type: string } }
        - { name: agent_id, in: query, schema: { type: string, format: uuid } }
        - { name: compared_against, in: query, schema: { type: string, enum: [BASELINE, PREVIOUS_SNAPSHOT, DESIRED_STATE] } }
        - { name: acknowledged, in: query, schema: { type: boolean } }
  /api/v1/compliance/drift-events/{id}/acknowledge:
    post:
      summary: Acknowledge a drift event (does not resolve it, just marks reviewed)
      security: [{ bearerAuth: [ADMIN, OPERATOR] }]
  /api/v1/compliance/drift-events/{id}/details:
    get: { summary: Field-level diffs (drift_details) for this event }
  /api/v1/compliance/file-integrity/{agent_id}:
    get: { summary: Current file_hashes for an agent, optionally filtered by path prefix }
  /api/v1/compliance/file-integrity/{agent_id}/changes:
    get: { summary: Cursor-paginated file_changes history }
```

## 4. Scoring & Dashboard

```yaml
  /api/v1/compliance/scores/fleet:
    get:
      summary: Fleet-wide current score by category, plus trend (from compliance_scores_daily)
      parameters:
        - { name: group_by, in: query, schema: { type: string, enum: [datacenter, cluster, environment, os, role] } }
  /api/v1/compliance/scores/agents/{agent_id}:
    get: { summary: Per-agent score history, all categories }
  /api/v1/compliance/dashboard/top-violations:
    get: { summary: Most-failed rules fleet-wide, for the "Top violations" widget }
  /api/v1/compliance/dashboard/top-changed-files:
    get: { summary: Highest file_changes frequency, fleet-wide }
```

## 5. Remediation Engine

```yaml
  /api/v1/compliance/remediation-plans:
    get: { summary: List plans }
    post:
      summary: Create a remediation plan from a set of drift_events or rule_evaluations
      security: [{ bearerAuth: [ADMIN, OPERATOR] }]
  /api/v1/compliance/remediation-plans/{id}/approve:
    post:
      summary: Approve plan — creates the underlying Job via JobService.create_job(job_type="COMPLIANCE_REMEDIATE", ...)
      security: [{ bearerAuth: [ADMIN, OPERATOR] }]
  /api/v1/compliance/remediation-plans/{id}/rollback:
    post:
      summary: Execute the rollback_body of each completed action as a new Job
      security: [{ bearerAuth: [ADMIN] }]
  /api/v1/compliance/maintenance-windows:
    get: { summary: List }
    post: { summary: Create, security: [{ bearerAuth: [ADMIN, OPERATOR] }] }
```

## 6. AI Compliance Assistant

```yaml
  /api/v1/compliance/ai/ask:
    post:
      summary: Freeform infrastructure question, RAG + planner, read-only tool access
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                question: { type: string }
                subject_type: { type: string, enum: [drift_event, rule_evaluation, agent, fleet] }
                subject_id: { type: string, format: uuid }
  /api/v1/compliance/ai/recommendations:
    get: { summary: List ai_recommendations, filterable by status/kind }
  /api/v1/compliance/ai/recommendations/{id}/approve:
    post:
      summary: Human approval — turns a REMEDIATION_PLAN-kind recommendation into a real remediation_plan + Job
      security: [{ bearerAuth: [ADMIN, OPERATOR] }]
```

## 7. Reporting Engine

```yaml
  /api/v1/compliance/reports:
    post:
      summary: Request a report (async — returns PENDING, poll or WebSocket for completion)
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                report_type: { type: string, enum: [FLEET_SUMMARY, POLICY_SET, DATACENTER, CUSTOM] }
                format: { type: string, enum: [PDF, CSV, XLSX, JSON] }
                params: { type: object }
    get: { summary: List reports, cursor-paginated }
  /api/v1/compliance/reports/{id}/download:
    get: { summary: Redirect to artifact_uri once status=COMPLETED }
```

## 8. Cursor pagination — matches existing convention exactly

```python
# routers/compliance/drift_events.py — same shape as routers/policies.py:28-46
@router.get("", response_model=CursorPage[DriftEventResponse])
async def list_drift_events(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    severity: str | None = Query(None),
    agent_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> CursorPage[DriftEventResponse]:
    q = select(DriftEvent).order_by(DriftEvent.time.desc())
    if severity:
        q = q.where(DriftEvent.severity == severity)
    if agent_id:
        q = q.where(DriftEvent.agent_id == agent_id)
    if cursor:
        ts_str, eid = decode_cursor(cursor).rsplit(":", 1)
        ts = datetime.fromisoformat(ts_str)
        q = q.where((DriftEvent.time < ts) | ((DriftEvent.time == ts) & (DriftEvent.id < UUID(eid))))
    q = q.limit(limit + 1)
    rows = (await db.execute(q)).scalars().all()
    # ... has_more / next_cursor exactly as policies.py:44-51
```

## 9. Internal gRPC — no new public surface

The Go service (`lokilinux-compliance`) has no gRPC/REST surface consumed by users or the
frontend — it only consumes NATS and writes Postgres (D1, [02-GO-SERVICE.md](02-GO-SERVICE.md)).
The only gRPC surface in this module is the existing agent↔`lokilinux-grpc` heartbeat stream,
extended per [04-PROTOCOL.md](04-PROTOCOL.md) — no new port, no new service definition.

## 10. WebSocket — real-time drift/score updates

Reuses the existing `utils/websocket.ts` event model on the frontend
(`job:log | agent:status | alert | metrics`) by adding two event types published by
`lokilinux-api`'s NATS workers subscribing to `COMPLIANCE_DRIFT_DETECTED`/`COMPLIANCE_SCORE_UPDATED`:

```ts
// frontend/utils/websocket.ts — new event union members
type ComplianceEvent =
  | { type: 'compliance:drift'; agent_id: string; severity: string; drift_event_id: string }
  | { type: 'compliance:score'; agent_id: string; category: string; score: number }
```

No new WebSocket endpoint — same connection, same auth, matches the existing pattern rather
than opening a parallel channel.
