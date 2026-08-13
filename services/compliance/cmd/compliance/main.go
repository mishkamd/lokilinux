// Command compliance runs the lokilinux-compliance service: the CPU-bound
// hot path for the Infrastructure Compliance & Drift Management module
// (snapshot ingest, drift diff, rule evaluation, scoring, scheduling — see
// docs/compliance/02-GO-SERVICE.md). It has no public REST surface; it only
// exposes /healthz and /metrics, consumes NATS, and reads/writes Postgres.
//
// Skeleton stage: boots, connects to its dependencies, and serves health/
// metrics. Ingest/rules/drift/scheduler packages land in later phases
// (docs/compliance/13-OPS.md roadmap) without changing this entrypoint's shape.
package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/nats-io/nats.go"
	"github.com/nats-io/nats.go/jetstream"

	"github.com/lokilinux/compliance/internal/baseline"
	"github.com/lokilinux/compliance/internal/config"
	"github.com/lokilinux/compliance/internal/ingest"
	"github.com/lokilinux/compliance/internal/rules"
	"github.com/lokilinux/compliance/internal/scheduler"
	"github.com/lokilinux/compliance/internal/storage"
	"github.com/lokilinux/compliance/internal/telemetry"
)

// Version is injected at build time via -ldflags "-X main.Version=...".
var Version = "dev"

