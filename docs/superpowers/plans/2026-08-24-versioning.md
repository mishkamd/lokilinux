# Versioning Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Două linii de versiune cu sursă unică de adevăr fiecare, zero hardcodări drift-uite, imagini docker etichetate real, și un skill care face bump automat (cu confirmare) la deploy/release.

**Architecture:** Track **platformă** (`vX.Y.Z`: root `VERSION` → pyproject + `__init__.py` + package.json + `.env LOKILINUX_VERSION` + tag `vX.Y.Z`) și track **agent** (`A.B.C`: `agent/VERSION` → ldflags + nfpm; valoarea live rămâne în DB `settings.agent.version`, gestionată de `release.sh` existent). Guard `scripts/check-versions.sh` oprește drift-ul. Skill nou `bump-version` orchestrează ambele track-uri, reutilizând `detect-changed-services.sh`.

**Tech Stack:** bash (set -euo pipefail), Make, docker compose, git tags (platformă cu prefix `v`, agent fără).

**Decizii confirmate:** două linii separate · agent SSOT inițial `0.35.3` · tip bump întrebat cu sugestie · CHANGELOG.md generat.

---

## Task 1: Aliniere versiuni platformă la 0.3.0 + constant unic runtime

- [x] `backend/lokilinux/__init__.py` → `__version__ = "0.3.0"`
- [x] `main.py`: import `from lokilinux import __version__`; line 49 startup log folosește `version=__version__`; FastAPI `version=__version__`
- Verify: `grep -rn '"0\.1\.0"' backend/lokilinux/main.py backend/lokilinux/__init__.py` → 0 matches
- Commit: `Align platform version to 0.3.0, derive runtime version from package`

## Task 2: Fișiere SSOT

- [x] `VERSION` = `0.3.0`, `agent/VERSION` = `0.35.3`
- Verify: ne-ignorate de git; Commit: `Add VERSION files as single source of truth (platform + agent)`

## Task 3: Makefile — elimină `git describe`

- [x] Linia 10 → `PLATFORM_VERSION ?= $(shell cat VERSION ...)` + `AGENT_VER ?= $(shell cat agent/VERSION ...)`
- [x] Target-uri agent folosesc `$(AGENT_VER)`; compliance-build folosește `$(PLATFORM_VERSION)`
- Verify: `make -n agent-build` → `main.Version=0.35.3`; `make -n compliance-build` → `main.Version=0.3.0`

## Task 4: Compose build arg compliance

- [x] `lokilinux-compliance.build.args: VERSION=${LOKILINUX_VERSION:-dev}`
- Verify: `docker compose config`

## Task 5: scripts/check-versions.sh — guard anti-drift

- [x] Compară VERSION vs pyproject / __init__.py / package.json; exit 1 pe drift

## Task 6: scripts/release-platform.sh <patch|minor|major> [--dry-run]

- [x] Bump VERSION + pyproject + __init__.py + package.json + .env LOKILINUX_VERSION + CHANGELOG.md, commit + tag v$NEW

## Task 7: Extensie release.sh (agent) + docs

- [x] release.sh scrie `agent/VERSION` în pasul cosmetic defaults
- [x] backend/README.md aliniat la realitate

## Task 8: Skill .claude/skills/bump-version/SKILL.md

- [x] Orchestrator dual-track: detect → sugerează + întreabă bump → dry-run → confirm → execute → report

## Task 9: Testare skill RED/GREEN cu subagenți

- [x] Baseline fără skill (documentat), apoi cu skill, refactor găuri

## Task 10: Verificare finală end-to-end

- [x] check-versions OK · make -n corect · compose config valid · dry-run nu murdărește tree · go test agent+compliance verde

## Known issues rămase (decizie ulterioară)

1. `MIN_AGENT_VERSION_NATIVE_MODULES = 0.36.0` > versiune servită `0.35.3` → module native blocate implicit. Fix recomandat: release oficial agent 0.36.0.
2. Imagini infra pin-ute — nu se ating.
3. Convenție tag: agent fără `v`, platformă cu `v`.
