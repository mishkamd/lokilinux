package modules

import "testing"

func TestServiceNameRe(t *testing.T) {
	valid := []string{"nginx", "nginx.service", "docker.socket", "user@1000.service", "my-app_v2"}
	invalid := []string{"nginx; rm -rf /", "curl|sh", "$(whoami)", "a b", "nginx && evil"}
	for _, n := range valid {
		if !isValidServiceName(n) {
			t.Errorf("expected %q to be a valid service name", n)
		}
	}
	for _, n := range invalid {
		if isValidServiceName(n) {
			t.Errorf("expected %q to be rejected as a service name", n)
		}
	}
}

func TestServiceActionsTable(t *testing.T) {
	want := map[string]string{
		"start": "running", "stop": "stopped",
		"restart": "restarted", "reload": "reloaded",
		"enable": "enabled", "disable": "disabled",
	}
	for action, label := range want {
		if got := serviceActions[action]; got != label {
			t.Errorf("serviceActions[%q] = %q, want %q", action, got, label)
		}
	}
	if _, ok := serviceActions["delete"]; ok {
		t.Errorf("serviceActions must not contain a non-systemctl action")
	}
}
