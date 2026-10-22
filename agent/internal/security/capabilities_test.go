package security

import "testing"

// TestRegistryCoversCustomCommand locks the fix for the signed-jobs rollout
// break: the control plane signs CUSTOM_COMMAND as EXEC_BASH/CRITICAL, but the
// agent registry had no CUSTOM_COMMAND entry. With enforce_signed_jobs=true
// the agent rejects every job type it does not know ("unknown_capability"),
// so flipping that flag silently broke the only sanctioned arbitrary-command
// path for the whole fleet.
func TestRegistryCoversCustomCommand(t *testing.T) {
	if !IsRegistered("CUSTOM_COMMAND") {
		t.Fatal("CUSTOM_COMMAND missing from the capability registry — enforce_signed_jobs=true would reject every custom command job")
	}
	caps := RequiredCapabilities("CUSTOM_COMMAND", "")
	if len(caps) != 1 || caps[0] != CapExecBash {
		t.Fatalf("RequiredCapabilities(CUSTOM_COMMAND) = %v, want [%s]", caps, CapExecBash)
	}
	if risk := RiskFor(CapExecBash); risk != RiskCritical {
		t.Errorf("RiskFor(EXEC_BASH) = %q, want %q", risk, RiskCritical)
	}
}

// TestRegistryRejectsUnknownJobType keeps the registry honest: an unknown
// job_type must have no capabilities, so it never satisfies a capability
// check by accident.
func TestRegistryRejectsUnknownJobType(t *testing.T) {
	if IsRegistered("NOT_A_JOB_TYPE") {
		t.Fatal("IsRegistered(NOT_A_JOB_TYPE) = true, want false")
	}
	if caps := RequiredCapabilities("NOT_A_JOB_TYPE", ""); caps != nil {
		t.Fatalf("RequiredCapabilities(NOT_A_JOB_TYPE) = %v, want nil", caps)
	}
}
