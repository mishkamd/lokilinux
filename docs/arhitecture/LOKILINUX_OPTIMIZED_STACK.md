# LokiLinux — Minimal & Optimized Stack

**Performance-First Architecture**

- Backend: FastAPI (async-only, uvicorn)
- Database: PostgreSQL 17 (optimized)
- Cache: Redis (strategy-driven)
- Frontend: Nuxt 4 + shadcn/ui (minimal bundle)
- Agent: Go binary (static, ~15MB)
- UI Colors: OKLCH color system

---

## I. OPTIMIZED STACK OVERVIEW

```
┌─────────────────────────────────────────────┐
│     LokiLinux — Minimal Stack (v1.0)       │
├─────────────────────────────────────────────┤
│                                             │
│  Frontend (Nuxt 4 + shadcn/ui)             │
│  Bundle: ~150KB gzip                       │
│  Server: Node.js minimal                   │
│                                             │
│  API Gateway (FastAPI)                     │
│  Workers: 4-8 (uvicorn)                    │
│  Async: 100% non-blocking                  │
│                                             │
│  Cache Layer (Redis)                       │
│  Strategy: cache-aside + TTL               │
│  Memory: 512MB-2GB                         │
│                                             │
│  Database (PostgreSQL 17)                  │
│  Optimized: connection pool, indexes       │
│  Storage: minimal schema                   │
│                                             │
│  Agent (Go Binary)                         │
│  Size: ~15MB static binary                 │
│  Memory: <50MB idle                        │
│  CPU: <1% idle                             │
│                                             │
└─────────────────────────────────────────────┘
```

**Total footprint:** ~1.5GB for all services (DB not included)

---

## II. FASTAPI BACKEND — ULTRA-OPTIMIZED

### 2.1 Minimal Dependency Tree

**File:** `backend/pyproject.toml`

```toml
[project]
name = "lokilinux"
version = "1.0.0"
description = "Minimal Linux fleet management platform"
requires-python = ">=3.11"

dependencies = [
    # Core FastAPI stack (minimal)
    "fastapi==0.104.1",
    "uvicorn[standard]==0.24.0",
    "pydantic==2.5.0",
    "pydantic-settings==2.1.0",
    
    # Database
    "sqlalchemy==2.0.23",
    "psycopg[binary]==3.9.10",  # PostgreSQL async driver
    "alembic==1.12.1",
    
    # Caching
    "redis==5.0.1",
    "hiredis==2.2.3",  # C parser for faster Redis
    
    # Security
    "python-jose[cryptography]==3.3.0",
    "passlib[bcrypt]==1.7.4",
    "python-multipart==0.0.6",
    
    # gRPC (optional, for agents)
    "grpcio==1.60.0",
    "grpcio-tools==1.60.0",
    "protobuf==4.25.1",
    
    # Utilities
    "httpx==0.25.2",
    "python-dotenv==1.0.0",
    "structlog==23.2.0",  # Structured logging
]

[project.optional-dependencies]
dev = [
    "pytest==7.4.3",
    "pytest-asyncio==0.21.1",
    "pytest-cov==4.1.0",
    "black==23.12.0",
    "ruff==0.1.8",
]
```

### 2.2 Optimized FastAPI Application

**File:** `backend/lokilinux/main.py`

```python
"""
LokiLinux FastAPI Application — Optimized for Performance
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZIPMiddleware
from fastapi.responses import ORJSONResponse
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

import structlog
from uvicorn.config import Config

from lokilinux.api.v1 import router as api_router_v1
from lokilinux.config import Settings
from lokilinux.db import get_db_session, init_db
from lokilinux.cache import RedisCache

# ============================================================================
# CONFIGURATION
# ============================================================================

settings = Settings()

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()

# ============================================================================
# LIFESPAN MANAGEMENT (FastAPI 0.93+)
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown"""
    
    # Startup
    logger.info("Starting LokiLinux API", version="1.0.0")
    
    # Initialize database
    await init_db()
    logger.info("Database initialized")
    
    # Initialize cache
    redis = RedisCache(url=settings.redis_url)
    await redis.connect()
    logger.info("Cache connected")
    
    # Store in app state for dependency injection
    app.state.redis = redis
    app.state.db_engine = create_async_engine(
        settings.database_url,
        echo=False,  # No SQL logging in production
        pool_size=20,
        max_overflow=10,
        pool_pre_ping=True,  # Test connection before use
        pool_recycle=3600,
    )
    
    yield
    
    # Shutdown
    logger.info("Shutting down LokiLinux API")
    await redis.disconnect()
    await app.state.db_engine.dispose()

# ============================================================================
# APPLICATION INITIALIZATION
# ============================================================================

app = FastAPI(
    title="LokiLinux API",
    version="1.0.0",
    description="Minimal Linux fleet management platform",
    lifespan=lifespan,
    default_response_class=ORJSONResponse,  # Use orjson for faster JSON
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,  # Disable ReDoc to save bandwidth
    openapi_url="/openapi.json" if settings.debug else None,
)

# ============================================================================
# MIDDLEWARE STACK (Order matters!)
# ============================================================================

# 1. CORS (restrictive)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=3600,  # Cache preflight for 1 hour
)

# 2. GZIP compression (>1KB responses only)
app.add_middleware(
    GZIPMiddleware,
    minimum_size=1024,
    compresslevel=6,  # Balance between compression and CPU
)

# ============================================================================
# REQUEST/RESPONSE LIFECYCLE
# ============================================================================

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """Add request ID for tracing"""
    request_id = request.headers.get("X-Request-ID", "")
    request.state.request_id = request_id
    
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests (structured)"""
    method = request.method
    path = request.url.path
    
    response = await call_next(request)
    
    logger.info(
        "request",
        method=method,
        path=path,
        status_code=response.status_code,
    )
    
    return response

# ============================================================================
# HEALTH CHECKS
# ============================================================================

@app.get("/health")
async def health_check():
    """Liveness probe"""
    return {"status": "ok"}

@app.get("/ready")
async def readiness_check():
    """Readiness probe (checks dependencies)"""
    try:
        # Check database
        async with AsyncSession(app.state.db_engine) as session:
            await session.execute("SELECT 1")
        
        # Check cache
        await app.state.redis.ping()
        
        return {"status": "ready"}
    except Exception as e:
        return {"status": "not_ready", "error": str(e)}, 503

# ============================================================================
# API ROUTES
# ============================================================================

app.include_router(
    api_router_v1,
    prefix="/api/v1",
    tags=["v1"],
)

# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================

@app.get("/inject/db")
async def get_db() -> AsyncSession:
    """FastAPI dependency: inject DB session"""
    async with AsyncSession(app.state.db_engine) as session:
        yield session

@app.get("/inject/cache")
async def get_cache() -> RedisCache:
    """FastAPI dependency: inject Redis cache"""
    return app.state.redis

# ============================================================================
# ERROR HANDLERS
# ============================================================================

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    """Handle validation errors efficiently"""
    return JSONResponse(
        status_code=422,
        content={"detail": "Validation error", "errors": exc.errors()[:5]},  # Limit errors
    )

# ============================================================================
# STARTUP COMMANDS
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "lokilinux.main:app",
        host="0.0.0.0",
        port=8000,
        workers=int(os.getenv("API_WORKERS", "4")),
        loop="uvloop",  # Fast event loop
        http="httptools",  # Fast HTTP parser
        ws_max_size=16_777_216,  # 16MB for large payloads
        access_log=False,  # Disable access logs (use middleware instead)
        use_colors=False,
    )
```

