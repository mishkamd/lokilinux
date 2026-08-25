"""
LokiLinux — Application Settings

Auth is delegated to Better Auth (Nuxt 4 server).
FastAPI validates Bearer JWTs via JWKS at {BETTER_AUTH_URL}/api/auth/jwks.
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
    event_pipeline_enabled: bool = True

    # ── gRPC (agent communication) ────────────────────────────
    grpc_port: int = 50051

    # ── Better Auth (Nuxt 4 instance) ─────────────────────────
    # FastAPI fetches JWKS from {better_auth_url}/api/auth/jwks
    better_auth_url: str  # e.g. http://localhost:3000
    better_auth_secret: str  # shared secret for JWKS validation

    # ── Agent certificates ────────────────────────────────────
    agent_cert_dir: str = "/etc/lokilinux/certs"

    # ── Observability ─────────────────────────────────────────
    log_level: str = "INFO"
    environment: str = "development"

    # ── Frontend (CORS origin) ────────────────────────────────
    frontend_url: str = "http://localhost:3000"

    # ── Agent distribution ────────────────────────────────────
    platform_url: str = "http://localhost:8000"
    agent_download_base: str = ""
    agent_version: str = "0.1.0"
    agent_package_dir: str = "/opt/lokilinux/packages"
    better_auth_admin_token: str = ""

    # ── Certificate revocation (P11) ──────────────────────────
    # enabled=False = compatibility mode (no lookups, no Redis dependency).
    # fail_closed=True: Redis unreachable at auth time REJECTS the connection
    # instead of admitting an un-checkable certificate.
    certificate_revocation_enabled: bool = True
    certificate_revocation_fail_closed: bool = True

    @property
    def debug(self) -> bool:
        return self.environment == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
