package modules

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"
)

// WorkflowStep is one coalesced step within a single WORKFLOW_STEPS job —
// several consecutive workflow-engine steps with no gate between them and
// the same targets, packed into one Job so they cost one heartbeat instead
// of one each (plan Partea I §12's coalescing optimization). Sequence
// controls execution order; Type is the workflow node type ("command",
// "package", "service", "system", "file", "ansible") — the same vocabulary
// _dispatch_step uses server-side.
type WorkflowStep struct {
	Sequence int
	Type     string
	Params   map[string]interface{}
}

// WorkflowStepsExecutor runs a coalesced list of steps in sequence, stopping
// at the first failure — one level up from RemediationExecutor (steps here
// are whole job types, not remediation providers within one action).
type WorkflowStepsExecutor struct {
	ansible *AnsibleExecutor
	shell   *JobExecutor
}

func NewWorkflowStepsExecutor(ansible *AnsibleExecutor, shell *JobExecutor) *WorkflowStepsExecutor {
	return &WorkflowStepsExecutor{ansible: ansible, shell: shell}
}

func (e *WorkflowStepsExecutor) dispatch(ctx context.Context, jobID, stepType string, params map[string]interface{}, timeoutSec int) JobResult {
	switch stepType {
	case "command":
		command, _ := params["command"].(string)
		if command == "" {
			return JobResult{JobID: jobID, ExitCode: 1, Error: "missing required parameter: command"}
		}
		return e.shell.Execute(ctx, jobID, command, timeoutSec)
	case "package":
		return UpdatePackages(ctx, jobID, params, timeoutSec)
	case "service":
		return Service(ctx, jobID, params, timeoutSec)
	case "system":
		return Reboot(ctx, jobID, params, timeoutSec)
	case "file":
		return File(ctx, jobID, params, timeoutSec)
	case "ansible":
		playbookContent, _ := params["playbook_content"].(string)
		if playbookContent == "" {
			return JobResult{JobID: jobID, ExitCode: 1, Error: "missing required parameter: playbook_content"}
		}
		extraVars, _ := params["extra_vars"].(map[string]interface{})
		roles, _ := params["roles"].(map[string]interface{})
		return e.ansible.Execute(ctx, jobID, playbookContent, extraVars, roles, timeoutSec, false)
	default:
		return JobResult{JobID: jobID, ExitCode: 1, Error: fmt.Sprintf("unsupported workflow step type: %q", stepType)}
	}
}

// Execute runs steps in sequence order, stopping at the first failure.
// Output from each step is prefixed with a label so the aggregated result
// shows which step produced what — same shape as RemediationExecutor.Execute.
func (e *WorkflowStepsExecutor) Execute(ctx context.Context, jobID string, steps []WorkflowStep, timeoutSec int) JobResult {
	start := time.Now()
	if len(steps) == 0 {
		return JobResult{JobID: jobID, ExitCode: 1, Error: "no workflow steps supplied", DurationMs: msSince(start)}
	}

	sorted := make([]WorkflowStep, len(steps))
	copy(sorted, steps)
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].Sequence < sorted[j].Sequence })

	var stdoutParts, stderrParts []string
	finalExit := 0
	finalErr := ""

	for _, step := range sorted {
		stepJobID := fmt.Sprintf("%s-step-%d", jobID, step.Sequence)
		result := e.dispatch(ctx, stepJobID, step.Type, step.Params, timeoutSec)

		label := fmt.Sprintf("[step %d %s] ", step.Sequence, step.Type)
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
			finalErr = fmt.Sprintf("step %d (%s) failed: %s", step.Sequence, step.Type, result.Error)
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