### 2.3 Database Configuration (PostgreSQL 17)

**File:** `backend/lokilinux/db.py`

```python
"""
Database configuration — PostgreSQL 17 optimized
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

import structlog

logger = structlog.get_logger()

async def init_db():
    """Initialize database with optimized settings"""
    
    # Create engine with optimizations
    engine = create_async_engine(
        "postgresql+asyncpg://user:pass@postgres:5432/lokilinux",
        
        # Connection pooling
        poolclass=QueuePool,
        pool_size=20,              # Connections to keep in pool
        max_overflow=10,           # Additional connections allowed
        pool_recycle=3600,         # Recycle connections after 1h
        pool_pre_ping=True,        # Verify connection before using
        
        # Performance
        echo=False,                # No SQL logging
        echo_pool=False,           # No pool logging
        
        # Async options
        execution_options={
            "isolation_level": "READ_COMMITTED",  # Not SERIALIZABLE
            "prepared_statement_cache_size": 500,
            "prepared_statement_name_func": lambda *args: None,  # Disable prepared statements overhead
        },
    )
    
    # Run migrations
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.operations import Operations
    
    async with engine.begin() as conn:
        await conn.run_sync(run_migrations)
    
    logger.info("Database initialized successfully")
    return engine

async def run_migrations(connection):
    """Run database migrations"""
    from alembic import command
    from alembic.config import Config
    
    alembic_cfg = Config("alembic.ini")
    ctx = MigrationContext.configure(connection)
    op = Operations(ctx)
    
    command.upgrade(alembic_cfg, "head")

# Dependency injection
async def get_db_session(engine) -> AsyncSession:
    """Get database session"""
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        yield session
```

### 2.4 Cache Strategy (Redis)

**File:** `backend/lokilinux/cache.py`

```python
"""
Redis caching layer — optimized for performance
"""

import json
from typing import Any, Optional
from datetime import timedelta

import redis.asyncio as redis
import structlog

logger = structlog.get_logger()

class RedisCache:
    """High-performance Redis cache with automatic TTL"""
    
    def __init__(self, url: str):
        self.url = url
        self.client: Optional[redis.Redis] = None
    
    async def connect(self):
        """Connect to Redis with optimizations"""
        self.client = await redis.from_url(
            self.url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50,
            socket_connect_timeout=5,
            socket_keepalive=True,
            health_check_interval=30,
        )
        
        logger.info("Connected to Redis")
    
    async def disconnect(self):
        """Disconnect from Redis"""
        if self.client:
            await self.client.close()
    
    async def ping(self) -> bool:
        """Health check"""
        try:
            return await self.client.ping()
        except:
            return False
    
    # ==================== CACHE OPERATIONS ====================
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        try:
            value = await self.client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.warning("Cache GET error", key=key, error=str(e))
            return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[timedelta] = None
    ):
        """Set value in cache with optional TTL"""
        try:
            await self.client.set(
                key,
                json.dumps(value),
                ex=int(ttl.total_seconds()) if ttl else None,
            )
        except Exception as e:
            logger.warning("Cache SET error", key=key, error=str(e))
    
    async def delete(self, key: str):
        """Delete key from cache"""
        try:
            await self.client.delete(key)
        except Exception as e:
            logger.warning("Cache DELETE error", key=key, error=str(e))
    
    async def clear(self, pattern: str = "*"):
        """Clear multiple keys by pattern"""
        try:
            keys = await self.client.keys(pattern)
            if keys:
                await self.client.delete(*keys)
        except Exception as e:
            logger.warning("Cache CLEAR error", pattern=pattern, error=str(e))
    
    # ==================== CACHE INVALIDATION ====================
    
    async def invalidate_agent(self, agent_id: str):
        """Invalidate all caches for an agent"""
        await self.delete(f"agent:{agent_id}:*")
        await self.delete(f"inventory:{agent_id}:*")
        await self.delete(f"metrics:{agent_id}:*")
    
    async def invalidate_cve(self):
        """Invalidate CVE cache"""
        await self.delete("cve:database:*")
        await self.delete("vulnerability:*")

# ==================== CACHE KEYS STRATEGY ====================
"""
Cache key naming convention:
  
  agent:{agent_id}:status
  agent:{agent_id}:health
  agent:{agent_id}:packages
  
  inventory:{agent_id}:system_info
  inventory:{agent_id}:installed_packages
  
  job:{job_id}:status
  job:{job_id}:results
  
  cve:database:version
  cve:{cve_id}:details
  vulnerability:{agent_id}:list
  
  policy:{policy_id}:rules
  
  session:{session_id}:user_data

TTL Strategy:
  - Agent status: 5 minutes
  - Inventory: 30 minutes
  - CVE data: 24 hours
  - Job status: 1 hour
  - Sessions: 7 days
"""
```

