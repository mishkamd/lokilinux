// Broker routing: when security.exec_broker_socket is configured, privileged
// job execution moves out of the (non-root) agent process into loki-agent-exec.
package agent

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/lokilinux/agent/internal/broker"
	"github.com/lokilinux/agent/internal/modules"
)

func newBrokerClientIfConfigured(socket string) *broker.Client {
	if socket == "" {
		return nil
	}
	return broker.NewClient(socket)
}

// runJobViaBroker maps a validated job to its broker operation. Parameter
// extraction mirrors the in-process executors 1:1 — the broker re-validates
// against the same allowlist, so this mapping stays honest by construction.
func (m *Manager) runJobViaBroker(jobID, jobType string, params map[string]interface{}, timeoutSec int) modules.JobResult {
	c := m.brokerClient
	run := func(operation string, args map[string]interface{}) modules.JobResult {
		return c.Run(operation, jobID, args, timeoutSec)
	}
	switch jobType {
	case "REBOOT":
		return run("reboot", map[string]interface{}{})
	case "SERVICE":
		return run("service.control", params)
	case "FILE":
		return run("file.manage", params)
	case "PACKAGE_UPDATE":
		return run("package.update", params)
	case "ANSIBLE_PLAYBOOK":
		playbookContent, _ := params["playbook_content"].(string)
		if playbookContent == "" {
			return modules.JobResult{JobID: jobID, ExitCode: 1, Error: "missing required parameter: playbook_content"}
		}
		return run("ansible.run", params)
	case "WORKFLOW_STEPS":
		return run("bash.exec", map[string]interface{}{
			"command": firstWorkflowCommand(params),
		})
	case "COMPLIANCE_REMEDIATE":
		// Remediation composes shell/ansible/python actions — route through
		// bash.exec with the pre-compiled command the remediation executor
		// would have produced is NOT possible generically; keep local path
		// until per-provider broker ops exist. Explicit refusal keeps us
		// fail-closed rather than silently running as root in-process.
		return modules.JobResult{JobID: jobID, ExitCode: 1,
			Error: "rejected [broker_gap]: COMPLIANCE_REMEDIATE has no broker operation yet; unset exec_broker_socket for this fleet until Faza 2.1"}
	default:
		// Unknown types never reach here — the validation gate rejects them
		// under enforcement; in observability mode fall back locally.
		return m.runLocal(context.Background(), jobID, jobType, params, timeoutSec)
	}
}

func firstWorkflowCommand(params map[string]interface{}) string {
	if steps, ok := params["steps"].([]interface{}); ok && len(steps) > 0 {
		if s0, ok := steps[0].(map[string]interface{}); ok {
			p, _ := s0["params"].(map[string]interface{})
			cmd, _ := p["command"].(string)
			return cmd
		}
	}
	cmd, _ := params["command"].(string)
	return cmd
}


// wireBrokerUpdateChecker delegates package-update checks to the exec broker:
// dnf/apt metadata caches need privileged writes, which the non-root core no
// longer has. The JSON snapshot comes back from package.check_updates.
func wireBrokerUpdateChecker(mgr *Manager, client *broker.Client) {
	mgr.pkgMod.SetBrokerUpdateChecker(func() (map[string]modules.UpdateSnapshot, error) {
		res := client.Run("package.check_updates", "telemetry-check-updates",
			map[string]interface{}{}, 300)
		if res.ExitCode != 0 || res.Error != "" {
			return nil, fmt.Errorf("broker check_updates: %s %s", res.Error, res.Stderr)
		}
		var snap struct {
			PackageManager string                           `json:"package_manager"`
			Updates        map[string]modules.UpdateSnapshot `json:"updates"`
		}
		if err := json.Unmarshal([]byte(res.Stdout), &snap); err != nil {
			return nil, fmt.Errorf("broker check_updates parse: %w", err)
		}
		return snap.Updates, nil
	})
}
