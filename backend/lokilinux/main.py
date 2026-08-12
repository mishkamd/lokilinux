"""
LokiLinux FastAPI Application

Auth: delegated to Better Auth (Nuxt 4).
      FastAPI validates Bearer JWTs via JWKS at {BETTER_AUTH_URL}/api/auth/jwks.
      No JWT generation, no bcrypt, no passlib here.

NATS topics use prefix  lokilinux.  (O1).
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import nats
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import JSONResponse

from lokilinux.api.v1 import router as api_v1_router
from lokilinux.cache import RedisCache
from lokilinux.config import Settings
from lokilinux.db import build_engine, build_session_factory
from lokilinux.middleware.rate_limit import RateLimitMiddleware

# ── Logging ───────────────────────────────────────────────────────────────────

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()
settings = Settings()

# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("lokilinux.startup", version="0.1.0", environment=settings.environment)

    # Database
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    app.state.db_engine = engine
    app.state.session_factory = session_factory
    logger.info("db.ready")

    # Redis
    cache = RedisCache(url=settings.redis_url)
    await cache.connect()
    app.state.cache = cache
    logger.info("cache.ready")

    # NATS — all topics prefixed lokilinux. (O1)
    nc = await nats.connect(settings.nats_url)
    app.state.nats = nc
    logger.info("nats.ready", url=settings.nats_url)

    # Workers — subscribe after NATS is up
    from lokilinux.workers.alert_processor import AlertProcessorWorker
    from lokilinux.workers.cve_processor import CVEProcessorWorker
    from lokilinux.workers.heartbeat_monitor import HeartbeatMonitorWorker
    from lokilinux.workers.job_executor import JobExecutorWorker
    from lokilinux.workers.job_timeout import JobTimeoutWorker
    from lokilinux.workers.notification_worker import NotificationWorker
    from lokilinux.workers.plugin_worker import PluginWorker
    from lokilinux.workers.policy_scheduler import PolicySchedulerWorker
    from lokilinux.workers.policy_worker import PolicyWorker
    from lokilinux.workers.retention_cleanup import RetentionCleanupWorker

    job_worker = JobExecutorWorker(nc, session_factory, cache)
    await job_worker.start()
    cve_worker = CVEProcessorWorker(nc, session_factory, cache)
    await cve_worker.start()
    alert_worker = AlertProcessorWorker(nc, session_factory)
    await alert_worker.start()
    policy_worker = PolicyWorker(nc, session_factory, cache)
    await policy_worker.start()
    policy_scheduler_worker = PolicySchedulerWorker(session_factory, cache)
    await policy_scheduler_worker.start()
    plugin_worker = PluginWorker(nc, session_factory, cache)
    await plugin_worker.start()
    heartbeat_worker = HeartbeatMonitorWorker(nc, session_factory, cache)
    await heartbeat_worker.start()
    job_timeout_worker = JobTimeoutWorker(session_factory, cache)
    await job_timeout_worker.start()
    retention_worker = RetentionCleanupWorker(session_factory)
    await retention_worker.start()
    from lokilinux.workers.remediation_scheduler import RemediationSchedulerWorker
    remediation_scheduler_worker = RemediationSchedulerWorker(session_factory, cache, nc)
    await remediation_scheduler_worker.start()
    notification_worker = NotificationWorker(nc, session_factory)
    await notification_worker.start()
    app.state.workers = [
        job_worker, cve_worker, alert_worker, policy_worker, policy_scheduler_worker, plugin_worker,
        heartbeat_worker, job_timeout_worker, remediation_scheduler_worker, retention_worker, notification_worker,
    ]
    logger.info("workers.ready")

    yield

    # Shutdown — reverse order
    logger.info("lokilinux.shutdown")
    await heartbeat_worker.stop()
    await remediation_scheduler_worker.stop()
    await job_timeout_worker.stop()
    await policy_scheduler_worker.stop()
    await retention_worker.stop()
    await nc.drain()
    await cache.disconnect()
    await engine.dispose()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="LokiLinux API",
    version="0.1.0",
    description="Enterprise Linux fleet management — backend API",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.debug else None,
)

# ── Middleware (order: outermost first) ───────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=3600,
)

app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)
app.add_middleware(RateLimitMiddleware)

# ── Request tracing middleware ────────────────────────────────────────────────


@app.middleware("http")
async def trace_requests(request: Request, call_next):  # type: ignore[no-untyped-def]
    request_id = request.headers.get("X-Request-ID", "")
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "http.request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        request_id=request_id,
    )
    return response


# ── Health endpoints ──────────────────────────────────────────────────────────


@app.get("/health", tags=["health"])
async def liveness() -> dict[str, str]:
    """Kubernetes liveness probe."""
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
async def readiness(request: Request) -> JSONResponse:
    """Kubernetes readiness probe — checks DB and cache."""
    errors: list[str] = []

    try:
        async with request.app.state.session_factory() as session:
            from sqlalchemy import text
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        errors.append(f"db: {exc}")

    if not await request.app.state.cache.ping():
        errors.append("cache: unreachable")

    if errors:
        return JSONResponse(status_code=503, content={"status": "not_ready", "errors": errors})
    return JSONResponse({"status": "ready"})


# ── Static files (agent packages) ────────────────────────────────────────────

_pkg_dir = settings.agent_package_dir
if os.path.isdir(_pkg_dir):
    app.mount("/downloads", StaticFiles(directory=_pkg_dir), name="downloads")

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(api_v1_router, prefix="/api/v1")


# ── Validation error handler ──────────────────────────────────────────────────

from fastapi.exceptions import RequestValidationError  # noqa: E402


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": "Validation error", "errors": exc.errors()[:5]},
    )


# ── Dev entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "lokilinux.main:app",
        host="0.0.0.0",
        port=8000,
        workers=int(os.getenv("API_WORKERS", "4")),
        loop="uvloop",
        http="httptools",
        access_log=False,
        use_colors=False,
    )