### 2.5 Minimal API Router Example

**File:** `backend/lokilinux/api/v1/routers/servers.py`

```python
"""
Optimized server/agent endpoint
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta

import structlog

from lokilinux.cache import RedisCache
from lokilinux.models import Agent
from lokilinux.schemas import ServerResponse, ServerListResponse

logger = structlog.get_logger()

router = APIRouter(prefix="/servers", tags=["servers"])

# ============================================================================
# LIST SERVERS (with caching)
# ============================================================================

@router.get("", response_model=ServerListResponse)
async def list_servers(
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
):
    """
    List all servers with caching
    
    Cache strategy:
    - Cache full list for 5 minutes
    - Invalidate on any agent update
    """
    
    cache_key = f"server:list:{limit}:{offset}"
    
    # Try cache first
    cached = await cache.get(cache_key)
    if cached:
        logger.info("server_list_cached", limit=limit, offset=offset)
        return cached
    
    # Database query (optimized)
    query = (
        select(Agent)
        .limit(limit)
        .offset(offset)
        .order_by(Agent.created_at.desc())
    )
    
    result = await db.execute(query)
    agents = result.scalars().all()
    
    # Count total (separate query for performance)
    count_query = select(func.count()).select_from(Agent)
    count_result = await db.execute(count_query)
    total = count_result.scalar()
    
    response = ServerListResponse(
        servers=[ServerResponse.from_orm(a) for a in agents],
        total=total,
        limit=limit,
        offset=offset,
    )
    
    # Cache for 5 minutes
    await cache.set(cache_key, response.dict(), ttl=timedelta(minutes=5))
    
    logger.info("server_list_fetched", total=total, limit=limit)
    return response

# ============================================================================
# GET SERVER DETAIL (with caching)
# ============================================================================

@router.get("/{agent_id}", response_model=ServerResponse)
async def get_server(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
):
    """Get server detail with caching"""
    
    cache_key = f"agent:{agent_id}:detail"
    
    # Try cache first
    cached = await cache.get(cache_key)
    if cached:
        logger.info("server_detail_cached", agent_id=agent_id)
        return ServerResponse(**cached)
    
    # Database query
    query = select(Agent).where(Agent.agent_id == agent_id)
    result = await db.execute(query)
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(status_code=404, detail="Server not found")
    
    response = ServerResponse.from_orm(agent)
    
    # Cache for 5 minutes
    await cache.set(cache_key, response.dict(), ttl=timedelta(minutes=5))
    
    return response

# ============================================================================
# UPDATE SERVER (invalidates cache)
# ============================================================================

@router.patch("/{agent_id}")
async def update_server(
    agent_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
):
    """Update server and invalidate cache"""
    
    # Update in database
    query = select(Agent).where(Agent.agent_id == agent_id)
    result = await db.execute(query)
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(status_code=404)
    
    for key, value in data.items():
        setattr(agent, key, value)
    
    agent.updated_at = datetime.utcnow()
    await db.commit()
    
    # Invalidate caches
    await cache.invalidate_agent(agent_id)
    
    logger.info("server_updated", agent_id=agent_id)
    
    return {"status": "updated"}
```

---

## III. POSTGRESQL 17 — OPTIMIZED

### 3.1 `postgresql.conf` Optimizations

**File:** `config/postgresql.conf`

```ini
# ============================================================================
# PostgreSQL 17 Optimizations for LokiLinux
# ============================================================================

# Connection Settings
max_connections = 200
superuser_reserved_connections = 10

# Memory Settings (for 4GB total available)
shared_buffers = 1GB                    # 25% of RAM
effective_cache_size = 3GB              # 75% of RAM
work_mem = 25MB                         # (RAM / max_connections) * 2
maintenance_work_mem = 256MB

# Checkpoint Settings
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100

# Query Planner
random_page_cost = 1.1                  # SSD-optimized
effective_io_concurrency = 200

# Parallel Execution
max_parallel_workers_per_gather = 4
max_parallel_workers = 4
max_parallel_maintenance_workers = 4

# Logging (minimal)
log_min_duration_statement = 1000       # Log slow queries (>1s)
log_line_prefix = '%t [%p]: [%l-1] user=%u,db=%d,app=%a,client=%h '
log_checkpoints = off
log_connections = off
log_disconnections = off
log_duration = off
log_lock_waits = off
log_statement = off

# Performance
jit = on                                # JIT compilation
jit_above_cost = 100000
jit_inline_above_cost = 500000
jit_optimize_above_cost = 500000

# Autovacuum
autovacuum = on
autovacuum_max_workers = 3
autovacuum_naptime = 10s
autovacuum_vacuum_scale_factor = 0.02

# SSL (if needed)
ssl = off                               # Enable only if using remote connections
```

### 3.2 Minimal Schema (Optimized)

**File:** `backend/alembic/versions/001_initial.py`

