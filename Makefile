.PHONY: up down build dev proto agent-build agent-build-arm64 agent-package agent-test compliance-build compliance-test certs init logs ps help

COMPOSE        = docker compose
COMPOSE_DEV    = $(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml
PROTO_DIR      = proto
AGENT_DIR      = agent
AGENT_BIN      = $(AGENT_DIR)/bin/lokilinux-agent
PROTO_GEN_GO   = $(AGENT_DIR)/gen
PROTO_GEN_PY   = backend/lokilinux/gen
# Version sources of truth: root VERSION = platform, agent/VERSION = agent.
# Never derive from `git describe` here — the repo carries two interleaved tag
# namespaces (platform vX.Y.Z, agent X.Y.Z), so describe picks whichever is
# newest and would stamp platform versions into agent artifacts (and vice versa).
PLATFORM_VERSION ?= $(shell cat VERSION 2>/dev/null || echo "0.0.0")
AGENT_VER        ?= $(shell cat agent/VERSION 2>/dev/null || echo "0.0.0")

# ── Stack ─────────────────────────────────────────────────────────────────────

## Start production stack (detached)
up:
	$(COMPOSE) up -d

## Stop all containers
down:
	$(COMPOSE) down

## Build all images
build:
	$(COMPOSE) build

## Start dev stack (hot-reload, local ports exposed, no resource limits)
dev:
	$(COMPOSE_DEV) up -d

## Tail logs for all services (ctrl-c to stop)
logs:
	$(COMPOSE) logs -f

## Show container status
ps:
	$(COMPOSE) ps

# ── Protobuf ──────────────────────────────────────────────────────────────────

## Regenerate Go + Python code from proto/lokilinux.proto
proto:
	@which protoc >/dev/null 2>&1 || { echo "ERROR: protoc not found. Install protobuf-compiler (apt install protobuf-compiler / brew install protobuf)."; exit 1; }
	mkdir -p $(PROTO_GEN_GO) $(PROTO_GEN_PY)
	protoc \
		--go_out=$(PROTO_GEN_GO) \
		--go_opt=paths=source_relative \
		--go-grpc_out=$(PROTO_GEN_GO) \
		--go-grpc_opt=paths=source_relative \
		$(PROTO_DIR)/lokilinux.proto
	protoc \
		--python_out=$(PROTO_GEN_PY) \
		--grpc_python_out=$(PROTO_GEN_PY) \
		$(PROTO_DIR)/lokilinux.proto

# ── Agent ─────────────────────────────────────────────────────────────────────

## Build static agent binary for linux/amd64
agent-build:
	CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
		go build -ldflags "-s -w -X main.Version=$(AGENT_VER)" -o $(AGENT_BIN) ./$(AGENT_DIR)/cmd/agent

## Build agent for linux/arm64
agent-build-arm64:
	CGO_ENABLED=0 GOOS=linux GOARCH=arm64 \
		go build -ldflags "-s -w -X main.Version=$(AGENT_VER)" -o $(AGENT_BIN)-arm64 ./$(AGENT_DIR)/cmd/agent

## Build agent for both architectures and create distributable packages
agent-package: agent-build agent-build-arm64
	mkdir -p $(AGENT_DIR)/bin
	cp scripts/loki-cli.sh $(AGENT_DIR)/bin/loki
	chmod +x $(AGENT_DIR)/bin/loki
	tar -czf $(AGENT_DIR)/bin/lokilinux-agent_$(AGENT_VER)_linux_amd64.tar.gz \
		-C $(AGENT_DIR)/bin lokilinux-agent loki
	tar -czf $(AGENT_DIR)/bin/lokilinux-agent_$(AGENT_VER)_linux_arm64.tar.gz \
		-C $(AGENT_DIR)/bin lokilinux-agent-arm64 loki
	@# Ed25519 artifact signatures (plan P9): sign "sha256:<hex>" of each
	@# tarball when the platform signing key is available on the build host.
	@# Missing key = skip with a loud warning; installers verify only when a
	@# .sig is served, so unsigned artifacts stay installable but flagged.
	@if [ -n "$${JOB_SIGNING_KEY_PATH:-}" ] && [ -f "$${JOB_SIGNING_KEY_PATH}" ]; then \
	  for f in $(AGENT_DIR)/bin/lokilinux-agent_$(AGENT_VER)_linux_*.tar.gz; do \
	    openssl pkeyutl -sign -inkey "$${JOB_SIGNING_KEY_PATH}" -rawin \
	      -in <(printf 'sha256:%s' "$$(sha256sum "$$f" | cut -d' ' -f1)") \
	      -out "$$f.sig" || echo "WARN: signing failed for $$f"; \
	  done; \
	else \
	  echo "WARN: JOB_SIGNING_KEY_PATH not set — agent artifacts UNSIGNED"; \
	fi
	@if command -v nfpm >/dev/null 2>&1; then \
		cp $(AGENT_DIR)/bin/lokilinux-agent $(AGENT_DIR)/bin/lokilinux-agent-nfpm-src && \
		cd $(AGENT_DIR) && ARCH=amd64 VERSION=$(AGENT_VER) nfpm package -f .nfpm.yaml --packager deb --target bin/ && \
		cd $(AGENT_DIR) && ARCH=amd64 VERSION=$(AGENT_VER) nfpm package -f .nfpm.yaml --packager rpm --target bin/ && \
		cp $(AGENT_DIR)/bin/lokilinux-agent-arm64 $(AGENT_DIR)/bin/lokilinux-agent-nfpm-src && \
		cd $(AGENT_DIR) && ARCH=arm64 VERSION=$(AGENT_VER) nfpm package -f .nfpm.yaml --packager deb --target bin/ && \
		cd $(AGENT_DIR) && ARCH=arm64 VERSION=$(AGENT_VER) nfpm package -f .nfpm.yaml --packager rpm --target bin/ && \
		rm -f $(AGENT_DIR)/bin/lokilinux-agent-nfpm-src; \
	else \
		echo "nfpm not installed — skipping .deb/.rpm (install: go install github.com/goreleaser/nfpm/v2/cmd/nfpm@v2.40.0)"; \
	fi

## Run agent tests with race detector
agent-test:
	cd $(AGENT_DIR) && go test ./... -v -race -cover

# ── Compliance service ─────────────────────────────────────────────────────────

COMPLIANCE_DIR = services/compliance
COMPLIANCE_BIN = $(COMPLIANCE_DIR)/bin/lokilinux-compliance

## Build the lokilinux-compliance static binary for linux/amd64
compliance-build:
	CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
		go build -ldflags "-s -w -X main.Version=$(PLATFORM_VERSION)" -o $(COMPLIANCE_BIN) ./$(COMPLIANCE_DIR)/cmd/compliance

## Run compliance service tests with race detector
compliance-test:
	cd $(COMPLIANCE_DIR) && go test ./... -v -race -cover

# ── Certificates ─────────────────────────────────────────────────────────────

## Generate CA + server certificate (runs scripts/init-certificates.sh)
certs:
	bash scripts/init-certificates.sh

## First-run initialisation: certs + volumes + migrations + admin user
init:
	bash scripts/docker-init.sh

# ── Help ──────────────────────────────────────────────────────────────────────

help:
	@grep -E '^##' Makefile | sed 's/^## //'

# ── Supply-chain security ─────────────────────────────────────────────────────

TRIVY ?= trivy

## Scan all lokilinux images; FAILS on HIGH/CRITICAL vulns (CI gate)
scan-image:
	@for img in $$(docker images --format '{{.Repository}}:{{.Tag}}' | grep '^lokilinux/'); do \
		echo "[*] Scanning $$img"; \
		$(TRIVY) image --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed $$img || exit 1; \
	done
	@echo "[+] All images passed the vulnerability gate"

## Generate CycloneDX SBOM for an image (make sbom IMAGE=lokilinux/api:0.3.0)
sbom:
ifndef IMAGE
	$(error usage: make sbom IMAGE=lokilinux/api:<tag>)
endif
	@mkdir -p sbom
	$(TRIVY) image --format cyclonedx --output sbom/$$(echo $(IMAGE) | tr '/:' '__').cdx.json $(IMAGE)
	@echo "[+] SBOM written to sbom/"
