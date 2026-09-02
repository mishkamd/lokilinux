"""
LokiLinux — Platform settings schema (single source of truth).

All keys are stored as flat "{group}.{key}" rows in the `settings` table
(lokilinux.models.audit.Setting). Frontend groups in
frontend/pages/admin/settings.vue mirror SETTINGS_SCHEMA exactly.

ponytail: LDAP fields are storage-only — no bind logic is wired up (needs a
real directory server to test against). cve.* and repo.* / plugins.marketplace_url
are storage-only too — nothing consumes them yet (CVE sync is still a stub,
repositories table doesn't exist). retention.metrics_days is storage-only —
changing it does not touch the TimescaleDB compression policy, which would
require running ALTER on a continuous aggregate.
"""

from typing import Any

SETTINGS_SCHEMA: dict[str, dict[str, tuple[str, Any]]] = {
    "agent": {
        "platform_url": ("string", ""),
        "version": ("string", "0.41.0"),
        "download_base": ("string", ""),
    },
    "security": {
        "ldap_enabled": ("boolean", False),
        "ldap_host": ("string", ""),
        "ldap_port": ("integer", 389),
        "ldap_bind_dn": ("string", ""),
        "ldap_bind_password": ("string", ""),
        "ldap_search_base": ("string", ""),
        "ldap_use_ssl": ("boolean", False),
        "require_2fa": ("boolean", False),
        "session_expiry_days": ("integer", 7),
        "session_update_age_hours": ("integer", 24),
        "password_min_length": ("integer", 8),
        "rate_limit_enabled": ("boolean", True),
        "rate_limit_per_minute": ("integer", 120),
        "audit_log_retention_days": ("integer", 365),
    },
    "notifications": {
        "smtp_host": ("string", ""),
        "smtp_port": ("integer", 587),
        "smtp_user": ("string", ""),
        "smtp_password": ("string", ""),
        "smtp_from": ("string", ""),
        "slack_webhook_url": ("string", ""),
    },
    "fleet": {
        "heartbeat_timeout_minutes": ("integer", 5),
        "job_stale_timeout_minutes": ("integer", 60),
    },
    "observability": {
        # Kill switch for the events -> signals -> incidents pipeline (Task A5).
        # Workers re-check this every loop, so flipping it takes effect without
        # a redeploy — legacy alerting is unaffected either way.
        "event_pipeline_enabled": ("boolean", True),
        # Safe-by-default (Task E2): AUTO-mode runbooks stay no-ops until an
        # admin explicitly flips this on. MANUAL runbooks are unaffected —
        # they only ever run when someone clicks "Execute".
        "incident_autorun_runbooks": ("boolean", False),
    },
    "retention": {
        "metrics_days": ("integer", 365),
    },
    "compliance": {
        # Master kill-switch for AUTOMATIC-mode remediation (Enterprise
        # Compliance plan U7/KTD8, Autopilot A2) — off by default, same
        # safe-by-default precedent as observability.incident_autorun_runbooks.
        # A policy_set with remediation.mode=AUTOMATIC has zero effect while
        # this is false; ASSISTED/MONITOR are untouched either way.
        "auto_remediation_enabled": ("boolean", False),
        # Anti-storm cap shared across the whole fleet, not per policy —
        # counts AUTOMATIC-trigger_type plans created today.
        "auto_remediation_max_plans_per_day": ("integer", 10),
        # ponytail: Autopilot A1 (docs/modules/10-compliance-autopilot.md)
        # — the value this setting is meant to drive
        # (compliance_assessment_scheduler.py, a worker reading this key and
        # creating a GLOBAL assessment every N days) isn't built. This is
        # config-only today: the wizard's Schedule step (plan U10) reads and
        # writes it so an admin's choice survives the moment A1 ships,
        # rather than defining the key twice. 0 = off either way.
        "auto_assessment_days": ("integer", 0),
    },
    "cve": {
        "feed_source_url": ("string", ""),
        "sync_interval_hours": ("integer", 24),
        "nvd_api_key": ("string", ""),
    },
    "branding": {
        "company_name": ("string", "LokiLinux"),
        "logo_url": ("string", "/logo.svg"),
    },
    "plugins": {
        "marketplace_url": ("string", ""),
    },
    "repo": {
        "default_mirror_url": ("string", ""),
    },
    "reports": {
        # Enterprise Compliance plan R10/U8 Task 4 — office-format serializers
        # (openpyxl/reportlab) are heavier and less audited than the JSON/CSV
        # paths, which stay always-on regardless of this flag. Default True
        # to avoid surprising anyone relying on the existing behavior; an
        # operator flips it off as a deliberate ops decision (plan's own
        # wording), not something this change decides for them.
        "xlsx_pdf_enabled": ("boolean", True),
    },
}