```python
"""
LokiLinux Minimal Schema — Performance optimized
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade():
    """Create optimized schema"""
    
    # ============================================================================
    # AGENTS TABLE
    # ============================================================================
    op.create_table(
        'agents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('agent_id', sa.String(255), unique=True, nullable=False, index=True),
        
        # Status
        sa.Column('status', sa.String(50), default='ACTIVE', index=True),
        sa.Column('last_heartbeat', sa.DateTime, nullable=True, index=True),
        
        # Info
        sa.Column('hostname', sa.String(255), nullable=False),
        sa.Column('os_distro', sa.String(100), nullable=False, index=True),
        sa.Column('os_version', sa.String(50), nullable=False),
        
        # Metadata
        sa.Column('tags', postgresql.JSONB, default={}, nullable=False),
        sa.Column('custom_facts', postgresql.JSONB, default={}, nullable=False),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime, default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, default=sa.func.now(), onupdate=sa.func.now()),
        
        # Indexes
        sa.Index('idx_agent_status', 'status'),
        sa.Index('idx_agent_hostname', 'hostname'),
        sa.Index('idx_agent_os', 'os_distro'),
        sa.Index('idx_agent_last_heartbeat', 'last_heartbeat'),
    )
    
    # ============================================================================
    # PACKAGES TABLE (minimal)
    # ============================================================================
    op.create_table(
        'packages',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='CASCADE')),
        
        # Package info
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('version', sa.String(100), nullable=False),
        sa.Column('arch', sa.String(50)),
        
        # Update status
        sa.Column('has_update', sa.Boolean, default=False),
        sa.Column('latest_version', sa.String(100)),
        
        # Timestamps
        sa.Column('updated_at', sa.DateTime, default=sa.func.now()),
        
        # Indexes
        sa.Index('idx_package_agent_id', 'agent_id'),
        sa.Index('idx_package_name', 'name'),
        sa.Index('idx_package_has_update', 'has_update'),
        
        # Constraint (prevent duplicates)
        sa.UniqueConstraint('agent_id', 'name', 'version', name='uq_agent_package'),
    )
    
    # ============================================================================
    # JOBS TABLE
    # ============================================================================
    op.create_table(
        'jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        
        # Metadata
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('job_type', sa.String(50), nullable=False, index=True),
        sa.Column('status', sa.String(50), default='QUEUED', index=True),
        
        # Scope (JSONB for flexibility)
        sa.Column('target_servers', postgresql.JSONB, nullable=False),
        sa.Column('total_servers', sa.Integer),
        
        # Parameters
        sa.Column('parameters', postgresql.JSONB),
        
        # Timestamps
        sa.Column('scheduled_time', sa.DateTime),
        sa.Column('started_at', sa.DateTime),
        sa.Column('completed_at', sa.DateTime),
        sa.Column('created_at', sa.DateTime, default=sa.func.now()),
        
        # Indexes
        sa.Index('idx_job_status', 'status'),
        sa.Index('idx_job_type', 'job_type'),
        sa.Index('idx_job_scheduled', 'scheduled_time'),
    )
    
    # ============================================================================
    # JOB RESULTS TABLE (streaming results)
    # ============================================================================
    op.create_table(
        'job_results',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('job_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('jobs.id', ondelete='CASCADE')),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='CASCADE')),
        
        # Status
        sa.Column('status', sa.String(50), nullable=False, index=True),
        sa.Column('exit_code', sa.Integer),
        sa.Column('error_message', sa.Text),
        
        # Output (JSONB for structured data)
        sa.Column('output', postgresql.JSONB),
        
        # Timestamps
        sa.Column('started_at', sa.DateTime),
        sa.Column('completed_at', sa.DateTime),
        sa.Column('created_at', sa.DateTime, default=sa.func.now()),
        
        # Indexes
        sa.Index('idx_job_result_job_id', 'job_id'),
        sa.Index('idx_job_result_agent_id', 'agent_id'),
        sa.Index('idx_job_result_status', 'status'),
    )
    
    # ============================================================================
    # CVE TABLE (minimal)
    # ============================================================================
    op.create_table(
        'cves',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('cve_id', sa.String(50), unique=True, nullable=False, index=True),
        
        # Severity
        sa.Column('cvss_score', sa.Float),
        sa.Column('severity', sa.String(20), nullable=False, index=True),
        
        # Description
        sa.Column('title', sa.String(255)),
        sa.Column('description', sa.Text),
        
        # Package mapping
        sa.Column('affected_packages', postgresql.JSONB),
        
        # Timestamps
        sa.Column('published_date', sa.Date),
        sa.Column('updated_at', sa.DateTime, default=sa.func.now()),
        
        # Indexes
        sa.Index('idx_cve_id', 'cve_id'),
        sa.Index('idx_cve_severity', 'severity'),
        sa.Index('idx_cve_score', 'cvss_score'),
    )
    
    # ============================================================================
    # AGENT VULNERABILITIES
    # ============================================================================
    op.create_table(
        'agent_vulnerabilities',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='CASCADE')),
        sa.Column('cve_id', sa.String(50), sa.ForeignKey('cves.cve_id', ondelete='CASCADE')),
        
        # Package info
        sa.Column('package_name', sa.String(255), nullable=False),
        sa.Column('package_version', sa.String(100), nullable=False),
        
        # Severity
        sa.Column('cvss_score', sa.Float),
        sa.Column('severity', sa.String(20), index=True),
        
        # Fix status
        sa.Column('fix_available', sa.Boolean),
        sa.Column('recommended_action', sa.String(50)),
        
        # Remediation
        sa.Column('is_remediated', sa.Boolean, default=False, index=True),
        sa.Column('remediation_date', sa.DateTime),
        
        # Timestamps
        sa.Column('discovered_at', sa.DateTime, default=sa.func.now()),
        sa.Column('last_check', sa.DateTime, default=sa.func.now()),
        
        # Indexes
        sa.Index('idx_vuln_agent_id', 'agent_id'),
        sa.Index('idx_vuln_cve_id', 'cve_id'),
        sa.Index('idx_vuln_severity', 'severity'),
        sa.Index('idx_vuln_remediated', 'is_remediated'),
    )
    
    # ============================================================================
    # USERS TABLE (minimal RBAC)
    # ============================================================================
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('username', sa.String(255), unique=True, nullable=False, index=True),
        sa.Column('email', sa.String(255), unique=True, nullable=False, index=True),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('role', sa.String(50), default='viewer'),  # admin, manager, operator, viewer
        sa.Column('is_active', sa.Boolean, default=True, index=True),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime, default=sa.func.now()),
        sa.Column('last_login', sa.DateTime),
    )
    
    # ============================================================================
    # AUDIT LOGS (minimal)
    # ============================================================================
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
        
        # Action
        sa.Column('action', sa.String(100), nullable=False, index=True),
        sa.Column('resource_type', sa.String(100), nullable=False),
        sa.Column('resource_id', sa.String(255)),
        
        # Details
        sa.Column('changes', postgresql.JSONB),
        sa.Column('status', sa.String(50)),
        
        # Timestamps
        sa.Column('timestamp', sa.DateTime, default=sa.func.now(), index=True),
        
        # Indexes
        sa.Index('idx_audit_action', 'action'),
        sa.Index('idx_audit_resource', 'resource_type'),
        sa.Index('idx_audit_timestamp', 'timestamp'),
    )

def downgrade():
    """Drop all tables"""
    op.drop_table('audit_logs')
    op.drop_table('users')
    op.drop_table('agent_vulnerabilities')
    op.drop_table('cves')
    op.drop_table('job_results')
    op.drop_table('jobs')
    op.drop_table('packages')
    op.drop_table('agents')
```

