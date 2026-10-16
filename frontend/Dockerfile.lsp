# LokiLinux — LSP sidecar for the frontend (TypeScript + Vue)
# Idle container: opencode talks to the servers via `docker exec -i`.
# The repo is bind-mounted at the SAME absolute path as on the host, so LSP
# rootUri / diagnostics paths resolve without any mapping.

FROM node:22.23.1-alpine

# tsserver comes from the bind-mounted frontend/node_modules.
# typescript is installed globally as fallback for when node_modules is absent.
# NOTE: .vue files are type-checked via `npx vue-tsc --noEmit`, NOT an LSP server —
# Volar's vue-language-server needs a tsserver/request bridge that generic LSP
# clients (opencode) don't implement.
RUN npm install -g typescript-language-server@4 typescript@5.9.3

WORKDIR /opt/lokilinux/frontend

CMD ["sleep", "infinity"]
