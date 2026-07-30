package compliance

import (
	"strings"
	"testing"
)

const sampleLsmod = `Module                  Size  Used by
cramfs                 16384  0
overlay               167936  1
nf_tables             221184  3 nft_ct,nft_chain_nat
`

func TestParseLsmod_SkipsHeaderRow(t *testing.T) {
	modules := parseLsmod(sampleLsmod)
	want := []string{"cramfs", "overlay", "nf_tables"}
	if len(modules) != len(want) {
		t.Fatalf("got %v, want %v", modules, want)
	}
	for i, m := range want {
		if modules[i] != m {
			t.Errorf("modules[%d] = %q, want %q", i, modules[i], m)
		}
	}
}

const sampleModprobeConf = `# blacklist rare filesystems
blacklist cramfs
blacklist freevxfs
options nf_conntrack hashsize=65536
`

func TestParseModprobeBlacklist(t *testing.T) {
	names := parseModprobeBlacklist(strings.NewReader(sampleModprobeConf))
	if len(names) != 2 || names[0] != "cramfs" || names[1] != "freevxfs" {
		t.Errorf("names = %v, want [cramfs freevxfs]", names)
	}
}

func TestKernelModulesCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*KernelModulesCollector)(nil)
	c := NewKernelModulesCollector()
	if c.Domain() != "kernel_modules" {
		t.Errorf("Domain() = %q, want kernel_modules", c.Domain())
	}
}
