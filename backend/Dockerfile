FROM python:3.11.15-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir pip --upgrade && \
    pip install --no-cache-dir \
    fastapi==0.138.1 uvicorn[standard]==0.49.0 \
    sqlalchemy[asyncio]==2.0.51 psycopg[async,binary]==3.3.4 alembic==1.18.5 \
    redis[hiredis]==8.0.1 nats-py==2.15.0 \
    grpcio==1.81.1 protobuf==6.33.5 \
    pydantic==2.13.4 pydantic-settings==2.14.2 \
    structlog==26.1.0 orjson==3.11.9 httpx==0.28.1 python-multipart==0.0.32 \
    PyJWT[cryptography]==2.13.0 cryptography==49.0.0 \
    openpyxl==3.1.5 reportlab==5.0.0 \
    croniter==6.2.4

FROM python:3.11.15-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY --from=builder /usr/local/bin/alembic /usr/local/bin/alembic

COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "lokilinux.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
