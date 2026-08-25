package main

import (
	"context"
	"flag"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/lokilinux/agent/internal/agent"
	"github.com/lokilinux/agent/internal/config"
	"github.com/lokilinux/agent/internal/logredact"
)

// Version is injected at build time via -ldflags "-X main.Version=...".
var Version = "dev"

func main() {
	configPath := flag.String("config", "/etc/lokilinux/agent.yaml", "path to agent config file")
	showVersion := flag.Bool("version", false, "print agent version and exit")
	flag.Parse()

	if *showVersion {
		os.Stdout.WriteString(Version + "\n")
		return
	}

	cfg, err := config.Load(*configPath)
	if err != nil {
		slog.Error("failed to load config", "path", *configPath, "error", err)
		os.Exit(1)
	}

	log, logBuf := newLogger(cfg.Logging.Level)

	mgr, err := agent.NewManager(cfg, log, Version, logBuf)
	if err != nil {
		log.Error("failed to initialise agent manager", "error", err)
		os.Exit(1)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	log.Info("LokiLinux agent starting",
		"agent_id", cfg.Identity.AgentID,
		"grpc_endpoint", cfg.Platform.GRPCEndpoint,
		"heartbeat_sec", cfg.Heartbeat.IntervalSec,
		"version", Version,
	)

	go mgr.Run(ctx)

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGTERM, syscall.SIGINT)
	<-sig

	log.Info("shutdown signal received")
	cancel()
	mgr.Stop()
}

// newLogger builds a structured JSON logger directed at stderr, wrapped in a
// ring buffer so the last N lines can be attached to outgoing heartbeats.
// The JSON handler is wrapped with secret redaction (plan §34): any
// attribute whose key looks credential-bearing is emitted as [REDACTED].
func newLogger(level string) (*slog.Logger, *agent.LogRingBuffer) {
	lvl := slog.LevelInfo
	switch level {
	case "debug":
		lvl = slog.LevelDebug
	case "warn":
		lvl = slog.LevelWarn
	case "error":
		lvl = slog.LevelError
	}
	buf := agent.NewLogRingBuffer(
		logredact.NewHandler(slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{Level: lvl})),
		100,
	)
	return slog.New(buf), buf
}
