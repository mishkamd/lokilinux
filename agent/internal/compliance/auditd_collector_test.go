package compliance

import "testing"

func TestParseAuditctlOutput_KeepsRuleLines(t *testing.T) {
	output := "-w /etc/shadow -p wa -k identity\n-w /etc/passwd -p wa -k identity\n"
	rules := parseAuditctlOutput(output)
	if len(rules) != 2 {
		t.Fatalf("rules = %v, want 2", rules)
	}
	if rules[0] != "-w /etc/shadow -p wa -k identity" {
		t.Errorf("rules[0] = %q", rules[0])
	}
}

func TestParseAuditctlOutput_NoRulesLineKept(t *testing.T) {
	rules := parseAuditctlOutput("No rules\n")
	if len(rules) != 1 || rules[0] != "No rules" {
		t.Errorf("rules = %v, want [\"No rules\"] (a real, meaningful auditctl output line)", rules)
	}
}

func TestParseAuditctlOutput_BlankLinesDropped(t *testing.T) {
	rules := parseAuditctlOutput("\n\n-w /etc/shadow -p wa -k identity\n\n")
	if len(rules) != 1 {
		t.Errorf("rules = %v, want exactly 1", rules)
	}
}

func TestParseAuditctlOutput_EmptyOutput(t *testing.T) {
	rules := parseAuditctlOutput("")
	if len(rules) != 0 {
		t.Errorf("rules = %v, want empty", rules)
	}
}

func TestAuditdCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*AuditdCollector)(nil)
	c := NewAuditdCollector()
	if c.Domain() != "auditd" {
		t.Errorf("Domain() = %q, want auditd", c.Domain())
	}
}
