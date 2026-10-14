## [Unreleased]

- feat(security): security response headers (nosniff, X-Frame-Options DENY, Referrer-Policy, HSTS; CSP on API responses, not on /docs)
- feat(security): SSRF guard `utils/url_guard.py` on webhook workflow steps and compliance datastream import; plugin installs limited to the platform origin
- fix(security): `/ready` no longer returns driver error text in the response body
- feat(security): `TRUST_PROXY_COUNT` — X-Forwarded-For is honoured for rate limiting only when set (default 0)
- feat(agent): `max_parallel_jobs` (default 2) bounds concurrently executing jobs; excess jobs wait for a slot instead of running unbounded
- fix(security): session cache keyed by token digest; CSV exports neutralise spreadsheet formulas; admin password written to a 0600 file, not printed
- feat(security): Host header allowlist (`TRUSTED_HOSTS_MODE`: log by default, enforce after a live check); request body cap per path (10 MB default, 64 KB auth, storage limit for uploads)
- feat(streams): JetStream streams capped at 10 GB each; compliance ingest drops duplicate snapshots within 5 min
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