---

## IV. NUXT 4 + shadcn/ui — ULTRA-MINIMAL

### 4.1 Nuxt Configuration (Minimal)

**File:** `frontend/nuxt.config.ts`

```typescript
// Nuxt 4 optimized configuration

export default defineNuxtConfig({
  // Core
  ssr: true,                           // Server-side rendering for SEO
  modules: ['@nuxt/ui'],
  
  // Build optimization
  nitro: {
    prerender: {
      // Pre-render these routes
      routes: ['/'],
      crawlLinks: true,
    },
    compression: 'gzip',
    headers: {
      'Cache-Control': 'public, max-age=3600',
    },
  },
  
  // CSS
  css: ['~/assets/css/global.css'],
  
  // Build
  build: {
    // Analyze bundle
    analyze: false,
    
    // Transpile only necessary
    transpile: [],
  },
  
  // Performance
  performance: {
    metrics: true,
  },
  
  // API
  runtimeConfig: {
    public: {
      apiUrl: process.env.NUXT_PUBLIC_API_URL || 'http://localhost:8000',
    },
  },
  
  // Fonts (minimal)
  googleFonts: {
    families: {
      Poppins: [400, 500, 600, 700],
    },
    preconnect: true,
    display: 'swap',
  },
  
  // Color mode
  colorMode: {
    preference: 'system',
    fallback: 'dark',
    hid: 'nuxt-color-mode-script',
  },
  
  // Typescript
  typescript: {
    strict: true,
    typeCheck: false,  // Type check at build time only
  },
})
```

### 4.2 Global CSS (OKLCH Colors)

**File:** `frontend/assets/css/global.css`

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --background: oklch(1 0 0);
  --foreground: oklch(0.145 0 0);
  --card: oklch(1 0 0);
  --card-foreground: oklch(0.145 0 0);
  --popover: oklch(1 0 0);
  --popover-foreground: oklch(0.145 0 0);
  --primary: oklch(0.505 0.213 27.518);
  --primary-foreground: oklch(0.971 0.013 17.38);
  --secondary: oklch(0.967 0.001 286.375);
  --secondary-foreground: oklch(0.21 0.006 285.885);
  --muted: oklch(0.97 0 0);
  --muted-foreground: oklch(0.556 0 0);
  --accent: oklch(0.97 0 0);
  --accent-foreground: oklch(0.205 0 0);
  --destructive: oklch(0.577 0.245 27.325);
  --border: oklch(0.922 0 0);
  --input: oklch(0.922 0 0);
  --ring: oklch(0.708 0 0);
  --chart-1: oklch(0.808 0.114 19.571);
  --chart-2: oklch(0.637 0.237 25.331);
  --chart-3: oklch(0.577 0.245 27.325);
  --chart-4: oklch(0.505 0.213 27.518);
  --chart-5: oklch(0.444 0.177 26.899);
  --radius: 0.625rem;
  --sidebar: oklch(0.985 0 0);
  --sidebar-foreground: oklch(0.145 0 0);
  --sidebar-primary: oklch(0.577 0.245 27.325);
  --sidebar-primary-foreground: oklch(0.971 0.013 17.38);
  --sidebar-accent: oklch(0.97 0 0);
  --sidebar-accent-foreground: oklch(0.205 0 0);
  --sidebar-border: oklch(0.922 0 0);
  --sidebar-ring: oklch(0.708 0 0);
}

.dark {
  --background: oklch(0.145 0 0);
  --foreground: oklch(0.985 0 0);
  --card: oklch(0.205 0 0);
  --card-foreground: oklch(0.985 0 0);
  --popover: oklch(0.205 0 0);
  --popover-foreground: oklch(0.985 0 0);
  --primary: oklch(0.444 0.177 26.899);
  --primary-foreground: oklch(0.971 0.013 17.38);
  --secondary: oklch(0.274 0.006 286.033);
  --secondary-foreground: oklch(0.985 0 0);
  --muted: oklch(0.269 0 0);
  --muted-foreground: oklch(0.708 0 0);
  --accent: oklch(0.269 0 0);
  --accent-foreground: oklch(0.985 0 0);
  --destructive: oklch(0.704 0.191 22.216);
  --border: oklch(1 0 0 / 10%);
  --input: oklch(1 0 0 / 15%);
  --ring: oklch(0.556 0 0);
  --chart-1: oklch(0.808 0.114 19.571);
  --chart-2: oklch(0.637 0.237 25.331);
  --chart-3: oklch(0.577 0.245 27.325);
  --chart-4: oklch(0.505 0.213 27.518);
  --chart-5: oklch(0.444 0.177 26.899);
  --sidebar: oklch(0.205 0 0);
  --sidebar-foreground: oklch(0.985 0 0);
  --sidebar-primary: oklch(0.637 0.237 25.331);
  --sidebar-primary-foreground: oklch(0.971 0.013 17.38);
  --sidebar-accent: oklch(0.269 0 0);
  --sidebar-accent-foreground: oklch(0.985 0 0);
  --sidebar-border: oklch(1 0 0 / 10%);
  --sidebar-ring: oklch(0.556 0 0);
}

