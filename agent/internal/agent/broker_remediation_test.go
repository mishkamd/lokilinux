package agent

import (
	"strings"
	"testing"

	"github.com/lokilinux/agent/internal/broker"
	"github.com/lokilinux/agent/internal/modules"
)

// TestBrokerRemediationRunners: SetBrokerRunners routes shell/ansible/python
// bodies through the injected runner instead of in-process executors.
func TestBrokerRemediationRunners(t *testing.T) {
	var capturedOps []string
	run := func(operation string, args map[string]interface{}, timeoutSec int) modules.JobResult {
		capturedOps = append(capturedOps, operation)
		switch operation {
		case "bash.exec":
			return modules.JobResult{ExitCode: 0, Stdout: "shell-ok"}
		case "ansible.run":
			return modules.JobResult{ExitCode: 3, Stderr: "playbook failed"}
		default:
			return modules.JobResult{ExitCode: 0}
		}
	}
	ex := modules.NewRemediationExecutor(nil, nil, nil)
	ex.SetBrokerRunners(map[string]modules.ActionRunner{
		"shell":   modules.NewBrokerRemediationRunner(run, "shell"),
		"ansible": modules.NewBrokerRemediationRunner(run, "ansible"),
		"python":  modules.NewBrokerRemediationRunner(run, "python"),
	})

	res := ex.Execute(t.Context(), "job-b", []modules.RemediationAction{
		{Sequence: 1, Provider: "shell", Body: "echo ok"},
	}, 30, false)
	if res.ExitCode != 0 || !strings.Contains(res.Stdout, "shell-ok") {
		t.Fatalf("broker shell action failed: %+v", res)
	}

	res = ex.Execute(t.Context(), "job-c", []modules.RemediationAction{
		{Sequence: 1, Provider: "ansible", Body: "playbook"},
	}, 30, false)
	if res.ExitCode == 0 {
		t.Fatal("failing ansible broker action not surfaced")
	}
	if len(capturedOps) != 2 || capturedOps[0] != "bash.exec" || capturedOps[1] != "ansible.run" {
		t.Fatalf("unexpected op sequence: %v", capturedOps)
	}
}

// Dry-run stays LOCAL even with broker runners installed (no privileges needed).
func TestDryRunBypassesBroker(t *testing.T) {
	brokerCalled := false
	run := func(operation string, args map[string]interface{}, timeoutSec int) modules.JobResult {
		brokerCalled = true
		return modules.JobResult{ExitCode: 0}
	}
	ex := modules.NewRemediationExecutor(
		modules.NewJobExecutor(), nil, nil)
	ex.SetBrokerRunners(map[string]modules.ActionRunner{
		"shell": modules.NewBrokerRemediationRunner(run, "shell"),
	})
	ex.Execute(t.Context(), "job-d", []modules.RemediationAction{
		{Sequence: 1, Provider: "shell", Body: "echo dryrun"},
	}, 10, true)
	if brokerCalled {
		t.Fatal("dry-run must not hit the broker")
	}
	_ = broker.Client{} // import guard
}
