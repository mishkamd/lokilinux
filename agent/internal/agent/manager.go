// Package agent contains the main agent orchestration loop.
package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/lokilinux/agent/internal/communication"
	"github.com/lokilinux/agent/internal/compliance"
	"github.com/lokilinux/agent/internal/config"
	"github.com/lokilinux/agent/internal/modules"
	"github.com/lokilinux/agent/internal/security"
	"github.com/lokilinux/agent/internal/storage"
)

// complianceTickInterval is the base cadence compliance.Runner ticks at —
// finer-grained than any single collector needs (Collector.Interval()
// governs actual cadence per domain), just frequent enough that a 0-
// interval ("every heartbeat") collector stays fresh between heartbeats.
const complianceTickInterval = time.Minute

// Manager orchestrates all agent subsystems and drives the heartbeat cycle.
type Manager struct {
	cfg               *config.Config
	log               *slog.Logger
	version           string
	logBuf            *LogRingBuffer
	client            *communication.GRPCClient
	store             *storage.Store
	sysMod            *modules.SystemInfoModule
	pkgMod            *modules.PackageManagerModule
	jobExec           *modules.JobExecutor
	ansibleExec       *modules.AnsibleExecutor
	remediationExec   *modules.RemediationExecutor
	workflowStepsExec *modules.WorkflowStepsExecutor
	complianceRunner  *compliance.Runner
	stop              chan struct{}

	// signed-job trust model (docs/security/AGENT_SECURITY.md): verifier
	// holds ONLY the platform public key; replay backs onto seen_jobs in
	// SQLite; secCfg mirrors config.Security for the validation pipeline.
	// policy is the last-good LocalPolicy from update_policy heartbeats —
	// guarded by policyMu because handleResponse (heartbeat goroutine) and
	// job goroutines read it concurrently.
	verifier *security.Verifier
	replay   *security.ReplayStore
	secCfg   configSecurity
	policyMu sync.RWMutex
	policy   *security.LocalPolicy

	failCount int // consecutive heartbeat failures, drives backoff

	// resultsMu guards pendingResults: job results are produced by
	// handleResponse (in the heartbeat goroutine, same one that reads it —
	// but the mutex keeps this safe if job execution ever moves off the
	// main loop) and drained into the next outgoing heartbeat.
	resultsMu      sync.Mutex
	pendingResults []modules.JobResult

	// nudge wakes the heartbeat loop early when a job finishes, instead of
	// letting the result sit in pendingResults until the next scheduled
	// tick (up to a full heartbeat interval later). Buffered 1 + a
	// non-blocking send: a burst of jobs finishing together coalesces into
	// a single early heartbeat rather than queuing one per job.
	nudge chan struct{}

	// resyncMu guards resyncDomains: set by handleResponse from the
	// server's resync_domains, drained by sendHeartbeat into the *next*
	// outgoing heartbeat's domain_full (docs/compliance/04-PROTOCOL.md §3).
	resyncMu      sync.Mutex
	resyncDomains []string

	// inFlightMu guards inFlight: jobs now run in their own goroutine (a
	// long PACKAGE_UPDATE/ANSIBLE_PLAYBOOK must not block the heartbeat
	// loop, or HeartbeatMonitorWorker marks the agent INACTIVE mid-job).
	// The server already avoids re-dispatching a job once its JobResult
	// leaves PENDING, but that's one heartbeat's worth of latency away —
	// this guard is the hard local backstop so the same job_id can never
	// run twice concurrently (two overlapping package-manager runs would
	// just deadlock each other on its lock file).
	inFlightMu sync.Mutex
	inFlight   map[string]struct{}
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

	secCfg := configSecurity{
		EnforceSignedJobs: cfg.Security.EnforceSignedJobs,
		SigningPubKeyPath: cfg.Security.SigningPubKeyPath,
	}
	verifier, err := initVerifier(&secCfg)
	if err != nil {
		return nil, err
	}
	if verifier == nil {
		log.Warn("signed-job enforcement disabled: no signing public key loaded",
			"path", cfg.Security.SigningPubKeyPath)
	}

	// Restore last-good local policy across restarts (freshness is judged
	// against ReceivedAt, so a stale one still fails HIGH+ jobs fail-closed).
	mgr := &Manager{
		cfg:         cfg,
		log:         log,
		version:     version,
		logBuf:      logBuf,
		client:      client,
		store:       store,
		sysMod:      modules.NewSystemInfoModule(),
		pkgMod:      modules.NewPackageManagerModule(),
		jobExec:     modules.NewJobExecutor(),
		ansibleExec: modules.NewAnsibleExecutor(),
		remediationExec: modules.NewRemediationExecutor(
			modules.NewJobExecutor(),
			modules.NewAnsibleExecutor(),
			modules.NewPythonExecutor(),
		),
		workflowStepsExec: modules.NewWorkflowStepsExecutor(
			modules.NewAnsibleExecutor(),
			modules.NewJobExecutor(),
		),
		complianceRunner: compliance.NewRunner(
			compliance.BuildRegistry(cfg.FileIntegrity.WatchPaths, cfg.FileIntegrity.Ignores), store, log,
		),
		verifier: verifier,
		replay:   security.NewReplayStore(store),
		secCfg:   secCfg,
		stop:     make(chan struct{}),
		nudge:    make(chan struct{}, 1),
		inFlight: make(map[string]struct{}),
	}
	if blob, err := store.GetConfig(context.Background(), "security.local_policy"); err == nil && blob != "" {
		if lp, err := security.UnmarshalLocalPolicy([]byte(blob)); err == nil {
			mgr.policy = lp
			log.Info("restored local policy from state", "version", lp.Version,
				"received_at", lp.ReceivedAt.Format(time.RFC3339))
		}
	}
	return mgr, nil
}

