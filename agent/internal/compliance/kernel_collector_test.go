package compliance

import (
	"strings"
	"testing"
)

const sampleGrubDefault = `GRUB_DEFAULT=0
GRUB_TIMEOUT=5
GRUB_CMDLINE_LINUX="crashkernel=auto rhgb quiet"
# a comment

GRUB_DISABLE_RECOVERY="true"
`

func TestParseGrubDefault_StripsQuotes(t *testing.T) {
	values := parseGrubDefault(strings.NewReader(sampleGrubDefault))
	if values["GRUB_CMDLINE_LINUX"] != "crashkernel=auto rhgb quiet" {
		t.Errorf("GRUB_CMDLINE_LINUX = %q, want unquoted value", values["GRUB_CMDLINE_LINUX"])
	}
	if values["GRUB_TIMEOUT"] != "5" {
		t.Errorf("GRUB_TIMEOUT = %q, want 5", values["GRUB_TIMEOUT"])
	}
}

func TestParseGrubDefault_CommentsAndBlankLinesIgnored(t *testing.T) {
	values := parseGrubDefault(strings.NewReader(sampleGrubDefault))
	if len(values) != 4 {
		t.Errorf("got %d entries, want 4 (comment/blank line excluded): %v", len(values), values)
	}
}

func TestKernelCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*KernelCollector)(nil)
	c := NewKernelCollector()
	if c.Domain() != "kernel" {
		t.Errorf("Domain() = %q, want kernel", c.Domain())
	}
}
