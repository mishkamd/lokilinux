package broker

import (
	"context"
	"fmt"
	"sync/atomic"
	"time"

	"github.com/lokilinux/agent/internal/modules"
)

// Logger is the audit sink the broker needs (satisfied by slog wrapper).
type Logger interface {
	Audit(event, jobID string, peerUID, exitCode, durationMs int)
}

var inFlight int64 // global concurrency guard

const maxConcurrent = 2

// metricsDenied is a stub hook wired to prometheus by main.go via SetMetricsHook.
var metricsDenied = func(string) {}

func SetDeniedHook(fn func(string)) { metricsDenied = fn }

// Execute dispatches an allowlisted operation to the existing executor
// modules — the broker adds NO new execution semantics, only authorization,
// strict parameter extraction and audit.
func Execute(req *Request) modules.JobResult {
	if n := atomic.AddInt64(&inFlight, 1); n > maxConcurrent {
		atomic.AddInt64(&inFlight, -1)
		return modules.JobResult{JobID: req.JobID, ExitCode: 1, Error: "broker busy"}
	}
	defer atomic.AddInt64(&inFlight, -1)

	timeout := req.TimeoutSec
	if timeout <= 0 || timeout > 4*3600 {
		timeout = defaultTimeout
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(timeout)*time.Second)
	defer cancel()

	jobID := req.JobID
	if jobID == "" {
		jobID = "broker-" + req.RequestID
	}
	args := req.Arguments

	switch req.Operation {
	case "package.update":
		params := map[string]interface{}{}
		if names, ok := args["package_names"].([]interface{}); ok {
			clean := make([]interface{}, 0, len(names))
			for _, n := range names {
				if s, ok := n.(string); ok {
					clean = append(clean, s)
				}
			}
			params["package_names"] = clean
		} else if len(args) != 0 {
			return badReq(jobID, "package_names must be an array of strings")
		}
		return modules.UpdatePackages(ctx, jobID, params, timeout)

	case "service.control":
		name, _ := args["service_name"].(string)
		action, _ := args["action"].(string)
		if name == "" {
			return badReq(jobID, "service_name required")
		}
		switch action {
		case "start", "stop", "restart", "status":
		default:
			return badReq(jobID, "action must be start|stop|restart|status")
		}
		return modules.Service(ctx, jobID, map[string]interface{}{
			"name": name, "action": action}, timeout)

	case "reboot":
		if len(args) != 0 {
			return badReq(jobID, "reboot takes no arguments")
		}
		return modules.Reboot(ctx, jobID, map[string]interface{}{}, timeout)

	case "file.manage":
		// File() validates action/path itself; pass through strictly.
		return modules.File(ctx, jobID, args, timeout)

	case "ansible.run":
		playbook, _ := args["playbook_content"].(string)
		if playbook == "" {
			return badReq(jobID, "playbook_content required")
		}
		if len(playbook) > 1<<20 {
			return badReq(jobID, "playbook exceeds 1MiB")
		}
		extraVars, _ := args["extra_vars"].(map[string]interface{})
		roles, _ := args["roles"].(map[string]interface{})
		return modules.NewAnsibleExecutor().Execute(ctx, jobID, playbook, extraVars, roles, timeout, false)

	case "python.exec":
		script, _ := args["script"].(string)
		if script == "" {
			return badReq(jobID, "script required")
		}
		if len(script) > 256<<10 {
			return badReq(jobID, "script exceeds 256KiB")
		}
		return modules.NewPythonExecutor().Execute(ctx, jobID, script, timeout)

	case "bash.exec":
		command, _ := args["command"].(string)
		if command == "" {
			return badReq(jobID, "command required")
		}
		return modules.NewJobExecutor().Execute(ctx, jobID, command, timeout)

	default:
		metricsDenied("unknown_operation")
		return badReq(jobID, fmt.Sprintf("operation %q not in allowlist", req.Operation))
	}
}

func badReq(jobID, msg string) modules.JobResult {
	metricsDenied("invalid_schema")
	return modules.JobResult{JobID: jobID, ExitCode: 1, Error: "rejected [invalid_broker_request]: " + msg}
}