// Run starts the heartbeat loop. Blocks until ctx is cancelled or Stop() is called.
// On consecutive failures it backs off exponentially (capped at 5m) so a degraded
// control plane isn't hammered every interval.
func (m *Manager) Run(ctx context.Context) {
	interval := time.Duration(m.cfg.Heartbeat.IntervalSec) * time.Second

	go m.runPurge(ctx)

	if err := m.complianceRunner.LoadState(ctx); err != nil {
		m.log.Warn("loading persisted compliance state failed", "error", err)
	}
	go m.complianceRunner.Run(ctx, complianceTickInterval)

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
		case <-m.nudge:
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
	vulns := m.pkgMod.Vulnerabilities(pkgs)

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

	domainHashes := m.complianceRunner.Hashes()

	m.resyncMu.Lock()
	toResync := m.resyncDomains
	m.resyncMu.Unlock()
	var domainFull map[string]map[string]interface{}
	if len(toResync) > 0 {
		domainFull = make(map[string]map[string]interface{}, len(toResync))
		for _, domain := range toResync {
			if result, ok := m.complianceRunner.FullBody(domain); ok {
				domainFull[domain] = map[string]interface{}(result.Facts)
			}
		}
	}

	payload := buildPayload(m.cfg.Identity.AgentID, sysInfo, pkgs, checksum, m.version, recentLogs, connCount, infoCount, critCount, health, results, domainHashes, domainFull, vulns)

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

	if len(toResync) > 0 {
		// Only clear the domains we just reported domain_full for — mirrors
		// pendingResults above: cleared after a confirmed successful send,
		// not before, so a failed heartbeat keeps the resync request queued
		// for the next attempt instead of silently dropping it for a cycle.
		m.resyncMu.Lock()
		m.resyncDomains = nil
		m.resyncMu.Unlock()
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
	domainHashes map[string]string,
	domainFull map[string]map[string]interface{},
	vulns []modules.Vulnerability,
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
		"domain_hashes":     domainHashes,
		"domain_full":       domainFull,
		"vulnerabilities":   vulns,
	}
}

