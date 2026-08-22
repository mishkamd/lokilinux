package modules

import "testing"

// Only the pure/no-execution paths are unit-tested here — same boundary the
// codebase already draws for RemediationExecutor (no remediation_executor_test.go
// exists either): sequencing across real command/package/service dispatch
// needs systemd-run and real system state, not available in a unit test.

func TestWorkflowStepsExecuteRejectsEmptySteps(t *testing.T) {
	e := NewWorkflowStepsExecutor(nil, nil)
	result := e.Execute(nil, "job-1", nil, 30)
	if result.ExitCode == 0 {
		t.Errorf("expected a non-zero exit code for an empty step list")
	}
	if result.Error == "" {
		t.Errorf("expected an error message for an empty step list")
	}
}

func TestWorkflowStepsDispatchRejectsUnsupportedType(t *testing.T) {
	e := NewWorkflowStepsExecutor(nil, nil)
	result := e.dispatch(nil, "job-1", "bogus-type", nil, 30)
	if result.ExitCode == 0 {
		t.Errorf("expected a non-zero exit code for an unsupported step type")
	}
	if result.Error == "" {
		t.Errorf("expected an error message for an unsupported step type")
	}
}

func TestWorkflowStepsDispatchCommandRejectsMissingCommand(t *testing.T) {
	e := NewWorkflowStepsExecutor(nil, NewJobExecutor())
	result := e.dispatch(nil, "job-1", "command", map[string]interface{}{}, 30)
	if result.ExitCode == 0 {
		t.Errorf("expected a non-zero exit code for a command step with no config.command")
	}
}

func TestWorkflowStepsDispatchAnsibleRejectsMissingPlaybook(t *testing.T) {
	e := NewWorkflowStepsExecutor(NewAnsibleExecutor(), nil)
	result := e.dispatch(nil, "job-1", "ansible", map[string]interface{}{}, 30)
	if result.ExitCode == 0 {
		t.Errorf("expected a non-zero exit code for an ansible step with no playbook_content")
	}
}
