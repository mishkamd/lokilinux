package compliance

import (
	"strings"
	"testing"
)

const sampleProcMounts = `/dev/sda1 / ext4 rw,relatime 0 0
tmpfs /tmp tmpfs rw,nosuid,nodev,noexec 0 0
proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0
`

func TestParseProcMounts_ParsesFields(t *testing.T) {
	mounts := parseProcMounts(strings.NewReader(sampleProcMounts))
	if len(mounts) != 3 {
		t.Fatalf("mounts len = %d, want 3", len(mounts))
	}
	root := mounts[0]
	if root.Source != "/dev/sda1" || root.Target != "/" || root.FSType != "ext4" {
		t.Errorf("root mount = %+v, want /dev/sda1 / ext4", root)
	}
	if len(root.Options) != 2 || root.Options[0] != "rw" || root.Options[1] != "relatime" {
		t.Errorf("root options = %v, want [rw relatime]", root.Options)
	}
}

// TestParseProcMounts_TmpNoexecDetectable locks the exact use case this
// collector exists for — docs/compliance/08-DRIFT-FIM.md's "/tmp mounted
// noexec" rule needs to find "noexec" inside /tmp's options via CEL's
// `in` operator.
func TestParseProcMounts_TmpNoexecDetectable(t *testing.T) {
	mounts := parseProcMounts(strings.NewReader(sampleProcMounts))
	var tmp *Mount
	for i := range mounts {
		if mounts[i].Target == "/tmp" {
			tmp = &mounts[i]
		}
	}
	if tmp == nil {
		t.Fatal("/tmp mount not found")
	}
	found := false
	for _, o := range tmp.Options {
		if o == "noexec" {
			found = true
		}
	}
	if !found {
		t.Errorf("/tmp options = %v, want noexec present", tmp.Options)
	}
}

func TestParseProcMounts_MalformedLineSkipped(t *testing.T) {
	mounts := parseProcMounts(strings.NewReader("bad line\n/dev/sda1 / ext4 rw 0 0\n"))
	if len(mounts) != 1 {
		t.Errorf("mounts = %+v, want exactly 1 (malformed line skipped)", mounts)
	}
}

func TestParseProcMounts_EmptyInput(t *testing.T) {
	mounts := parseProcMounts(strings.NewReader(""))
	if len(mounts) != 0 {
		t.Errorf("mounts = %+v, want empty", mounts)
	}
}

func TestMountsCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*MountsCollector)(nil)
	c := NewMountsCollector()
	if c.Domain() != "mounts" {
		t.Errorf("Domain() = %q, want mounts", c.Domain())
	}
}
