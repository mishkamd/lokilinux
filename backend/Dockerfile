# ============================================================================
# BUILD STAGE — compilers + headers, never shipped
# ============================================================================
FROM python:3.11.15-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Isolated venv so only runtime deps are copied to the final image
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    fastapi==0.138.1 uvicorn[standard]==0.49.0 \
    sqlalchemy[asyncio]==2.0.51 psycopg[async,binary]==3.3.4 alembic==1.18.5 \
    redis[hiredis]==8.0.1 nats-py==2.15.0 \
    grpcio==1.81.1 protobuf==6.33.5 \
    pydantic==2.13.4 pydantic-settings==2.14.2 \
    structlog==26.1.0 orjson==3.11.9 httpx==0.28.1 python-multipart==0.0.32 \
    PyJWT[cryptography]==2.13.0 cryptography==50.0.0 \
    openpyxl==3.1.5 reportlab==5.0.0 \
    croniter==6.2.4 && \
    # Transitive-dep security fixes, forced AFTER main install so the
    # resolver cannot downgrade them back:
    # setuptools CVE-2025-47273, wheel CVE-2026-24049, jaraco.context
    # CVE-2026-23949, msgpack GHSA-6v7p-g79w-8964
    pip install --no-cache-dir --upgrade --force-reinstall --no-deps \
    setuptools==78.1.1 wheel==0.46.2 jaraco.context==6.1.0 msgpack==1.2.1 && \
    # Build tooling is not needed at runtime; dropping pip+setuptools also
    # removes the vendored (vulnerable) copies they ship in _vendor.
    # msgpack/jaraco.context/wheel themselves remain as real packages.
    pip uninstall -y pip setuptools || true && \
    rm -rf /opt/venv/lib/python3.11/site-packages/setuptools* \
           /opt/venv/lib/python3.11/site-packages/pkg_resources* \
           /opt/venv/lib/python3.11/site-packages/_distutils_hack \
           /opt/venv/bin/pip*

# ============================================================================
# RUNTIME STAGE — minimal, non-root
# ============================================================================
FROM python:3.11.15-slim

WORKDIR /app

# Dedicated unprivileged user/group (no login shell, no home needed).
# apt upgrade patches util-linux CVEs; system site-packages (pip/setuptools
# with their vulnerable vendored deps) are unused at runtime — the app runs
# exclusively from /opt/venv — so they are removed entirely.
RUN groupadd --gid 10001 appuser && \
    useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin appuser && \
    apt-get update && \
    apt-get install -y --no-install-recommends --only-upgrade \
      util-linux bsdutils mount login \
      libblkid1 libmount1 libsmartcols1 libuuid1 liblastlog2-2 && \
    rm -rf /var/lib/apt/lists/* && \
    rm -rf /usr/local/lib/python3.11/site-packages/* /usr/local/bin/pip*

# venv with all runtime dependencies (psycopg[binary] bundles its own libpq,
# grpcio ships prebuilt extensions — no OS-level libs required)
COPY --from=builder /opt/venv /opt/venv

COPY --chown=appuser:appuser alembic/ ./alembic/
COPY --chown=appuser:appuser alembic.ini ./
COPY --chown=appuser:appuser lokilinux/ ./lokilinux/

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

USER appuser

EXPOSE 8000

# curl removed from image — stdlib healthcheck instead
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)"]

CMD ["uvicorn", "lokilinux.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
