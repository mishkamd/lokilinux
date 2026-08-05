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
        "version": ("string", "0.9.0"),
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
    "retention": {
        "metrics_days": ("integer", 365),
    },
    "cve": {
        "feed_source_url": ("string", ""),
        "sync_interval_hours": ("integer", 24),
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
}

# Keys never echoed back in plaintext once set.
SECRET_KEYS = {"security.ldap_bind_password", "notifications.smtp_password"}

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