/* Minimal reset */
* {
  @apply border-border;
}

body {
  @apply bg-background text-foreground;
  font-feature-settings: "rounding-mode" auto;
}

/* Typography */
h1, h2, h3, h4, h5, h6 {
  @apply font-semibold leading-tight;
}

/* Utility classes for common patterns */
.container-max {
  @apply max-w-7xl mx-auto px-4 sm:px-6 lg:px-8;
}

.glass {
  @apply bg-background/50 backdrop-blur-md border border-border;
}

.text-muted {
  @apply text-muted-foreground;
}
```

### 4.3 Minimal Package.json

**File:** `frontend/package.json`

```json
{
  "name": "lokilinux-frontend",
  "version": "1.0.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "nuxi dev",
    "build": "nuxi build",
    "preview": "nuxi preview",
    "generate": "nuxi generate"
  },
  "dependencies": {
    "nuxt": "^3.8.2",
    "@nuxt/ui": "^2.13.0",
    "@nuxt/image": "^1.1.0",
    "tailwindcss": "^3.4.0",
    "radix-ui": "^1.0.0",
    "class-variance-authority": "^0.7.0",
    "clsx": "^2.0.0",
    "tailwind-merge": "^2.2.0",
    "next-themes": "^0.2.1"
  },
  "devDependencies": {
    "@nuxtjs/tailwindcss": "^6.11.0",
    "typescript": "^5.3.0",
    "vue": "^3.3.0"
  }
}
```

### 4.4 Example Component (minimal shadcn)

**File:** `frontend/components/ServerCard.vue`

```vue
<template>
  <div class="rounded-lg border bg-card text-card-foreground shadow-sm p-4 hover:shadow-md transition-shadow">
    <!-- Header -->
    <div class="flex items-center justify-between mb-4">
      <div>
        <h3 class="font-semibold text-lg">{{ server.hostname }}</h3>
        <p class="text-sm text-muted-foreground">{{ server.os_distro }} {{ server.os_version }}</p>
      </div>
      
      <!-- Status Badge -->
      <div :class="['rounded-full px-3 py-1 text-xs font-medium',
        statusBadgeClass]">
        {{ server.status }}
      </div>
    </div>
    
    <!-- Stats -->
    <div class="grid grid-cols-3 gap-4 mb-4">
      <div>
        <p class="text-xs text-muted-foreground">Heartbeat</p>
        <p class="text-sm font-semibold">{{ formatTime(server.last_heartbeat) }}</p>
      </div>
      <div>
        <p class="text-xs text-muted-foreground">CVE Count</p>
        <p class="text-sm font-semibold text-destructive">{{ server.cve_count }}</p>
      </div>
      <div>
        <p class="text-xs text-muted-foreground">Uptime</p>
        <p class="text-sm font-semibold">{{ server.uptime }}</p>
      </div>
    </div>
    
    <!-- Action Button -->
    <button 
      @click="$emit('view-detail')"
      class="w-full rounded-md bg-primary text-primary-foreground px-3 py-2 text-sm font-medium hover:bg-primary/90 transition-colors"
    >
      View Details
    </button>
  </div>
</template>

<script setup lang="ts">
defineProps({
  server: {
    type: Object,
    required: true
  }
})

defineEmits(['view-detail'])

