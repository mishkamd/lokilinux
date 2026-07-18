// Package agent contains the main agent orchestration loop.
package agent

import (
	"context"
	"log/slog"
	"sync"
	"time"

	"github.com/lokilinux/agent/internal/communication"
	"github.com/lokilinux/agent/internal/config"
	"github.com/lokilinux/agent/internal/modules"
	"github.com/lokilinux/agent/internal/storage"
)

// Manager orchestrates all agent subsystems and drives the heartbeat cycle.
type Manager struct {
	cfg     *config.Config
	log     *slog.Logger
	version string
	logBuf  *LogRingBuffer
	client  *communication.GRPCClient
	store   *storage.Store
	sysMod      *modules.SystemInfoModule
	pkgMod      *modules.PackageManagerModule
	jobExec     *modules.JobExecutor
	ansibleExec *modules.AnsibleExecutor
	stop        chan struct{}

	failCount int // consecutive heartbeat failures, drives backoff

	// resultsMu guards pendingResults: job results are produced by
	// handleResponse (in the heartbeat goroutine, same one that reads it —
	// but the mutex keeps this safe if job execution ever moves off the
	// main loop) and drained into the next outgoing heartbeat.
	resultsMu      sync.Mutex
	pendingResults []modules.JobResult
}

const (
	maxHeartbeatBackoff = 5 * time.Minute
	// reconnectAfterFailures forces a fresh gRPC dial once the connection has
	// failed this many times in a row — grpc-go's internal reconnect doesn't
	// reliably recover a transport that's been returning EOF (e.g. after the
	// server restarts), so retrying the same dead ClientConn forever just
	// wedges the agent. Threshold matches nextDelay's backoff-start point.
	reconnectAfterFailures = 3
)

// NewManager wires up all subsystems. Returns an error if storage is unavailable.
func NewManager(cfg *config.Config, log *slog.Logger, version string, logBuf *LogRingBuffer) (*Manager, error) {
	store, err := storage.Open(cfg.Cache.SQLiteDB)
	if err != nil {
		return nil, err
	}

	client := communication.NewGRPCClient(
		cfg.Platform.GRPCEndpoint,
		cfg.Identity.CertPath,
		cfg.Identity.KeyPath,
		cfg.Identity.CAPath,
	)

	return &Manager{
		cfg:     cfg,
		log:     log,
		version: version,
		logBuf:  logBuf,
		client:  client,
		store:   store,
		sysMod:      modules.NewSystemInfoModule(),
		pkgMod:      modules.NewPackageManagerModule(),
		jobExec:     modules.NewJobExecutor(),
		ansibleExec: modules.NewAnsibleExecutor(),
		stop:        make(chan struct{}),
	}, nil
}

// Run starts the heartbeat loop. Blocks until ctx is cancelled or Stop() is called.
// On consecutive failures it backs off exponentially (capped at 5m) so a degraded
// control plane isn't hammered every interval.
func (m *Manager) Run(ctx context.Context) {
	interval := time.Duration(m.cfg.Heartbeat.IntervalSec) * time.Second

	go m.runPurge(ctx)

	// fire immediately on start, then on each computed delay
	m.sendHeartbeat(ctx)

	timer := time.NewTimer(m.nextDelay(interval))
	defer timer.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-m.stop:
			return
		case <-timer.C:
			m.sendHeartbeat(ctx)
			timer.Reset(m.nextDelay(interval))
		}
	}
}

// nextDelay returns the base interval normally, or an exponential backoff after
// 3+ consecutive failures (interval, 2x, 4x ... capped at maxHeartbeatBackoff).
func (m *Manager) nextDelay(interval time.Duration) time.Duration {
	if m.failCount < 3 {
		return interval
	}
	delay := interval << uint(m.failCount-3) // 1x, 2x, 4x...
	if delay > maxHeartbeatBackoff || delay <= 0 {
		return maxHeartbeatBackoff
	}
	return delay
}

// runPurge removes expired SQLite job records once per day.
func (m *Manager) runPurge(ctx context.Context) {
	t := time.NewTicker(24 * time.Hour)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-m.stop:
			return
		case <-t.C:
			if err := m.store.PurgeExpiredJobs(ctx); err != nil {
				m.log.Warn("db purge failed", "error", err)
			}
		}
	}
}

// Stop signals the Run loop to exit cleanly.
func (m *Manager) Stop() {
	select {
	case <-m.stop:
	default:
		close(m.stop)
	}
	m.client.Close() //nolint:errcheck
	m.store.Close()  //nolint:errcheck
}

