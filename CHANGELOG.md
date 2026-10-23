## [Unreleased]

- fix(frontend): data tables collapse into labelled cards on mobile instead of scrolling sideways — a ten-column table was 1061px wide inside a 363px viewport; sorting survives as a strip of sort chips, and a column without a label no longer renders a 13px arrow button
- fix(frontend): interactive targets meet WCAG 2.2 (24×24) — table sort headers, checkboxes (32px hit area around a 16px box), range pills and "+ Save view"; chart axis labels use the muted-foreground token (4.47:1 → 7.86:1) and row checkboxes carry accessible names
- fix(frontend): the type scale is rem-only — `--text-label/field/micro` follow the 106% root (and the user's browser font size) instead of drifting 6% away from every other step; DESIGN.md now states the real spacing scale
- fix(frontend): one page title instead of two — six pages rendered the layout's H1 and a PageHeader H2 with the same words, and the header's icon buttons were 36px against the Button primitive's 32px `icon` variant

- feat(compliance): policy sets are editable — a rule can be removed from a draft (`DELETE /compliance/policy-sets/{id}/rules/{rule_id}`) and a set can be exported as a portable profile (`GET /compliance/policy-sets/{id}/export`, JSON/YAML, rule references by key) and re-imported (`POST /compliance/policy-sets/import-profile`); a published set stays immutable, editing it means a new version
- feat(compliance): the remediation content is finally visible — `remediation_templates` (script + rollback, 21 curated rules) is exposed on the rule detail and per policy set; the policy set's Remediation tab lists the exact commands that would run, so choosing AUTOMATIC is reviewable before anything is dispatched; the command body is only handed to roles that can act on a host
- feat(compliance): one canonical domain vocabulary (`GET /compliance/domains`, mirroring the agent's 24 collectors) replaces the free-text "Filter by domain" boxes on findings and drift — a wrong spelling used to match nothing, with no message
- fix(compliance): a domain with no report category used to land silently in "configuration"; the vocabulary now lives in one place and covers all 24 collector domains
- feat(compliance): policy templates — ready-made profiles selected from the rule catalog (CIS/NIST/STIG/PCI, severity bands, the curated set), created with their rules and scope in one transaction (`GET /compliance/policy-templates`, `POST /compliance/policy-sets/from-template`); the same "one rule body, many named profiles" model ComplianceAsCode, CIS and Tenable use
- feat(compliance): rule-catalog filters are now real selects fed by the catalog's own values (`GET /compliance/rules/facets`) instead of free-text inputs that silently matched nothing
- feat(compliance): policy sets can be edited in place — add rules from the catalog on a draft, and see/apply the fleet scopes a set covers
- fix(compliance): the policy-set list offered three creation paths, one of which opened the legacy Enforcement wizard and created the wrong entity; the "New policy set" dialog is now one flow (template or blank), and the dead 8-step `ComplianceWizard` is gone
- fix(compliance): the compliance overview showed two different compliance percentages (unweighted pass rate and weighted score) on one page, plus metric cards repeating the hero's findings and drift; the hero is now the single place that reports them
- fix(compliance): the Configuration pages (baselines, drift, file integrity) had no tab bar at all, so there was no way to reach their neighbours from inside the area
- fix(compliance): every compliance list fetched 20 rows while the tables page at 25, so the pager never appeared and "Load more" was the only way past the first screen
- chore(compliance): dropped `policies.parent_policy_id` — declared but never written or read by anything (migration 065)

- fix(observability): the events source filter never refetched and "Load more" replaced the list instead of appending; event timestamps were rendered as local time although ClickHouse stores them as naive UTC
- fix(observability): saving a correlation rule wiped its suppression windows (the PATCH wrote the schema defaults); the rule's windows now round-trip
- fix(ui): the DataTable header label was a bare text interpolation, so every table with an action column reported a hydration mismatch
- feat(observability): alerts/signals/incidents/events lists — URL filters, saved views, hostname instead of a raw agent UUID, server-side totals, and cursor pagination for alerts
- feat(security): security response headers (nosniff, X-Frame-Options DENY, Referrer-Policy, HSTS; CSP on API responses, not on /docs)
- feat(security): SSRF guard `utils/url_guard.py` on webhook workflow steps and compliance datastream import; plugin installs limited to the platform origin
- fix(security): `/ready` no longer returns driver error text in the response body
- feat(security): `TRUST_PROXY_COUNT` — X-Forwarded-For is honoured for rate limiting only when set (default 0)
- feat(agent): `max_parallel_jobs` (default 2) bounds concurrently executing jobs; excess jobs wait for a slot instead of running unbounded
- fix(security): session cache keyed by token digest; CSV exports neutralise spreadsheet formulas; admin password written to a 0600 file, not printed
- feat(security): Host header allowlist (`TRUSTED_HOSTS_MODE`: log by default, enforce after a live check); request body cap per path (10 MB default, 64 KB auth, storage limit for uploads)
- feat(streams): JetStream streams capped at 10 GB each; compliance ingest drops duplicate snapshots within 5 min
- feat(security): domain snapshots carry a per-agent HMAC, verified by the compliance service; `ENFORCE_SNAPSHOT_HMAC` (off) rejects unsigned ones (migration 053)
- feat(workflow): no-self-approval on publish; the publisher of a version cannot approve its runs (migration 049 index, 050 published_by)
- fix(incidents): at most one open incident per group, enforced by a partial unique index (migration 049); a lost race attaches to the winner
- feat(vulns): Debian and Ubuntu packages matched against OSV every 30 min (migration 051, `source_package`; agents report source names)
- feat(agents): heartbeat reports native job capabilities (migration 052); workflow dispatch does not use them yet
- feat(agent-install): enrollment token via `LOKILINUX_ENROLLMENT_TOKEN` or `--token-file`; `--token` warns
- ci(security): gitleaks, semgrep, pip-audit and npm audit gate the pipeline
- docs(security): AI boundary contract (AI_BOUNDARY.md); X-Request-ID values are validated
- chore(agent): removed the unwired typed heartbeat loop

## [0.5.0] - 2026-08-26

- feat(observability): harden event/signal/correlation pipeline and compliance ingest (ab8394b)
- feat(frontend): apply enterprise design-system consistency across all pages (76602b5)
- feat(agent): envelope debug detail on malformed rejection (audit aid) (6187a0a)
- fix(jobs): normalize target_servers dict/list shapes so PENDING JobResults are created (dispatch bug) (15d224b)
- fix(grpc): metrics server hook lost in parallel overwrite — reapply (d7247b7)
- fix(stack): grpc BETTER_AUTH env + metrics port 9091, target_servers shape normalization, signed-job counter (424816d)
- docs(env): document PUBLIC_URL (agent install command + CORS origin) (e6e46e8)
- fix(agent-install): enrollment install_command honors configured platform URL (c53ea6b)

## [0.4.0] - 2026-08-26

- Bump default agent version to 0.37.0 (6fd2fba)
- Bump default agent version to 0.36.0 (6eeb6ce)
- docs: align architecture and module docs with operations-platform positioning (812c750)
- feat(frontend): operations-platform branding on auth, metadata, nav labels; branded error page (31103a5)
- feat(otlp): OpenTelemetry OTLP/HTTP ingestion (Task G1) (e841956)
- chore(backend): update OpenAPI metadata to operations-platform positioning (fff8951)
- docs: update product positioning and design-system description (0d09f09)
- docs: reposition README as Enterprise Linux Operations Platform (54e0817)
- feat(ui): observability suite pages (signals/events/topology/correlation/runbooks) (b990b68)
- feat(ui): incidents list + detail with timeline, root cause, runbook panel (49cc614)
- docs: finalization plan status — complete, E2E 8/8 live (ffbf1b0)
- docs(security): DISTRO_RUNBOOK, rollout checklist, E2E script validated live (8/8) (bbd39f5)
- feat(api): incidents/signals/correlation/observability endpoints (0f576ed)
- fix(incidents): write ClickHouse incident_evidence rows on open (Task D2 gap) (31351e5)
- feat(runbooks): incident->workflow bridge with safe-by-default auto trigger (be058a5)
- fix: guard CA bundle block on fresh certs dir (22248fd)
- feat(topology): nodes/edges, recursive resolver, REST CRUD (4c01d35)
- feat(security): CRL check on re-enroll proof-of-possession (revoked cert cannot resurrect identity) (d7ca41a)
- feat(agent): remediation via broker-backed ActionRunners (dry-run stays local) (2669e50)
- feat(incidents): incident watcher/sweeper worker (4a2aaf3)
- feat(agent): broker telemetry routing (check_updates), remediation gap prep, non-root flip opt-in (06a3535)
- feat(incidents): lifecycle service with alert bridge, dedup, auto-resolve (4816c1b)
- Add finalization plan (broker telemetry, remediation routing, CRL register, validation) (1f5d562)
- feat(incidents): incident/relations/timeline tables + alerts.incident_id link (migration 032) (db526ff)
- feat(correlation): weighted window evaluator, redis state, suppression, worker (2da0aa0)
- feat(signals): detectors, dedup/upsert signal service, signal processor worker (2aed0a1)
- feat(signals): signals + correlation_rules tables (migration 031) (e671f48)
- docs(security): KMS documentation + plan implementation status (795df16)
- feat(security): production profile startup validation (fail-closed) (c950ca1)
- feat(agent): exec broker daemon (peercred socket, allowlisted ops), packaging + opt-in non-root flip (66b04f0)


