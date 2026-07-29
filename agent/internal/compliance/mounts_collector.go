package compliance

import (
	"bufio"
	"context"
	"io"
	"os"
	"strings"
	"time"
)

// MountsCollector reads every entry in /proc/mounts, including virtual
// filesystems (tmpfs, proc, cgroup) — deliberately not reusing
// agent/internal/modules/system_info.go's real-disk-only mount filter
// (which exists for capacity reporting). A rule like "/tmp is mounted
// noexec" needs mount *options*, and /tmp is commonly tmpfs — filtering it
// out here would make that exact check impossible to express.
type MountsCollector struct{}

func NewMountsCollector() *MountsCollector { return &MountsCollector{} }

func (c *MountsCollector) Domain() string { return "mounts" }

func (c *MountsCollector) Interval() time.Duration { return 0 }

func (c *MountsCollector) Collect(ctx context.Context) (Facts, error) {
	f, err := os.Open("/proc/mounts")
	if err != nil {
		return nil, err
	}
	defer f.Close()

	return Facts{"mounts": parseProcMounts(f)}, nil
}

// Mount is one /proc/mounts entry. Options is a slice (not a raw string)
// so CEL rules can use the `in` operator directly: `"noexec" in m.options`.
type Mount struct {
	Source  string   `json:"source"`
	Target  string   `json:"target"`
	FSType  string   `json:"fstype"`
	Options []string `json:"options"`
}

// parseProcMounts takes an io.Reader so it's testable without a real
// /proc/mounts. Format: "source target fstype options dump pass", fields
// space-separated, options comma-separated (per the fstab(5)/mounts(5) format).
func parseProcMounts(r io.Reader) []Mount {
	var mounts []Mount
	scanner := bufio.NewScanner(r)
	for scanner.Scan() {
		fields := strings.Fields(scanner.Text())
		if len(fields) < 4 {
			continue
		}
		mounts = append(mounts, Mount{
			Source:  fields[0],
			Target:  fields[1],
			FSType:  fields[2],
			Options: strings.Split(fields[3], ","),
		})
	}
	return mounts
}
