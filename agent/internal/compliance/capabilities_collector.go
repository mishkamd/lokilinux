package compliance

import (
	"bufio"
	"context"
	"errors"
	"os/exec"
	"strings"
	"time"
)

// capabilitiesDefaultPaths scopes `getcap -r` to the executable search
// path rather than the full filesystem (`getcap -r /`) — a full-tree scan
// is expensive at 100k-agent scale for a check that in practice only ever
// matters for binaries an admin or attacker would actually invoke.
var capabilitiesDefaultPaths = []string{"/usr/bin", "/usr/sbin", "/usr/local/bin"}

type CapabilitiesCollector struct{}

func NewCapabilitiesCollector() *CapabilitiesCollector { return &CapabilitiesCollector{} }

func (c *CapabilitiesCollector) Domain() string { return "capabilities" }

func (c *CapabilitiesCollector) Interval() time.Duration { return 0 }

// FileCapability is one `getcap` result line.
type FileCapability struct {
	Path         string `json:"path"`
	Capabilities string `json:"capabilities"`
}

func (c *CapabilitiesCollector) Collect(ctx context.Context) (Facts, error) {
	var results []FileCapability
	for _, path := range capabilitiesDefaultPaths {
		out, err := exec.CommandContext(ctx, "getcap", "-r", path).Output()
		var execErr *exec.Error
		switch {
		case err == nil:
			results = append(results, parseGetcapOutput(string(out))...)
		case errors.As(err, &execErr):
			// getcap (libcap2-bin/libcap) not installed — an honest gap
			return Facts{"installed": false}, nil
		default:
			return nil, err
		}
	}
	return Facts{"installed": true, "capabilities": results}, nil
}

// parseGetcapOutput parses "<path> = <cap spec>" rows — getcap separates
// path and capability spec with " = ", not arbitrary whitespace, since a
// capability spec can itself contain spaces.
func parseGetcapOutput(output string) []FileCapability {
	var results []FileCapability
	scanner := bufio.NewScanner(strings.NewReader(output))
	for scanner.Scan() {
		line := scanner.Text()
		idx := strings.Index(line, " = ")
		if idx == -1 {
			continue
		}
		results = append(results, FileCapability{
			Path:         strings.TrimSpace(line[:idx]),
			Capabilities: strings.TrimSpace(line[idx+3:]),
		})
	}
	return results
}
