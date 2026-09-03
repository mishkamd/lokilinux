"""
LokiLinux — Application Settings

Auth is delegated to Better Auth (Nuxt 4 server): Bearer tokens are opaque
session tokens validated via GET {better_auth_url}/api/auth/get-session.
No JWT_SECRET_KEY / JWT_ALGORITHM / bcrypt here.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────
    database_url: str  # e.g. postgresql+psycopg://user:pass@host:5432/lokilinux

    # ── Cache ─────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379"

    # ── Message bus ───────────────────────────────────────────
    nats_url: str = "nats://localhost:4222"

    # ── Event store (observability pipeline) ──────────────────
    clickhouse_url: str = "http://localhost:8123"
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_database: str = "lokilinux"
    event_retention_days: int = 30
    signal_occurrence_retention_days: int = 90
    incident_evidence_retention_days: int = 180
    # NOTE: the pipeline kill switch (event_pipeline_enabled) lives in
    # settings_schema.py's "observability" group, not here — it's a live,
    # DB-backed toggle workers re-check every loop, not a deploy-time value
    # (see the plan's Rollout & rollback section).
    event_max_payload_bytes: int = 65536
    event_rate_per_agent_per_min: int = 600
    event_max_clock_skew_sec: int = 300
    correlation_state_backend: str = "redis"

    # ── Better Auth (Nuxt 4 instance) ─────────────────────────
    # FastAPI validates opaque session tokens via
    # GET {better_auth_url}/api/auth/get-session — the Better Auth SECRET
    # lives only on the Nuxt side; the API never needed it (the required
    # field that used to sit here broke boot on any env without it).
    better_auth_url: str  # e.g. http://localhost:3000

    # ── Agent certificates ────────────────────────────────────
    agent_cert_dir: str = "/etc/lokilinux/certs"
    agent_cert_ttl_days: int = 30
    ca_signer_socket_path: str = "/run/lokilinux/ca-signer/sign.sock"

    # ── Observability ─────────────────────────────────────────
    # (grpc port comes from the GRPC_PORT env read in grpc_server.py;
    # backend log level from LOG_LEVEL env / structlog config — neither
    # belongs in Settings until something actually reads them.)
    environment: str = "development"

    # ── Frontend (CORS origin) ────────────────────────────────
    frontend_url: str = "http://localhost:3000"

    # ── Agent distribution ────────────────────────────────────
    platform_url: str = "http://localhost:8000"
    agent_download_base: str = ""
    agent_version: str = "0.1.0"
    agent_package_dir: str = "/opt/lokilinux/packages"

    # ── Certificate revocation (P11) ──────────────────────────
    # enabled=False = compatibility mode (no lookups, no Redis dependency).
    # fail_closed=True: Redis unreachable at auth time REJECTS the connection
    # instead of admitting an un-checkable certificate.
    certificate_revocation_enabled: bool = True
    certificate_revocation_fail_closed: bool = True

    # ── Metrics / KMS (plan 2026-08-25) ───────────────────────
    metrics_enabled: bool = True
    metrics_port: int = 9090
    job_signing_required: bool = False   # fail-closed dispatch when True
    security_profile: str = "development"  # production adds startup validations

    # ── Object storage (RustFS / S3-compatible) ───────────────
    s3_enabled: bool = True
    s3_endpoint_url: str = "http://rustfs:9000"
    # Set only when the bucket is reachable from a browser (AWS S3, R2,
    # Wasabi, or RustFS behind a reverse proxy) — presigned URLs are signed
    # against this instead of s3_endpoint_url. Left empty, presign requests
    # are refused (409) and downloads go through the API proxy instead,
    # since s3_endpoint_url normally points at an app-net-internal hostname
    # no browser can resolve.
    s3_public_endpoint_url: str = ""
    s3_region: str = "us-east-1"
    s3_bucket: str = "lokilinux"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_addressing_style: str = "path"
    s3_presigned_url_expiration: int = 3600
    s3_max_upload_bytes: int = 500 * 1024 * 1024
    s3_multipart_threshold_bytes: int = 8 * 1024 * 1024

    @property
    def debug(self) -> bool:
        return self.environment == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