func main() {
	configPath := flag.String("config", "/etc/lokilinux/compliance.yaml", "path to compliance service config file")
	showVersion := flag.Bool("version", false, "print version and exit")
	healthcheck := flag.Bool("healthcheck", false, "GET /healthz on this instance and exit 0/1 — for Docker's HEALTHCHECK, since the final image is distroless (no shell, no wget/curl to run as a separate CMD)")
	healthcheckPort := flag.Int("healthcheck-port", 8080, "port to hit when -healthcheck is set")
	flag.Parse()

	if *showVersion {
		os.Stdout.WriteString(Version + "\n")
		return
	}

	if *healthcheck {
		os.Exit(runHealthcheck(*healthcheckPort))
	}

	cfg, err := config.Load(*configPath)
	if err != nil {
		slog.Error("failed to load config", "path", *configPath, "error", err)
		os.Exit(1)
	}

	log := newLogger(cfg.Logging.Level)
	log.Info("lokilinux-compliance starting", "version", Version)

	// NATS connection — required for ingest (consumer) and scheduler (KV
	// leader election); dial failure is fatal at startup, matching how the
	// existing backend workers treat their NATS dependency.
	natsURL := envOr("NATS_URL", cfg.NATS.URL)
	nc, err := nats.Connect(natsURL, nats.MaxReconnects(-1), nats.ReconnectWait(2*time.Second))
	if err != nil {
		log.Error("failed to connect to NATS", "url", natsURL, "error", err)
		os.Exit(1)
	}
	defer nc.Close()
	log.Info("connected to NATS", "url", natsURL)

	dbURL := envOr("DATABASE_URL", cfg.Database.URL)
	if dbURL == "" {
		log.Error("DATABASE_URL not set (env or config database.url)")
		os.Exit(1)
	}
	store, err := storage.Open(context.Background(), dbURL)
	if err != nil {
		log.Error("failed to connect to database", "error", err)
		os.Exit(1)
	}
	defer store.Close()
	log.Info("connected to database")

	evaluator, err := rules.NewCELEvaluator()
	if err != nil {
		log.Error("failed to build CEL environment", "error", err)
		os.Exit(1)
	}
	ingester := ingest.NewIngester(store, evaluator)

	// Lifetime context for the consume loop — cancelled on shutdown signal,
	// separate from the per-request contexts pgx/CEL use internally.
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	js, err := jetstream.New(nc)
	if err != nil {
		log.Error("failed to build JetStream context", "error", err)
		os.Exit(1)
	}
	stream, err := ingest.EnsureStream(ctx, js, cfg.NATS.StreamName)
	if err != nil {
		log.Error("failed to ensure JetStream stream", "stream", cfg.NATS.StreamName, "error", err)
		os.Exit(1)
	}
	consumer := ingest.NewConsumer(ingester, log)
	go func() {
		if err := consumer.Start(ctx, stream, cfg.NATS.ConsumerDurable, cfg.NATS.MaxAckPending); err != nil {
			log.Error("ingest consumer stopped", "error", err)
		}
	}()
	log.Info("ingest consumer started", "stream", cfg.NATS.StreamName, "durable", cfg.NATS.ConsumerDurable)

	// Baseline consumer: COMPLIANCE_BASELINE_PUBLISHED -> recompute
	// baseline_effective for every agent (fleet-wide invalidation,
	// docs/compliance/06-BASELINE.md §2). Sits on the same JetStream stream,
	// filtered to a disjoint subject from the ingest consumer's.
	baselineResolver := baseline.NewResolver(store)
	baselineConsumer := baseline.NewConsumer(baselineResolver, log)
	go func() {
		if err := baselineConsumer.Start(ctx, stream, cfg.NATS.MaxAckPending); err != nil {
			log.Error("baseline consumer stopped", "error", err)
		}
	}()
	log.Info("baseline consumer started", "stream", cfg.NATS.StreamName, "durable", "compliance-baseline")

	// Startup reconciliation: recompute baseline_effective for any agent
	// that lacks a row, guarding against restart where NATS backlog is lost.
	// Safe to call even when no baselines are published yet (no-op).
	if err := baselineResolver.ReconcileOnStartup(ctx); err != nil {
		log.Error("startup baseline reconciliation failed", "error", err)
	} else {
		log.Info("startup baseline reconciliation complete")
	}

	// Scheduler: leader election (NATS KV, TTL-based lease) + Job.scheduled_time
	// dispatch — the first consumer that column has ever had
	// (docs/compliance/02-GO-SERVICE.md §4).
	leaderTTL := time.Duration(cfg.NATS.LeaderTTLSeconds) * time.Second
	kvBucket, err := js.CreateOrUpdateKeyValue(ctx, jetstream.KeyValueConfig{
		Bucket: cfg.NATS.LeaderKVBucket,
		TTL:    leaderTTL,
	})
	if err != nil {
		log.Error("failed to create leader-election KV bucket", "bucket", cfg.NATS.LeaderKVBucket, "error", err)
		os.Exit(1)
	}
	nodeID, err := os.Hostname()
	if err != nil || nodeID == "" {
		nodeID = "unknown-" + strconv.FormatInt(time.Now().UnixNano(), 36)
	}
	elector := scheduler.NewLeaderElector(scheduler.NewNATSKVStore(kvBucket), nodeID)
	go elector.Run(ctx, leaderTTL/3)

	dispatcher := scheduler.NewDispatcher(elector, store, log)
	go dispatcher.Run(ctx, 10*time.Second)

	expirer := scheduler.NewExpirer(elector, store, log)
	go expirer.Run(ctx, time.Minute)
	log.Info("scheduler started", "node_id", nodeID, "leader_ttl", leaderTTL)

	// Registers this service's counters on the default Prometheus registry
	// immediately (visible at 0 on /metrics right away); the returned struct
	// is threaded into ingest/drift/scoring packages as they land.
	telemetry.New()

	healthApp := fiber.New(fiber.Config{DisableStartupMessage: true})
	healthApp.Get("/healthz", func(c *fiber.Ctx) error {
		if nc.Status() != nats.CONNECTED {
			return c.Status(fiber.StatusServiceUnavailable).JSON(fiber.Map{"status": "degraded", "nats": nc.Status().String()})
		}
		return c.JSON(fiber.Map{"status": "ok"})
	})

	metricsServer := &http.Server{
		Addr:    fmtAddr(cfg.Telemetry.MetricsPort),
		Handler: telemetry.Handler(),
	}

	go func() {
		if err := healthApp.Listen(fmtAddr(cfg.Telemetry.HealthPort)); err != nil {
			log.Error("healthz server stopped", "error", err)
		}
	}()
	go func() {
		if err := metricsServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Error("metrics server stopped", "error", err)
		}
	}()

	log.Info("serving",
		"healthz_port", cfg.Telemetry.HealthPort,
		"metrics_port", cfg.Telemetry.MetricsPort,
	)

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGTERM, syscall.SIGINT)
	<-sig

	log.Info("shutdown signal received")
	cancel() // stops the ingest consume loop

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()
	_ = healthApp.ShutdownWithContext(shutdownCtx)
	_ = metricsServer.Shutdown(shutdownCtx)
}

func newLogger(level string) *slog.Logger {
	lvl := slog.LevelInfo
	switch level {
	case "debug":
		lvl = slog.LevelDebug
	case "warn":
		lvl = slog.LevelWarn
	case "error":
		lvl = slog.LevelError
	}
	return slog.New(slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{Level: lvl}))
}

// runHealthcheck GETs /healthz on the given port and returns a process exit
// code (0 healthy, 1 otherwise) — invoked as `lokilinux-compliance
// -healthcheck` from Docker's HEALTHCHECK CMD, the only way to probe an
// HTTP endpoint from inside a distroless container that has no wget/curl.
func runHealthcheck(port int) int {
	client := http.Client{Timeout: 3 * time.Second}
	resp, err := client.Get(fmt.Sprintf("http://127.0.0.1:%d/healthz", port))
	if err != nil {
		return 1
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return 1
	}
	return 0
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func fmtAddr(port int) string {
	return ":" + strconv.Itoa(port)
}