const formatTime = (date: string) => {
  if (!date) return 'Never'
  const now = new Date()
  const diff = now.getTime() - new Date(date).getTime()
  const minutes = Math.floor(diff / 60000)
  
  if (minutes < 1) return 'Just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

const statusBadgeClass = computed(() => {
  const classes = {
    'ACTIVE': 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100',
    'INACTIVE': 'bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-100',
    'UNHEALTHY': 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100',
  }
  return classes[server.status] || classes['INACTIVE']
})
</script>
```

---

## V. GO AGENT — MINIMAL BINARY

### 5.1 Agent Main Structure

**File:** `agent/main.go`

```go
package main

import (
	"context"
	"flag"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/lokilinux/agent/internal/agent"
	"github.com/lokilinux/agent/internal/config"
)

func main() {
	// Parse flags
	configPath := flag.String("config", "/etc/lokilinux/agent.env", "Config file path")
	flag.Parse()

	// Load config from .env
	cfg, err := config.LoadFromFile(*configPath)
	if err != nil {
		slog.Error("Failed to load config", "error", err)
		os.Exit(1)
	}

	// Setup logging
	logger := setupLogger(cfg.LogLevel)

	// Create agent
	agentInstance, err := agent.New(cfg, logger)
	if err != nil {
		logger.Error("Failed to create agent", "error", err)
		os.Exit(1)
	}

	// Context
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Start agent
	logger.Info("Starting LokiLinux Agent", "agent_id", cfg.AgentID, "version", "1.0.0")
	
	go agentInstance.Start(ctx)

	// Wait for signal
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	
	<-sigChan
	logger.Info("Shutting down...")
	
	cancel()
	agentInstance.Stop()
}

func setupLogger(level string) *slog.Logger {
	opts := &slog.HandlerOptions{
		Level: parseLogLevel(level),
	}
	handler := slog.NewJSONHandler(os.Stderr, opts)
	return slog.New(handler)
}

func parseLogLevel(level string) slog.Level {
	switch level {
	case "debug":
		return slog.LevelDebug
	case "info":
		return slog.LevelInfo
	case "warn":
		return slog.LevelWarn
	case "error":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}
```

### 5.2 Agent Core Loop

**File:** `agent/internal/agent/manager.go`

```go
package agent

import (
	"context"
	"log/slog"
	"time"

	"github.com/lokilinux/agent/internal/config"
	"github.com/lokilinux/agent/internal/communication"
	"github.com/lokilinux/agent/internal/modules"
)

type Agent struct {
	cfg        *config.Config
	logger     *slog.Logger
	client     *communication.GRPCClient
	modules    *modules.ModuleManager
	ticker     *time.Ticker
	stopChan   chan struct{}
}

func New(cfg *config.Config, logger *slog.Logger) (*Agent, error) {
	// Initialize gRPC client
	client, err := communication.NewGRPCClient(cfg.PlatformURL, cfg.AgentCertPath, cfg.AgentKeyPath)
	if err != nil {
		return nil, err
	}

	// Initialize modules
	modulesMgr := modules.NewModuleManager(logger)
	modulesMgr.RegisterModule("system_info", modules.NewSystemInfoModule())
	modulesMgr.RegisterModule("package_manager", modules.NewPackageManagerModule())
	modulesMgr.RegisterModule("vulnerability_scanner", modules.NewVulnerabilityModule())
	modulesMgr.RegisterModule("metrics", modules.NewMetricsModule())

	return &Agent{
		cfg:      cfg,
		logger:   logger,
		client:   client,
		modules:  modulesMgr,
		stopChan: make(chan struct{}),
	}, nil
}

func (a *Agent) Start(ctx context.Context) {
	// Heartbeat interval
	heartbeatInterval := time.Duration(a.cfg.HeartbeatIntervalSeconds) * time.Second
	a.ticker = time.NewTicker(heartbeatInterval)
	defer a.ticker.Stop()

	// Initial heartbeat
	a.sendHeartbeat(ctx)

	for {
		select {
		case <-ctx.Done():
			return
		case <-a.stopChan:
			return
		case <-a.ticker.C:
			a.sendHeartbeat(ctx)
		}
	}
}

func (a *Agent) sendHeartbeat(ctx context.Context) {
	// Collect system info
	systemInfo, err := a.modules.Execute("system_info")
	if err != nil {
		a.logger.Error("Failed to collect system info", "error", err)
		return
	}

	// Collect packages
	packages, err := a.modules.Execute("package_manager")
	if err != nil {
		a.logger.Error("Failed to collect packages", "error", err)
	}

	// Collect vulnerabilities
	vulnerabilities, err := a.modules.Execute("vulnerability_scanner")
	if err != nil {
		a.logger.Error("Failed to scan vulnerabilities", "error", err)
	}

	// Collect metrics
	metrics, err := a.modules.Execute("metrics")
	if err != nil {
		a.logger.Error("Failed to collect metrics", "error", err)
	}

	// Build heartbeat payload
	heartbeat := map[string]interface{}{
		"agent_id":         a.cfg.AgentID,
		"timestamp":        time.Now().Unix(),
		"system":           systemInfo,
		"packages":         packages,
		"vulnerabilities":  vulnerabilities,
		"metrics":          metrics,
	}

	// Send to platform
	response, err := a.client.SendHeartbeat(ctx, heartbeat)
	if err != nil {
		a.logger.Error("Failed to send heartbeat", "error", err)
		return
	}

	// Process response (jobs, policies, etc.)
	a.processHeartbeatResponse(ctx, response)

	a.logger.Debug("Heartbeat sent", "agent_id", a.cfg.AgentID)
}

func (a *Agent) processHeartbeatResponse(ctx context.Context, response map[string]interface{}) {
	// Handle pending jobs, policy updates, etc.
	if jobs, ok := response["pending_jobs"]; ok {
		a.logger.Info("Received jobs", "count", len(jobs.([]interface{})))
		// Execute jobs...
	}
}

func (a *Agent) Stop() {
	close(a.stopChan)
}
```

### 5.3 System Info Module (Minimal)

**File:** `agent/internal/modules/system_info.go`

```go
package modules

import (
	"os"
	"runtime"
	"strings"

	"golang.org/x/sys/unix"
)

type SystemInfoModule struct{}

func NewSystemInfoModule() *SystemInfoModule {
	return &SystemInfoModule{}
}

func (m *SystemInfoModule) Execute() (interface{}, error) {
	hostname, _ := os.Hostname()
	
	// Memory
	var memStats runtime.MemStats
	runtime.ReadMemStats(&memStats)
	
	// Disk
	var stat unix.Statfs_t
	unix.Statfs("/", &stat)
	
	// OS
	osRelease, _ := readOSRelease()
	
	return map[string]interface{}{
		"hostname":         hostname,
		"os_distro":        osRelease["ID"],
		"os_version":       osRelease["VERSION_ID"],
		"kernel":           readKernel(),
		"cpu_count":        runtime.NumCPU(),
		"memory_total":     memStats.Alloc + memStats.TotalAlloc,
		"disk_total":       stat.Blocks * uint64(stat.Bsize),
		"disk_used":        (stat.Blocks - stat.Bfree) * uint64(stat.Bsize),
	}, nil
}

func readKernel() string {
	var uts unix.Utsname
	unix.Uname(&uts)
	return string(uts.Release[:strings.Index(string(uts.Release[:]), "\x00")])
}

func readOSRelease() (map[string]string, error) {
	content, err := os.ReadFile("/etc/os-release")
	if err != nil {
		return nil, err
	}

	osRelease := make(map[string]string)
	for _, line := range strings.Split(string(content), "\n") {
		parts := strings.SplitN(line, "=", 2)
		if len(parts) == 2 {
			osRelease[parts[0]] = strings.Trim(parts[1], "\"")
		}
	}
	return osRelease, nil
}
```

### 5.4 Package Manager Module (APT/DNF)

**File:** `agent/internal/modules/package_manager.go`

```go
package modules

import (
	"os"
	"os/exec"
	"strings"
)

type PackageManagerModule struct{}

func NewPackageManagerModule() *PackageManagerModule {
	return &PackageManagerModule{}
}

func (m *PackageManagerModule) Execute() (interface{}, error) {
	// Detect package manager
	packageManager := detectPackageManager()
	
	var packages []map[string]interface{}
	var err error
	
	if packageManager == "apt" {
		packages, err = m.listAptPackages()
	} else if packageManager == "dnf" {
		packages, err = m.listDnfPackages()
	}
	
	if err != nil {
		return nil, err
	}
	
	return packages, nil
}

func (m *PackageManagerModule) listAptPackages() ([]map[string]interface{}, error) {
	cmd := exec.Command("dpkg", "-l")
	output, err := cmd.Output()
	if err != nil {
		return nil, err
	}

	var packages []map[string]interface{}
	for _, line := range strings.Split(string(output), "\n") {
		if !strings.HasPrefix(line, "ii") {
			continue
		}
		
		parts := strings.Fields(line)
		if len(parts) < 4 {
			continue
		}
		
		packages = append(packages, map[string]interface{}{
			"name":    parts[1],
			"version": parts[2],
		})
	}
	
	return packages, nil
}

func (m *PackageManagerModule) listDnfPackages() ([]map[string]interface{}, error) {
	cmd := exec.Command("rpm", "-qa", "--qf=%{NAME}|%{VERSION}\\n")
	output, err := cmd.Output()
	if err != nil {
		return nil, err
	}

	var packages []map[string]interface{}
	for _, line := range strings.Split(string(output), "\n") {
		parts := strings.Split(line, "|")
		if len(parts) < 2 {
			continue
		}
		
		packages = append(packages, map[string]interface{}{
			"name":    parts[0],
			"version": parts[1],
		})
	}
	
	return packages, nil
}

func detectPackageManager() string {
	if _, err := os.Stat("/usr/bin/apt"); err == nil {
		return "apt"
	}
	if _, err := os.Stat("/usr/bin/dnf"); err == nil {
		return "dnf"
	}
	if _, err := os.Stat("/usr/bin/yum"); err == nil {
		return "yum"
	}
	return "unknown"
}
```

---

## VI. DOCKERFILE OPTIMIZATIONS

### 6.1 API Dockerfile (Multi-stage)

**File:** `backend/Dockerfile`

```dockerfile
# Stage 1: Builder
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY pyproject.toml poetry.lock* ./

# Install dependencies
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.in-project true && \
    poetry install --no-dev --no-interaction --no-ansi

# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy venv from builder
COPY --from=builder /build/.venv ./.venv

# Copy application
COPY . .

# Set environment
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run
CMD ["uvicorn", "lokilinux.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### 6.2 Frontend Dockerfile (SSR Optimized)

**File:** `frontend/Dockerfile`

```dockerfile
# Stage 1: Builder
FROM node:20-alpine as builder

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci --only=prod

COPY . .
RUN npm run build

# Stage 2: Runtime
FROM node:20-alpine

WORKDIR /app

# Install pm2
RUN npm install -g pm2

# Copy build from builder
COPY --from=builder /build/.output .

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --spider -q http://localhost:3000/ || exit 1

# Run Nuxt in production
CMD ["pm2-runtime", "start", "ecosystem.config.js"]
```

### 6.3 Agent Dockerfile (Static Binary)

**File:** `agent/Dockerfile`

```dockerfile
# Build stage
FROM golang:1.21-alpine AS builder

WORKDIR /build

# Install dependencies
RUN apk add --no-cache git

COPY go.mod go.sum ./
RUN go mod download

COPY . .

# Build static binary
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build \
    -ldflags="-w -s -X main.Version=1.0.0" \
    -o lokilinux-agent \
    ./cmd/agent

# Runtime stage (scratch for minimal size)
FROM scratch

COPY --from=builder /build/lokilinux-agent /lokilinux-agent
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/

ENTRYPOINT ["/lokilinux-agent"]
```

---

## VII. PERFORMANCE BENCHMARKS

### 7.1 Target Metrics

```
API Performance:
  - Response time (p95): <200ms
  - Throughput: >1000 req/sec
  - Memory: <500MB idle
  - CPU: <50% at 1K concurrent users

Database:
  - Query latency (p95): <100ms
  - Connection pool utilization: <80%
  - Disk I/O: <10MB/sec average

Agent:
  - Memory footprint: <50MB
  - CPU idle: <1%
  - Heartbeat latency: <100ms
  - Binary size: <15MB

Frontend:
  - First Contentful Paint: <1s
  - Time to Interactive: <2s
  - Bundle size: <150KB gzip
```

### 7.2 Load Testing Script

**File:** `scripts/load-test.sh`

```bash
#!/bin/bash

# Load test API with k6
k6 run --vus 100 --duration 5m load-test.js

# Results should show:
# - Requests: 500,000+ (at 1K RPS)
# - Error rate: <0.1%
# - Response time p95: <200ms
```

---

## VIII. QUICK START (Optimized)

```bash
# 1. Build all images
docker-compose build

# 2. Start services
docker-compose up -d

# 3. Verify (should be <5s total startup)
docker-compose ps

# 4. Check memory usage
docker stats --no-stream
# Should show:
# - API: ~300-400MB
# - Frontend: ~150MB
# - PostgreSQL: ~200-300MB
# - Redis: ~100MB
# Total: ~1-1.5GB

# 5. Generate agent binary (builds in <1min)
make -C agent build-release
# Output: agent/dist/lokilinux-agent-linux-amd64 (~15MB)
```

---

## IX. OPTIMIZATION SUMMARY

| Component | Size | Memory | CPU | Speed |
|---|---|---|---|---|
| **API** | ~200MB Docker | 300-400MB | 2-4 cores | <100ms responses |
| **Frontend** | ~150MB Docker | 150-200MB | 1 core | <1s FCP |
| **Agent** | ~15MB binary | <50MB | <1% idle | <100ms heartbeat |
| **Database** | N/A (separate) | 200-300MB | 2-4 cores | <100ms queries |
| **Redis** | N/A (separate) | 100-512MB | 1 core | <1ms cache ops |

**Total minimal stack:** ~1.5GB memory, ~1 CPU core (scales horizontally)

---

Complet! Stack-ul este maxim optimizat pentru **performance**, **minimal resource usage**, și **fast deployment**. Vrei să aprofundez vreun domeniu?
