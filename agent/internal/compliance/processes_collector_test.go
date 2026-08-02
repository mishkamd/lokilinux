package compliance

import (
	"os"
	"testing"
)

const sampleProcStatus = `Name:	bash
State:	S (sleeping)
Uid:	1000	1000	1000	1000
Gid:	1000	1000	1000	1000
`

func TestParseStatusUID(t *testing.T) {
	if uid := parseStatusUID(sampleProcStatus); uid != 1000 {
		t.Errorf("uid = %d, want 1000", uid)
	}
}

func TestParseStatusUID_MissingLine(t *testing.T) {
	if uid := parseStatusUID("Name:\tbash\n"); uid != 0 {
		t.Errorf("uid = %d, want 0 for missing Uid line", uid)
	}
}

func TestReadProcessFacts_CurrentProcess(t *testing.T) {
	proc, ok := readProcessFacts(os.Getpid())
	if !ok {
		t.Fatal("readProcessFacts(os.Getpid()) returned ok=false")
	}
	if proc.PID != os.Getpid() {
		t.Errorf("PID = %d, want %d", proc.PID, os.Getpid())
	}
	if proc.Name == "" {
		t.Error("Name is empty")
	}
}

func TestProcessesCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*ProcessesCollector)(nil)
	c := NewProcessesCollector()
	if c.Domain() != "processes" {
		t.Errorf("Domain() = %q, want processes", c.Domain())
	}
}
