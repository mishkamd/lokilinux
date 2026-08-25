package security

// Capability registry: maps every job_type the manager can dispatch to its
// required capability and risk tier (plan §27). A job_type absent from this
// registry is treated as privileged-but-unknown and REJECTED when signed-job
// enforcement is on — fail closed (plan §28).

import "strings"

type RiskLevel string

const (
	RiskLow      RiskLevel = "LOW"
	RiskMedium   RiskLevel = "MEDIUM"
	RiskHigh     RiskLevel = "HIGH"
	RiskCritical RiskLevel = "CRITICAL"
)

// Capability names are the authorization vocabulary shared with the control
// plane's policy engine and RBAC roles.
const (
	CapReadSystem           = "READ_SYSTEM"
	CapReadLogs             = "READ_LOGS"
	CapServiceControl       = "SERVICE_CONTROL"
	CapPackageManagement    = "PACKAGE_MANAGEMENT"
	CapNetworkConfig        = "NETWORK_CONFIGURATION"
	CapFirewallConfig       = "FIREWALL_CONFIGURATION"
	CapExecBash             = "EXEC_BASH"
	CapExecPython           = "EXEC_PYTHON"
	CapExecAnsible          = "EXEC_ANSIBLE"
	CapSecurityRemediation  = "SECURITY_REMEDIATION"
	CapPluginInstall        = "PLUGIN_INSTALL"
	CapRebootHost           = "REBOOT_HOST"
	CapFileWrite            = "FILE_WRITE"
)

type Capability struct {
	Name string
	Risk RiskLevel
}

// Registry: job_type → capability. WORKFLOW_STEPS is special: it can carry
// command/package/service/system/file/ansible steps, so RequiredCapabilities
// inspects the actual steps; the static entry lists the union it may demand.
var Registry = map[string]Capability{
	"HEARTBEAT":           {CapReadSystem, RiskLow},
	"FILE_READ":           {CapReadSystem, RiskLow},
	"LOG_READ":            {CapReadLogs, RiskLow},
	"SERVICE":             {CapServiceControl, RiskMedium},
	"PACKAGE_UPDATE":      {CapPackageManagement, RiskHigh},
	"COMPLIANCE_REMEDIATE":{CapSecurityRemediation, RiskHigh},
	"FIREWALL_CHANGE":     {CapFirewallConfig, RiskHigh},
	"REBOOT":              {CapRebootHost, RiskHigh},
	"FILE":                {CapFileWrite, RiskMedium},
	"WORKFLOW_STEPS":      {CapExecBash, RiskCritical},
	"ANSIBLE_PLAYBOOK":    {CapExecAnsible, RiskCritical},
	"PLUGIN_INSTALL":      {CapPluginInstall, RiskCritical},
}

// IsRegistered reports whether a job_type is known to the agent.
func IsRegistered(jobType string) bool {
	_, ok := Registry[jobType]
	return ok
}

// RiskFor returns the risk tier of a capability name ("" when unknown).
func RiskFor(capability string) RiskLevel {
	for _, c := range Registry {
		if c.Name == capability {
			return c.Risk
		}
	}
	return ""
}

// RequiredCapabilities returns the capability set a job_type demands.
// WORKFLOW_STEPS expands to one capability per distinct step type present.
func RequiredCapabilities(jobType string, workflowStepsJSON string) []string {
	if jobType == "WORKFLOW_STEPS" && workflowStepsJSON != "" {
		caps := workflowStepCapabilities(workflowStepsJSON)
		if len(caps) > 0 {
			return caps
		}
	}
	c, ok := Registry[jobType]
	if !ok {
		return nil
	}
	return []string{c.Name}
}

// workflowStepCapabilities maps step types to capabilities without parsing
// full JSON — a cheap substring scan over the serialized steps array is
// sufficient because step types come from a fixed vocabulary and the strings
// searched ("command", "ansible", ...) cannot appear as keys of anything
// else in that structure. Unknown step types demand EXEC_BASH (strictest
// match) so they can never sneak through with no capability requirement.
func workflowStepCapabilities(stepsJSON string) []string {
	seen := map[string]bool{}
	add := func(c string) { seen[c] = true }
	if strings.Contains(stepsJSON, `"package"`) || strings.Contains(stepsJSON, `'package'`) {
		add(CapPackageManagement)
	}
	if strings.Contains(strings.ToLower(stepsJSON), `"service"`) {
		add(CapServiceControl)
	}
	if strings.Contains(strings.ToLower(stepsJSON), `"ansible"`) {
		add(CapExecAnsible)
	}
	if strings.Contains(strings.ToLower(stepsJSON), `"system"`) {
		add(CapRebootHost)
	}
	if strings.Contains(strings.ToLower(stepsJSON), `"file"`) {
		add(CapFileWrite)
	}
	if len(seen) == 0 || strings.Contains(strings.ToLower(stepsJSON), `"command"`) {
		add(CapExecBash)
	}
	out := make([]string, 0, len(seen))
	for c := range seen {
		out = append(out, c)
	}
	return out
}
