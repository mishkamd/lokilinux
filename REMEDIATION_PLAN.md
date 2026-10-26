# Remediation Plan — Docker Audit (LokiLinux)

Priorități (după severitate):

1. **P1 — fix(docker)**: bump backend base image (python:3.11.15-slim → 3.11.x) — curăță 44 HIGH Trivy (util-linux/ncurses/perl-base).
2. **P2 — chore(docker)**: `RUSTFS_CONSOLE_ENABLE=false` în prod.
3. **P3 — perf(docker)**: disable/configure uvicorn access logs (prod).
4. **P4 — chore(docker)**: audit dev compose port exposures (5432/6432/4222/8222/6222/6379/9000/9001).
5. **P5 — security(docker)**: re-run Trivy post-bump (follow-up `perl-base fix_deferred`).

Riscuri / validare: build + Trivy scan + test suite după fiecare remediat.

---

Audit read-only · fără modificări aplicație în această fază.
