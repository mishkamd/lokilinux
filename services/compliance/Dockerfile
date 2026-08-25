FROM golang:1.26 AS builder

WORKDIR /build

# Stamps main.Version via -ldflags below (passed from docker-compose build args).
ARG VERSION=dev

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -ldflags "-s -w -X main.Version=${VERSION}" \
    -o /build/bin/lokilinux-compliance ./cmd/compliance

FROM gcr.io/distroless/static-debian12

COPY --from=builder /build/bin/lokilinux-compliance /lokilinux-compliance

# Distroless ships a pre-created unprivileged account (uid/gid 65532);
# without this the container would run as root.
USER nonroot:nonroot

ENTRYPOINT ["/lokilinux-compliance"]
