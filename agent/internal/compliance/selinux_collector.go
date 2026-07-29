package compliance

import (
	"bufio"
	"context"
	"errors"
	"io"
	"os"
	"os/exec"
	"strings"
	"time"
)

// SELinuxCollector reports the live enforcement mode via `getenforce`
// (what the kernel is actually doing right now) alongside the *configured*
// mode from /etc/selinux/config (what it will be after next boot) — these
// can disagree if an admin ran `setenforce` without editing the config, and
// a rule may care about either one.
//
// On Debian-family hosts SELinux is typically absent entirely; this
// reports mode="not_applicable" rather than fabricating "Disabled", per
// docs/compliance/03-AGENT-PLUGIN-SDK.md's per-distro table.
type SELinuxCollector struct{}

func NewSELinuxCollector() *SELinuxCollector { return &SELinuxCollector{} }

func (c *SELinuxCollector) Domain() string { return "selinux" }

func (c *SELinuxCollector) Interval() time.Duration { return 0 }

func (c *SELinuxCollector) Collect(ctx context.Context) (Facts, error) {
	facts := Facts{}

	out, err := exec.CommandContext(ctx, "getenforce").Output()
	var execErr *exec.Error
	switch {
	case err == nil:
		facts["mode"] = strings.TrimSpace(string(out))
	case errors.As(err, &execErr):
		facts["mode"] = "not_applicable"
	default:
		return nil, err
	}

	if f, err := os.Open("/etc/selinux/config"); err == nil {
		defer f.Close()
		for k, v := range parseSelinuxConfig(f) {
			facts["configured_"+strings.ToLower(k)] = v
		}
	}

	return facts, nil
}

// parseSelinuxConfig parses the simple KEY=value (ini-like, # comments)
// format of /etc/selinux/config. Takes an io.Reader for testability.
func parseSelinuxConfig(r io.Reader) map[string]string {
	values := map[string]string{}
	scanner := bufio.NewScanner(r)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		idx := strings.Index(line, "=")
		if idx == -1 {
			continue
		}
		key := strings.TrimSpace(line[:idx])
		value := strings.TrimSpace(line[idx+1:])
		values[key] = value
	}
	return values
}
