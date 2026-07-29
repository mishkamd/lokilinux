FROM golang:1.24-bookworm AS builder

WORKDIR /build

COPY go.mod ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -ldflags "-s -w -X main.Version=${VERSION:-dev}" \
    -o /build/bin/lokilinux-compliance ./cmd/compliance

FROM gcr.io/distroless/static-debian12

COPY --from=builder /build/bin/lokilinux-compliance /lokilinux-compliance

ENTRYPOINT ["/lokilinux-compliance"]
