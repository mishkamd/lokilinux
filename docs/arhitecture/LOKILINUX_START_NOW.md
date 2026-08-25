# LokiLinux — Pași de Pornire 🚀

## STEP 1: Creează Directoarele (2 minute)

```bash
mkdir -p ~/lokilinux
cd ~/lokilinux

# Creează structura de bază
mkdir -p backend frontend agent docker docs

# Inițializează git
git init
echo "*.pyc
*.pyo
node_modules/
.env
.env.local
__pycache__/
.venv/
dist/
build/" > .gitignore

git add .gitignore
git commit -m "Initial commit: project structure"
```

---

## STEP 2: Deschide Claude Code

```bash
cd ~/lokilinux
claude code
```

**Claude Code window se va deschide → Ready to code!**

---

## STEP 3: Copy-Paste First Prompt

**In Claude Code terminal, copy-paste EXACT:**

```
Generate the complete FastAPI backend foundation for LokiLinux:

GENERATE THESE FILES:
1. backend/lokilinux/main.py - FastAPI app with lifespan management
2. backend/lokilinux/config.py - Settings from .env
3. backend/lokilinux/db.py - PostgreSQL async database
4. backend/lokilinux/cache.py - Redis caching layer
5. backend/pyproject.toml - Minimal dependencies
6. backend/.env.example - Configuration template

REQUIREMENTS:
- FastAPI 0.104.1
- SQLAlchemy 2.0 async
- asyncpg for PostgreSQL
- redis async
- uvicorn with uvloop
- All async/await (no sync I/O)
- Health checks: /health and /ready endpoints
- Structured logging with structlog
- Connection pooling: size=20, overflow=10
- gRPC gateway skeleton on port 50051
- Type hints everywhere
- Comprehensive docstrings
- Error handling middleware

AFTER GENERATION:
1. Show me all generated files
2. Show how to run locally: uvicorn lokilinux.main:app --reload
```

**Claude generates** → 6 files created ✅

---

## STEP 4: Test Backend

```bash
cd backend
pip install -e .
export PYTHONPATH=$(pwd)
uvicorn lokilinux.main:app --reload
```

**Visit:** http://localhost:8000/docs → API Docs ✅

---

## STEP 5: Second Prompt - Database

**Back in Claude Code terminal:**

```
Generate Alembic database migrations for LokiLinux:

CREATE TWO MIGRATION FILES:

1. backend/alembic/versions/001_initial.py
   Tables: agents, packages, repositories, jobs, job_results, cves, agent_vulnerabilities, users, audit_logs
   
2. backend/alembic/versions/002_update_management.py
   Tables: update_policies, update_jobs, update_job_results

REQUIREMENTS:
- PostgreSQL dialect
- UUID primary keys
- Indexes on: agent_id, status, scope, job_type, cve_id
- Foreign keys with CASCADE delete
- JSONB fields for metadata
- Both upgrade() and downgrade() functions

Test with: cd backend && alembic upgrade head
```

**Claude generates** → 2 migration files ✅

---

## STEP 6: Run Migrations

```bash
cd backend
# Make sure PostgreSQL is running
# Create database: createdb lokilinux
alembic upgrade head
```

**Database ready** with 15 tables ✅

---

## STEP 7: Third Prompt - Agent

**In Claude Code:**

```
Generate the Go agent foundation for LokiLinux:

GENERATE:
1. agent/go.mod
2. agent/cmd/agent/main.go
3. agent/internal/config/config.go

REQUIREMENTS:
- Go 1.21+
- Static binary (CGO_ENABLED=0)
- Load config from /etc/lokilinux/agent.env
- Graceful shutdown (SIGINT/SIGTERM)
- Structured logging with slog
- mTLS certificate handling

After: Build with CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o lokilinux-agent ./cmd/agent
```

**Claude generates** → Go foundation ready ✅

---

## STEP 8: Build Agent

```bash
cd agent
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o lokilinux-agent ./cmd/agent
ls -lh lokilinux-agent
# Should be ~15MB ✅
```

---

## STEP 9: Fourth Prompt - gRPC Client

**In Claude Code:**

```
Generate the gRPC client for the agent:

GENERATE:
1. agent/internal/communication/grpc_client.go
2. agent/internal/agent/heartbeat.go
3. agent/internal/agent/manager.go

REQUIREMENTS:
- mTLS mutual authentication
- Bidirectional streaming heartbeat
- Keep-alive (10s interval)
- Exponential backoff (1s to 5min)
- Collect system info (CPU, memory, packages)
- Send heartbeat every 60 seconds
- Error handling & logging

Test: go build ./...
```

