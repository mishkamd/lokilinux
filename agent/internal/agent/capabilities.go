package agent

import (
	"github.com/lokilinux/agent/internal/modules"
)

// nativeCapabilities lists the job types this build executes with its own
// modules rather than a shell command. Sent on every heartbeat so the server
// can pick a native job type only for agents that run it (ROADMAP R5). Keep
// this in step with the cases in runJob.
func nativeCapabilities() []string {
	caps := []string{"REBOOT", "SERVICE", "FILE", "WORKFLOW_STEPS", "PACKAGE_UPDATE"}
	// ANSIBLE_PLAYBOOK is conditional: without ansible-core on the host the
	// playbook would only fail at exec time, after the operator picked it.
	if modules.AnsibleAvailable() {
		caps = append(caps, "ANSIBLE_PLAYBOOK")
	}
	return caps
}
