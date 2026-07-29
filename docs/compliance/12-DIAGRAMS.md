<!-- generated-by: claude -->
# Workflow & Sequence Diagrams

All diagrams are Mermaid, rendered natively by GitHub and by Claude Artifacts — no external
image assets to keep in sync with the design.

## 1. End-to-end scan cycle (workflow)

```mermaid
flowchart TD
    A[Agent: heartbeat tick, every 60s] --> B{Domain hash changed<br/>since last beat?}
    B -->|no| C[Send hash only]
    B -->|yes| D[Send hash + queue full body for next beat]
    C --> E[lokilinux-grpc: passthrough]
    D --> E
    E --> F[NATS: lokilinux.compliance.hashes.reported]
    F --> G[lokilinux-compliance: diff against inventory_snapshots]
    G --> H{Domain flagged<br/>as stale/missing?}
    H -->|yes| I[Response: resync_domains includes this domain]
    I --> D
    H -->|no full body pending| J[No action this cycle]
    E --> K{Full body present<br/>in this request?}
    K -->|yes| L[NATS: lokilinux.compliance.snapshot.domain]
    L --> M[Ingest: canonicalize, BLAKE3, upsert inventory_blobs/snapshots]
    M --> N[Drift Detector: vs baseline, vs previous, vs desired]
    M --> O[Rule Engine: CEL evaluation against active policy_sets]
    N --> P{Diff found?}
    P -->|yes| Q[Insert drift_events + drift_details, classify severity, correlate root cause]
    Q --> R[Publish lokilinux.compliance.drift.detected]
    O --> S[Insert rule_evaluations]
    S --> T[Scorer: recompute compliance_scores for affected categories]
    T --> U[Publish lokilinux.compliance.score.updated]
    R --> V[lokilinux-api NATS worker: WebSocket push + optional alert_rules match]
    U --> V
```

## 2. Baseline approval workflow

```mermaid
sequenceDiagram
    actor Author as Operator (author)
    actor Approver as Admin (approver)
    participant API as lokilinux-api
    participant DB as PostgreSQL
    participant NATS

    Author->>API: POST /compliance/baselines/{id}/versions (edit expected_state)
    API->>DB: INSERT baseline_versions (status=DRAFT)
    Author->>API: POST .../submit
    API->>DB: UPDATE status=PENDING_APPROVAL
    API->>DB: AuditService.log(baseline.submitted)
    Approver->>API: POST .../approve
    API->>API: reject if approver.id == baseline_versions.created_by (no self-approval)
    API->>DB: INSERT baseline_approvals(decision=APPROVED)
    API->>DB: UPDATE baseline_versions status=APPROVED
    Approver->>API: POST .../publish
    API->>API: compute content_hash, Ed25519 sign
    API->>DB: UPDATE status=PUBLISHED, signature=..., published_at=now()
    API->>DB: UPDATE prior PUBLISHED version -> DEPRECATED
    API->>NATS: publish lokilinux.compliance.baseline.published
    NATS->>API: lokilinux-compliance recomputes baseline_effective fleet-wide (async)
```

## 3. Remediation approval + execution (sequence)

```mermaid
sequenceDiagram
    actor Operator
    participant API as lokilinux-api
    participant JobSvc as JobService (existing)
    participant NATS
    participant Agent as Go Agent
    participant DB as PostgreSQL

    Operator->>API: POST /compliance/remediation-plans (from selected drift_events)
    API->>DB: INSERT remediation_plans(status=DRAFT), remediation_actions
    Operator->>API: POST .../submit
    API->>DB: UPDATE status=PENDING_APPROVAL
    Operator->>API: POST .../approve (require_role ADMIN|OPERATOR)
    API->>JobSvc: create_job(job_type=COMPLIANCE_REMEDIATE, target_servers, requires_approval=false)
    JobSvc->>DB: dedup check, INSERT jobs, INSERT job_results (one per agent, status=PENDING)
    JobSvc->>NATS: publish lokilinux.job.created
    API->>DB: INSERT remediation_jobs(plan_id, job_id)
    API->>DB: AuditService.log(compliance.remediation_approved)
    Note over Agent: next heartbeat (<=60s later)
    Agent->>API: HeartbeatRequest
    API->>DB: get_pending_jobs(agent) -> this job's parameters
    API-->>Agent: HeartbeatResponse{pending_jobs: [...]}  (Phase-0-fixed wire, 04-PROTOCOL.md)
    Agent->>Agent: execute via provider (ansible/shell/python), pgid-kill on timeout
    Agent->>API: next HeartbeatRequest{job_results: [...]}
    API->>DB: recompute_job_status -> COMPLETED/FAILED
    API->>DB: UPDATE remediation_plans.status accordingly
```

## 4. AI recommendation → approved action (sequence)

```mermaid
sequenceDiagram
    actor User
    participant API as lokilinux-api
    participant Planner as CompliancePlanner
    participant RAG as pgvector retrieval
    participant LLM as LLMProvider
    participant DB as PostgreSQL

    User->>API: POST /compliance/ai/ask {question, subject_type, subject_id}
    API->>RAG: hybrid retrieve (pgvector + pg_trgm) top-K chunks
    API->>Planner: run(question, context)
    loop up to ai.max_planner_steps
        Planner->>LLM: complete(messages, tools=READ_TOOLS+PROPOSAL_TOOLS)
        LLM-->>Planner: tool call (read) or proposal
        Planner->>DB: execute read tool (read-only service call)
        DB-->>Planner: result
    end
    Planner->>DB: INSERT ai_recommendations(status=PROPOSED)  [only if a proposal tool was called]
    Planner-->>API: answer text + recommendation_id (if any)
    API-->>User: response
    opt User approves
        User->>API: POST /ai/recommendations/{id}/approve
        API->>DB: INSERT remediation_plans (from proposal.body)
        Note over API: continues as the standard remediation approval flow (diagram 3)
    end
```

## 5. Historical audit architecture

```mermaid
flowchart LR
    subgraph Mutations
        M1[Baseline publish/approve]
        M2[Policy set edit/import]
        M3[Remediation approve/rollback]
        M4[AI recommendation approve]
    end
    M1 --> AS[AuditService.log]
    M2 --> AS
    M3 --> AS
    M4 --> AS
    M2 --> PA[policy_audit — activated, was write-less since creation]
    AS --> AL[(audit_logs — existing table)]
    AL --> Dashboard["/admin/audit page (existing) +\ncompliance-scoped filter (new)"]
    AL --> Reports[Reporting Engine: audit section of FLEET_SUMMARY report]
```

No new audit storage — this module is additional *writers* into the existing `audit_logs`
table (today only `routers/admin.py` writes to it) and the existing-but-dormant `policy_audit`
table, not a parallel audit trail.
