# LokiLinux — LSP sidecar for the Go modules (agent/ and services/compliance/)
# Idle container: opencode talks to gopls via `docker exec -i`.
# The repo is bind-mounted at the SAME absolute path as on the host.
# golang:1.25 serves both modules (agent go 1.24.13, compliance go 1.25.0).

FROM golang:1.25-alpine

ENV GOTOOLCHAIN=auto
RUN go install golang.org/x/tools/gopls@latest

# Shared module cache lives in the image/volume, not the repo bind mount.
ENV GOMODCACHE=/go/pkg/mod \
    GOTOOLCHAIN=auto

CMD ["sleep", "infinity"]