**Claude generates** → gRPC client ready ✅

---

## STEP 10: Fifth Prompt - Frontend

**In Claude Code:**

```
Generate Nuxt 4 frontend for LokiLinux:

GENERATE:
1. frontend/nuxt.config.ts
2. frontend/package.json
3. frontend/pages/servers/index.vue - Server list
4. frontend/pages/servers/[id].vue - Server detail
5. frontend/pages/updates/index.vue - Update management
6. frontend/stores/servers.ts - Pinia store
7. frontend/composables/useServers.ts
8. frontend/assets/css/global.css - OKLCH colors

REQUIREMENTS:
- Vue 3 composition API
- TypeScript
- Tailwind CSS
- Pinia
- Responsive design
- Dark mode support

After: npm install && npm run dev
```

**Claude generates** → Frontend ready ✅

---

## STEP 11: Run Frontend

```bash
cd frontend
npm install
npm run dev
```

**Visit:** http://localhost:3000 ✅

---

## STEP 12: Sixth Prompt - Server APIs

**In Claude Code:**

```
Generate server inventory API endpoints:

GENERATE:
1. backend/lokilinux/api/v1/routers/servers.py
2. backend/lokilinux/schemas/server.py

ENDPOINTS:
1. GET /api/v1/servers - List all servers
   - Filters: status, scope, os
   - Cache: 5 minutes
   - Pagination: limit, offset

2. GET /api/v1/servers/{agent_id} - Server detail
   - System info, repositories, packages, updates, CVE count
   - Cache: 5 minutes

3. GET /api/v1/servers/{agent_id}/updates - Available updates
   - Filter: security_only
   - Return package list with versions

REQUIREMENTS:
- SQLAlchemy 2.0 async
- Pydantic schemas
- Redis caching
- Proper error handling
- Type hints & docstrings

Test: curl http://localhost:8000/api/v1/servers
```

**Claude generates** → APIs ready ✅

---

## STEP 13: Seventh Prompt - Update Management

**In Claude Code:**

```
Generate update management service and APIs:

GENERATE:
1. backend/lokilinux/services/update_service.py
2. backend/lokilinux/api/v1/routers/updates.py

SERVICE METHODS:
- create_update_job(scope, servers, packages, strategy, policy)
- get_update_status(job_id)
- execute_staged_waves()
- rollback_update(job_id)

STRATEGIES:
- IMMEDIATE: all servers at once
- STAGED: 25% → 50% → 75% → 100% (with hours between)
- CANARY: 5% → 25% → 100% (with health checks)

ENDPOINTS:
1. GET /api/v1/updates/policies/{scope}
2. POST /api/v1/updates/execute/{scope}?dry_run=true
3. GET /api/v1/updates/jobs/{job_id}
4. POST /api/v1/updates/jobs/{job_id}/rollback

REQUIREMENTS:
- Async operations
- Error handling
- Audit logging
- Wave execution
- Transaction handling

Test: curl -X POST http://localhost:8000/api/v1/updates/execute/prod?dry_run=true
```

**Claude generates** → Update system ready ✅

---

## FINAL: Commit Everything

```bash
cd ~/lokilinux

git add -A
git commit -m "feat: Complete LokiLinux MVP
- Backend: FastAPI + PostgreSQL + Redis
- Agent: Go gRPC client with heartbeat
- Frontend: Nuxt 4 web UI for infrastructure operations
- APIs: Server inventory + update management
- Database: 15 tables with migrations
- Testing: All components generated and tested"

git log --oneline
```

---

## ✅ CHECKLIST - END OF DAY

```
✅ Backend: FastAPI running on localhost:8000
✅ Frontend: Nuxt running on localhost:3000
✅ Database: PostgreSQL with 15 tables
✅ Agent: Go binary built (~15MB)
✅ APIs: /api/v1/servers working
✅ Update system: /api/v1/updates endpoints ready
✅ Code: All committed to git
✅ Documentation: Generated with docstrings

Total time: 3-5 hours
Lines of code generated: 2000+
Files created: 25+
Everything compiling & running: YES ✅
```

---

## 🎯 NEXT: WHAT TO BUILD TOMORROW

```
Prompt 8: CVE Database Integration
Prompt 9: Plugin Manager Service
Prompt 10: Authentication & RBAC
Prompt 11: Audit Logging
Prompt 12: Docker Setup & Kubernetes
```

---

**That's it! 🚀 Start with Step 1 now!**

All prompts are optimized for maximum code generation with minimum back-and-forth.

Good luck! 💪
