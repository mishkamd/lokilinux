# Docker Optimization Report — LokiLinux

Dimensiuni imaginini (local): api **535MB**, frontend **277MB**, compliance **35MB**.

- Frontend: `.output` 33MB, `node_modules` 567MB (dockerignored OK).
- api: `uvicorn --workers 2`, mem limit **2G**, pids 256; metrics 9090 publicat, gRPC metrics 9091 nu.
- fe: mem **512M**, cpus 0.5, pids 128; healthcheck OK.
- DB tier limits: postgres 4G/2cpu, clickhouse 2G/2cpu, redis 2G, nats 1G, rustfs 2G, pgbouncer 256M.

Logging: structlog JSON→stdout, `PYTHONUNBUFFERED=1`; prod CMD uvicorn access log **ON**
(doar `__main__` îl dezactivează); fără driver/max-size config → json-file default.

## Recomandări

1. Bump base backend pentru a elimina 44 HIGH Trivy.
2. `RUSTFS_CONSOLE_ENABLE=true` → false în prod.
3. Prod: disable/configure uvicorn access logs.

---

Optimizări measure/confirmate în acest audit: doar constatări (read-only phase).