// sendHeartbeat collects current state and ships it to the control plane.
func (m *Manager) sendHeartbeat(ctx context.Context) {
	sysInfo, err := m.sysMod.Collect()
	if err != nil {
		m.log.Error("system info collection failed", "error", err)
		return
	}

	pkgs, checksum, err := m.pkgMod.ListPackages()
	if err != nil {
		// non-fatal — log and continue with empty list
		m.log.Warn("package list failed", "error", err)
	}

	var recentLogs []string
	var connCount, infoCount, critCount int
	if m.logBuf != nil {
		recentLogs = m.logBuf.Lines()
		connCount, infoCount, critCount = m.logBuf.Counts()
	}
	health := m.sysMod.CollectHealth(sysInfo)

	m.resultsMu.Lock()
	results := append([]modules.JobResult(nil), m.pendingResults...)
	m.resultsMu.Unlock()

	payload := buildPayload(m.cfg.Identity.AgentID, sysInfo, pkgs, checksum, m.version, recentLogs, connCount, infoCount, critCount, health, results)

	resp, err := m.client.SendHeartbeat(ctx, payload)
	if err != nil {
		m.failCount++
		m.log.Error("heartbeat failed", "error", err, "consecutive_failures", m.failCount)
		if m.failCount%reconnectAfterFailures == 0 {
			if rerr := m.client.Reconnect(); rerr != nil {
				m.log.Error("reconnect failed", "error", rerr)
			} else {
				m.log.Info("reconnected", "consecutive_failures", m.failCount)
			}
		}
		return
	}
	m.failCount = 0

	if len(results) > 0 {
		m.resultsMu.Lock()
		m.pendingResults = m.pendingResults[len(results):]
		m.resultsMu.Unlock()
	}

	m.log.Info("heartbeat sent",
		"event", "connection",
		"agent_id", m.cfg.Identity.AgentID,
		"packages", len(pkgs),
		"checksum", checksum[:8],
		"job_results_reported", len(results),
	)

	if resp != nil {
		m.handleResponse(ctx, resp)
	}
}

// buildPayload assembles the heartbeat map sent to the gRPC client.
// The loose map[string]interface{} type is intentional: Val 2 (Agent G)
// converts this to typed proto messages inside GRPCClient.SendHeartbeat.
func buildPayload(
	agentID string,
	sys *modules.SystemInfo,
	pkgs []modules.Package,
	checksum string,
	version string,
	recentLogs []string,
	logConnections int,
	logInformative int,
	logCritical int,
	health modules.Health,
	jobResults []modules.JobResult,
) map[string]interface{} {
	return map[string]interface{}{
		"agent_id":          agentID,
		"timestamp":         time.Now().Unix(),
		"system":            sys,
		"packages":          pkgs,
		"packages_checksum": checksum,
		"agent_version":     version,
		"recent_logs":       recentLogs,
		"log_connections":   logConnections,
		"log_informative":   logInformative,
		"log_critical":      logCritical,
		"health":            health,
		"job_results":       jobResults,
	}
}

// handleResponse processes jobs and policy deltas from the server response.
func (m *Manager) handleResponse(ctx context.Context, resp map[string]interface{}) {
	jobs, ok := resp["pending_jobs"]
	if !ok {
		return
	}
	jobList, ok := jobs.([]interface{})
	if !ok || len(jobList) == 0 {
		return
	}
	m.log.Info("received pending jobs", "count", len(jobList))

	for _, j := range jobList {
		job, ok := j.(map[string]interface{})
		if !ok {
			continue
		}
		jobID, _ := job["job_id"].(string)
		jobType, _ := job["job_type"].(string)

		params, _ := job["parameters"].(map[string]interface{})

		timeoutSec := m.cfg.JobExecution.TimeoutSeconds // config default (3600s)
		if t, ok := job["timeout_seconds"].(float64); ok && t > 0 {
			timeoutSec = int(t)
		}

		var result modules.JobResult

		if jobType == "PLUGIN_INSTALL" {
			result = modules.InstallPlugin(ctx, jobID, params, timeoutSec)
		} else if jobType == "ANSIBLE_PLAYBOOK" {
			playbookContent, _ := params["playbook_content"].(string)
			extraVars, _ := params["extra_vars"].(map[string]interface{})
			roles, _ := params["roles"].(map[string]interface{})
			if playbookContent == "" {
				m.log.Warn("ansible job has no playbook_content, skipping", "job_id", jobID)
				continue
			}
			result = m.ansibleExec.Execute(ctx, jobID, playbookContent, extraVars, roles, timeoutSec)
		} else {
			command, _ := params["command"].(string)
			if command == "" {
				m.log.Warn("job has no command parameter, skipping", "job_id", jobID)
				continue
			}
			result = m.jobExec.Execute(ctx, jobID, command, timeoutSec)
		}

		m.log.Info("job executed",
			"job_id", jobID,
			"job_type", jobType,
			"exit_code", result.ExitCode,
			"duration_ms", result.DurationMs,
		)

		m.resultsMu.Lock()
		m.pendingResults = append(m.pendingResults, result)
		m.resultsMu.Unlock()
	}
}
