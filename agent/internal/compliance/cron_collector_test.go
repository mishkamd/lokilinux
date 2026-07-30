package compliance

import (
	"strings"
	"testing"
)

const sampleCronFile = `# comment
*/5 * * * * root /usr/bin/backup.sh

0 2 * * * root /usr/bin/cleanup.sh
`

func TestParseCronFileLines_StripsCommentsAndBlank(t *testing.T) {
	lines := parseCronFileLines(strings.NewReader(sampleCronFile))
	if len(lines) != 2 {
		t.Fatalf("got %d lines, want 2: %v", len(lines), lines)
	}
	if !strings.Contains(lines[0], "backup.sh") {
		t.Errorf("lines[0] = %q, want backup.sh entry", lines[0])
	}
}

func TestCronCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*CronCollector)(nil)
	c := NewCronCollector()
	if c.Domain() != "cron" {
		t.Errorf("Domain() = %q, want cron", c.Domain())
	}
}