# Keys never echoed back in plaintext once set.
SECRET_KEYS = {"security.ldap_bind_password", "notifications.smtp_password", "cve.nvd_api_key"}

# Subset safe to expose without auth (login page, layouts, pre-session checks).
PUBLIC_GROUPS = {"branding"}
PUBLIC_KEYS = {"security.require_2fa"}

MASK = "••••••••"


def flat_keys() -> list[str]:
    return [f"{group}.{key}" for group, keys in SETTINGS_SCHEMA.items() for key in keys]


def _cast(raw: str | None, value_type: str, default: Any) -> Any:
    if raw is None:
        return default
    if value_type == "boolean":
        return raw.lower() == "true"
    if value_type == "integer":
        try:
            return int(raw)
        except ValueError:
            return default
    return raw


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


async def get_all_settings(db: Any, *, groups: set[str] | None = None) -> dict[str, dict[str, Any]]:
    from sqlalchemy import select

    from lokilinux.models.audit import Setting

    wanted_groups = groups or set(SETTINGS_SCHEMA)
    keys = [f"{g}.{k}" for g in wanted_groups for k in SETTINGS_SCHEMA.get(g, {})]
    rows = (await db.execute(select(Setting).where(Setting.key.in_(keys)))).scalars().all()
    stored = {r.key: r.value for r in rows}

    result: dict[str, dict[str, Any]] = {}
    for group in wanted_groups:
        if group not in SETTINGS_SCHEMA:
            continue
        result[group] = {}
        for key, (vtype, default) in SETTINGS_SCHEMA[group].items():
            full_key = f"{group}.{key}"
            value = _cast(stored.get(full_key), vtype, default)
            if full_key in SECRET_KEYS and value:
                value = MASK
            result[group][key] = value
    return result


async def update_settings(db: Any, payload: dict[str, dict[str, Any]]) -> dict[str, str]:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from lokilinux.models.audit import Setting

    changes: dict[str, str] = {}
    for group, keys in payload.items():
        if group not in SETTINGS_SCHEMA or not isinstance(keys, dict):
            continue
        for key, value in keys.items():
            if key not in SETTINGS_SCHEMA[group]:
                continue
            full_key = f"{group}.{key}"
            if full_key in SECRET_KEYS and value == MASK:
                continue  # unchanged secret echoed back — don't clobber it
            vtype, _default = SETTINGS_SCHEMA[group][key]
            str_value = _stringify(value)
            stmt = (
                pg_insert(Setting)
                .values(key=full_key, value=str_value, value_type=vtype)
                .on_conflict_do_update(index_elements=["key"], set_={"value": str_value, "value_type": vtype})
            )
            await db.execute(stmt)
            changes[full_key] = "***" if full_key in SECRET_KEYS else str_value
    await db.commit()
    return changes


async def get_setting_value(db: Any, full_key: str) -> Any:
    """Fetch a single live setting value (used by workers/middleware), typed per schema."""
    from sqlalchemy import select

    from lokilinux.models.audit import Setting

    group, _, key = full_key.partition(".")
    if group not in SETTINGS_SCHEMA or key not in SETTINGS_SCHEMA[group]:
        return None
    vtype, default = SETTINGS_SCHEMA[group][key]
    row = (await db.execute(select(Setting).where(Setting.key == full_key))).scalar_one_or_none()
    return _cast(row.value if row else None, vtype, default)
