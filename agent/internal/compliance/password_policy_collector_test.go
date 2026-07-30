package compliance

import (
	"strings"
	"testing"
)

const samplePwquality = `# comment
minlen = 12
dcredit = -1
enforcing
`

func TestParsePwqualityConf_KeyValueAndBareFlag(t *testing.T) {
	facts := parsePwqualityConf(strings.NewReader(samplePwquality))
	if facts["minlen"] != "12" {
		t.Errorf("minlen = %v, want 12", facts["minlen"])
	}
	if facts["dcredit"] != "-1" {
		t.Errorf("dcredit = %v, want -1", facts["dcredit"])
	}
	if _, ok := facts["enforcing"]; !ok {
		t.Error("bare flag 'enforcing' missing")
	}
}

func TestPasswordPolicyCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*PasswordPolicyCollector)(nil)
	c := NewPasswordPolicyCollector()
	if c.Domain() != "password_policy" {
		t.Errorf("Domain() = %q, want password_policy", c.Domain())
	}
}