// handleResponse processes jobs and policy deltas from the server response.
func (m *Manager) handleResponse(ctx context.Context, resp map[string]interface{}) {
	if domains, ok := resp["resync_domains"].([]string); ok && len(domains) > 0 {
		m.resyncMu.Lock()
		m.resyncDomains = domains
		m.resyncMu.Unlock()
	}

	jobs, ok := resp["pending_jobs"]
	if !ok {
		m.maybeUpdatePolicy(resp)
		return
	}
	jobList, ok := jobs.([]interface{})
	if !ok || len(jobList) == 0 {
		return
	}
	m.log.Info("received pending jobs", "count", len(jobList))
	m.maybeUpdatePolicy(resp)

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

		// Pre-dispatch trust gate: signature + replay + capability coverage.
		// Rejections report back like any other failure so the job doesn't
		// hang RUNNING server-side until the timeout sweeper.
		stepsJSON := ""
		if jobType == "WORKFLOW_STEPS" {
			if raw, err := json.Marshal(params["steps"]); err == nil {
				stepsJSON = string(raw)
			}
		}
		if rejected := validateAndAuthorize(m.secCfg, m.verifier, m.replay,
			m.currentPolicy(), m.cfg.Identity.AgentID, jobID, jobType, params, stepsJSON, time.Now()); rejected != nil {
			m.log.Warn("job rejected by security pipeline",
				"job_id", jobID, "job_type", jobType, "error", rejected.Error)
			m.resultsMu.Lock()
			m.pendingResults = append(m.pendingResults, *rejected)
			m.resultsMu.Unlock()
			select {
			case m.nudge <- struct{}{}:
			default:
			}
			continue
		}
		if !m.secCfg.EnforceSignedJobs {
			if _, signed := params["_envelope"]; !signed && len(security.RequiredCapabilities(jobType, stepsJSON)) > 0 {
				m.log.Warn("UNSIGNED privileged job allowed (enforce_signed_jobs=false)",
					"job_id", jobID, "job_type", jobType)
			}
		}

		m.inFlightMu.Lock()
		if _, running := m.inFlight[jobID]; running {
			m.inFlightMu.Unlock()
			m.log.Warn("job already in flight, skipping duplicate dispatch", "job_id", jobID)
			continue
		}
		m.inFlight[jobID] = struct{}{}
		m.inFlightMu.Unlock()

		// Runs off the heartbeat goroutine — a long PACKAGE_UPDATE/
		// ANSIBLE_PLAYBOOK must not block the next heartbeat send.
		go func(jobID, jobType string, params map[string]interface{}, timeoutSec int) {
			defer func() {
				m.inFlightMu.Lock()
				delete(m.inFlight, jobID)
				m.inFlightMu.Unlock()
			}()

			result, ok := m.runJob(ctx, jobID, jobType, params, timeoutSec)
			if !ok {
				return
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

			select {
			case m.nudge <- struct{}{}:
			default: // heartbeat loop already has a pending nudge queued
			}
		}(jobID, jobType, params, timeoutSec)
	}
}

