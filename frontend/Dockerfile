FROM node:22.23.1-alpine AS builder

WORKDIR /build

# npm ci = reproducible installs strictly from package-lock.json
COPY package.json package-lock.json ./
RUN npm ci --legacy-peer-deps

COPY . .

ARG NUXT_PUBLIC_API_BASE=http://lokilinux-api:8000
ENV NUXT_PUBLIC_API_BASE=${NUXT_PUBLIC_API_BASE}

RUN npm run build

FROM node:22.23.1-alpine

WORKDIR /app

# The runtime runs `node server/index.mjs` only. npm ships inside the base image
# with bundled copies of pacote and brace-expansion that carry advisories, so it
# is removed here, as the backend image removes pip. libcrypto3/libssl3 get the
# Alpine fix (3.5.8) from the base's repositories.
RUN apk upgrade --no-cache libcrypto3 libssl3 && \
    rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx

RUN addgroup -g 1001 -S nuxt && adduser -u 1001 -S nuxt -G nuxt

COPY --from=builder --chown=nuxt:nuxt /build/.output ./

USER nuxt

ENV NODE_ENV=production \
    PORT=3000 \
    HOST=0.0.0.0

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD wget --spider -q http://localhost:3000/ || exit 1

CMD ["node", "server/index.mjs"]
