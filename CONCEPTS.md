# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## Vulnerability Management

### CVE
A tracked vulnerability record in the fleet-wide catalog — one entry per published CVE, independent of whether it currently affects any host. Its severity starts from whatever the first detecting scan reports and is later corrected to the authoritative value by NVD Enrichment.

### Finding
A specific CVE detected on a specific host and package. A Finding has its own resolution lifecycle distinct from the CVE it references; a single CVE can have many Findings across the fleet, each independently open or resolved.

Lifecycle: detected → optionally moved into active remediation → resolved, or explicitly accepted as a standing risk (a terminal decision, not a resolution). A Finding that gets re-detected after being resolved reopens fully, back to its initial detected state.

### Open Exposure
The current-state view of Findings still active on the fleet right now, as distinct from the CVE catalog's fleet-independent, all-time view. A CVE can exist in the catalog at a given severity while having zero Open Exposure, if every Finding that ever referenced it has since been resolved.

### NVD Enrichment
The background process that periodically corrects a CVE's severity and details from the National Vulnerability Database's authoritative data, run independently of any host's scan activity. Enrichment updates the CVE catalog only — it does not, by itself, update any Finding that already references that CVE.

## Relationships

A CVE owns the authoritative severity; a Finding references a CVE but does not own severity itself — reading a Finding's own copy of severity instead of its CVE's can show a stale value if the CVE's severity was corrected after the Finding was recorded. Open Exposure is computed from Findings, never from CVEs directly, since the catalog has no concept of "currently affects a host."