// runJob dispatches a single job to the executor matching its job_type. The
// bool return is always true now — every path reports back, even malformed
// or unrecognized jobs. It used to be false for those (skip, report
// nothing), which left the job RUNNING until JobTimeoutWorker swept it to
// TIMEOUT up to an hour later with zero explanation. A policy engine that
// generates jobs automatically needs failures to surface in ~1 heartbeat,
// not look like a hang.
// REBOOT/SERVICE/FILE/WORKFLOW_STEPS below are Faza 10's native modules —
// written, unit-tested, and dispatchable, but the backend workflow engine
// does not emit these job_types yet (services/workflow_engine.py's
// _dispatch_step still compiles service/system/file/package to
// CUSTOM_COMMAND shell, deliberately: there's no version/capability
// negotiation in the heartbeat protocol today, so a backend that started
// emitting these against an agent fleet running an older binary would have
// older agents silently fail via the `default:` branch below, since none
// of these job_types carry a `command` param). Wiring the backend to prefer
// these once a version gate exists is future work, not part of this change.
func (m *Manager) runJob(ctx context.Context, jobID, jobType string, params map[string]interface{}, timeoutSec int) (modules.JobResult, bool) {
	switch jobType {
	case "REBOOT":
		return modules.Reboot(ctx, jobID, params, timeoutSec), true
	case "SERVICE":
		return modules.Service(ctx, jobID, params, timeoutSec), true
	case "FILE":
		return modules.File(ctx, jobID, params, timeoutSec), true
	case "WORKFLOW_STEPS":
		steps, err := parseWorkflowSteps(params)
		if err != nil {
			m.log.Warn("workflow_steps parse error", "job_id", jobID, "error", err)
			return modules.JobResult{JobID: jobID, ExitCode: 1, Error: err.Error()}, true
		}
		return m.workflowStepsExec.Execute(ctx, jobID, steps, timeoutSec), true
	case "PLUGIN_INSTALL":
		return modules.InstallPlugin(ctx, jobID, params, timeoutSec), true
	case "PACKAGE_UPDATE":
		return modules.UpdatePackages(ctx, jobID, params, timeoutSec), true
	case "ANSIBLE_PLAYBOOK":
		playbookContent, _ := params["playbook_content"].(string)
		extraVars, _ := params["extra_vars"].(map[string]interface{})
		roles, _ := params["roles"].(map[string]interface{})
		if playbookContent == "" {
			m.log.Warn("ansible job has no playbook_content, skipping", "job_id", jobID)
			return modules.JobResult{JobID: jobID, ExitCode: 1, Error: "missing required parameter: playbook_content"}, true
		}
		return m.ansibleExec.Execute(ctx, jobID, playbookContent, extraVars, roles, timeoutSec, false), true
	case "COMPLIANCE_REMEDIATE":
		actions, err := parseRemediationActions(params)
		if err != nil {
			m.log.Warn("compliance_remediate parse error", "job_id", jobID, "error", err)
			return modules.JobResult{JobID: jobID, ExitCode: 1, Error: err.Error()}, true
		}
		operation, _ := params["operation"].(string)
		dryRun := operation == "DRY_RUN"
		return m.remediationExec.Execute(ctx, jobID, actions, timeoutSec, dryRun), true
	default:
		// Any job_type not matched above (including CUSTOM_COMMAND) falls
		// here — a bare `command` param is enough regardless of job_type,
		// same as before this fix, just no longer silent on failure.
		command, _ := params["command"].(string)
		if command == "" {
			m.log.Warn("unsupported job_type, skipping", "job_id", jobID, "job_type", jobType)
			return modules.JobResult{JobID: jobID, ExitCode: 1, Error: fmt.Sprintf("unsupported job_type %q: no command parameter", jobType)}, true
		}
		return m.jobExec.Execute(ctx, jobID, command, timeoutSec), true
	}
}

// parseRemediationActions extracts the per-agent action list from a
// COMPLIANCE_REMEDIATE job's parameters. The gRPC layer already filtered
// the fleet-wide actions map down to this agent's actions, so params["actions"]
// is a flat list here.
func parseRemediationActions(params map[string]interface{}) ([]modules.RemediationAction, error) {
	raw, ok := params["actions"]
	if !ok {
		return nil, fmt.Errorf("missing actions parameter")
	}
	list, ok := raw.([]interface{})
	if !ok {
		return nil, fmt.Errorf("actions parameter is not a list")
	}

	actions := make([]modules.RemediationAction, 0, len(list))
	for i, item := range list {
		m, ok := item.(map[string]interface{})
		if !ok {
			return nil, fmt.Errorf("action %d is not an object", i)
		}
		provider, _ := m["provider"].(string)
		body, _ := m["rendered_body"].(string)
		seq := 0
		if s, ok := m["sequence"].(float64); ok {
			seq = int(s)
		}
		actions = append(actions, modules.RemediationAction{
			Sequence: seq,
			Provider: provider,
			Body:     body,
		})
	}
	return actions, nil
}

// parseWorkflowSteps extracts the coalesced step list from a WORKFLOW_STEPS
// job's parameters — same shape as parseRemediationActions above, one
// abstraction level up (whole job types instead of remediation providers).
func parseWorkflowSteps(params map[string]interface{}) ([]modules.WorkflowStep, error) {
	raw, ok := params["steps"]
	if !ok {
		return nil, fmt.Errorf("missing steps parameter")
	}
	list, ok := raw.([]interface{})
	if !ok {
		return nil, fmt.Errorf("steps parameter is not a list")
	}

	steps := make([]modules.WorkflowStep, 0, len(list))
	for i, item := range list {
		m, ok := item.(map[string]interface{})
		if !ok {
			return nil, fmt.Errorf("step %d is not an object", i)
		}
		stepType, _ := m["type"].(string)
		stepParams, _ := m["params"].(map[string]interface{})
		seq := 0
		if s, ok := m["sequence"].(float64); ok {
			seq = int(s)
		}
		steps = append(steps, modules.WorkflowStep{
			Sequence: seq,
			Type:     stepType,
			Params:   stepParams,
		})
	}
	return steps, nil
}
