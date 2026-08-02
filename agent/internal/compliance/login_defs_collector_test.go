package compliance

import (
	"strings"
	"testing"
)

const sampleLoginDefs = `# comment
PASS_MAX_DAYS	99999
PASS_MIN_DAYS	0
PASS_MIN_LEN	5
UMASK		022
`

func TestParseLoginDefs_KeyValue(t *testing.T) {
	facts := parseLoginDefs(strings.NewReader(sampleLoginDefs))
	tests := map[string]string{
		"PASS_MAX_DAYS": "99999",
		"PASS_MIN_DAYS": "0",
		"UMASK":         "022",
	}
	for key, want := range tests {
		if got, _ := facts[key].(string); got != want {
			t.Errorf("facts[%q] = %v, want %q", key, facts[key], want)
		}
	}
}

func TestParseLoginDefs_CommentIgnored(t *testing.T) {
	facts := parseLoginDefs(strings.NewReader(sampleLoginDefs))
	if len(facts) != 4 {
		t.Errorf("got %d entries, want 4: %v", len(facts), facts)
	}
}

func TestLoginDefsCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*LoginDefsCollector)(nil)
	c := NewLoginDefsCollector()
	if c.Domain() != "login_defs" {
		t.Errorf("Domain() = %q, want login_defs", c.Domain())
	}
}
