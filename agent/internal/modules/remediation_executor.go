package modules

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"
)

// RemediationAction is a single step in a remediation plan, dispatched to
// the agent that owns it. Sequence controls execution order within a plan.
type RemediationAction struct {
	Sequence int
	Provider string
	Body     string
}

// ActionRunner is the function signature each provider maps to. Injected
// for testability — production wiring uses real executors.
type ActionRunner func(ctx context.Context, jobID, body string, timeoutSec int) JobResult

// RemediationExecutor orchestrates sequential execution of remediation
// actions across potentially multiple providers. Stops on first failure
// and aggregates output from all steps.
type RemediationExecutor struct {
	shell   *JobExecutor
	ansible *AnsibleExecutor
	python  *PythonExecutor
}

func NewRemediationExecutor(shell *JobExecutor, ansible *AnsibleExecutor, python *PythonExecutor) *RemediationExecutor {
	return &RemediationExecutor{shell: shell, ansible: ansible, python: python}
}

// runnerFor returns the ActionRunner for a given provider — dryRun selects
// each provider's real check/dry-run mode (ansible --check --diff, sh -n,
// Python ast.parse) instead of actually applying the action
// (docs/compliance §13, §14). shell uses JobExecutor (runs via /bin/sh -c
// under systemd-run); ansible and python use their own argv-based executors
// with empty extra_vars/roles.
func (e *RemediationExecutor) runnerFor(provider string, dryRun bool) (ActionRunner, error) {
	switch provider {
	case "shell":
		if dryRun {
			return func(ctx context.Context, jobID, body string, timeoutSec int) JobResult {
				return e.shell.CheckSyntax(ctx, jobID, body, timeoutSec)
			}, nil
		}
		return func(ctx context.Context, jobID, body string, timeoutSec int) JobResult {
			return e.shell.Execute(ctx, jobID, body, timeoutSec)
		}, nil
	case "ansible":
		return func(ctx context.Context, jobID, body string, timeoutSec int) JobResult {
			return e.ansible.Execute(ctx, jobID, body, nil, nil, timeoutSec, dryRun)
		}, nil
	case "python":
		if dryRun {
			return func(ctx context.Context, jobID, body string, timeoutSec int) JobResult {
				return e.python.CheckSyntax(ctx, jobID, body, timeoutSec)
			}, nil
		}
		return func(ctx context.Context, jobID, body string, timeoutSec int) JobResult {
			return e.python.Execute(ctx, jobID, body, timeoutSec)
		}, nil
	default:
		return nil, fmt.Errorf("unsupported remediation provider %q", provider)
	}
}

// Execute runs actions in sequence order. Stops on the first non-zero exit
// code or error. Output from each action is prefixed with a label so the
// aggregated result shows which step produced what. dryRun runs each
// provider's real check mode instead of applying anything — see runnerFor.
func (e *RemediationExecutor) Execute(ctx context.Context, jobID string, actions []RemediationAction, timeoutSec int, dryRun bool) JobResult {
	start := time.Now()

	if len(actions) == 0 {
		return JobResult{
			JobID: jobID, ExitCode: 1,
			Error:      "no remediation actions supplied",
			DurationMs: msSince(start),
		}
	}

	// Sort by sequence ascending
	sorted := make([]RemediationAction, len(actions))
	copy(sorted, actions)
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].Sequence < sorted[j].Sequence })

	var stdoutParts, stderrParts []string
	finalExit := 0
	finalErr := ""

	for _, action := range sorted {
		if strings.TrimSpace(action.Body) == "" {
			finalExit = 1
			finalErr = fmt.Sprintf("remediation action %d has empty rendered_body", action.Sequence)
			break
		}

		runner, err := e.runnerFor(action.Provider, dryRun)
		if err != nil {
			finalExit = 1
			finalErr = err.Error()
			break
		}

		// Per-step jobID so systemd-run output files don't collide
		stepJobID := fmt.Sprintf("%s-step-%d", jobID, action.Sequence)
		result := runner(ctx, stepJobID, action.Body, timeoutSec)

		label := fmt.Sprintf("[action %d %s] ", action.Sequence, action.Provider)
		if result.Stdout != "" {
			stdoutParts = append(stdoutParts, label+result.Stdout)
		}
		if result.Stderr != "" {
			stderrParts = append(stderrParts, label+result.Stderr)
		}

		if result.ExitCode != 0 || result.Error != "" {
			finalExit = result.ExitCode
			if finalExit == 0 {
				finalExit = 1
			}
			finalErr = fmt.Sprintf("action %d (%s) failed: %s", action.Sequence, action.Provider, result.Error)
			break
		}
	}

	return JobResult{
		JobID:      jobID,
		ExitCode:   finalExit,
		Stdout:     strings.Join(stdoutParts, "\n"),
		Stderr:     strings.Join(stderrParts, "\n"),
		DurationMs: msSince(start),
		Error:      finalErr,
	}
}
