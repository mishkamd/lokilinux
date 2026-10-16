package agent

// nativeCapabilities lists the job types this build executes with its own
// modules rather than a shell command. Sent on every heartbeat so the server
// can pick a native job type only for agents that run it (ROADMAP R5). Keep
// this in step with the cases in runJob.
func nativeCapabilities() []string {
	return []string{"REBOOT", "SERVICE", "FILE", "WORKFLOW_STEPS", "PACKAGE_UPDATE"}
}
