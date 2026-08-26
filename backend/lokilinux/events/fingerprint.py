"""
LokiLinux — deterministic event/signal fingerprinting.

Same (tenant, host, type, resource) always produces the same fingerprint —
this is what upsert_signal (Phase B) groups occurrences on, and what
correlation windows (Phase C) key by. Must never include timestamp or any
other non-deterministic field.
"""

import hashlib


def fingerprint(tenant_id: str, host_id: str | None, type_: str, resource: str | None = None) -> str:
    resource = resource or host_id or ""
    raw = "|".join(filter(None, [tenant_id, host_id, type_, resource]))
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
