package compliance

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"time"
)

// KernelCollector reports the running kernel version and the boot-time
// GRUB command line — /proc/version / `uname -r` can disagree with what
// GRUB will boot next time if a kernel update hasn't triggered a reboot
// yet, so both the live version and the configured command line are
// captured since a rule may care about either.
type KernelCollector struct{}

func NewKernelCollector() *KernelCollector { return &KernelCollector{} }

func (c *KernelCollector) Domain() string { return "kernel" }

func (c *KernelCollector) Interval() time.Duration { return 0 }

func (c *KernelCollector) Collect(ctx context.Context) (Facts, error) {
	facts := Facts{}

	out, err := exec.CommandContext(ctx, "uname", "-r").Output()
	if err != nil {
		return nil, fmt.Errorf("running uname -r: %w", err)
	}
	facts["version"] = strings.TrimSpace(string(out))

	if raw, err := os.ReadFile("/proc/version"); err == nil {
		facts["proc_version"] = strings.TrimSpace(string(raw))
	}

	// /etc/default/grub is present on both distro families in practice
	// (grub2-mkconfig reads it on RHEL too) — falling back to
	// `grub2-editenv list` only if the file is absent keeps this collector
	// simple rather than branching on distro ID.
	if f, err := os.Open("/etc/default/grub"); err == nil {
		defer f.Close()
		for k, v := range parseGrubDefault(f) {
			facts[strings.ToLower(k)] = v
		}
		return facts, nil
	}

	out, err = exec.CommandContext(ctx, "grub2-editenv", "list").Output()
	var execErr *exec.Error
	switch {
	case err == nil:
		facts["grub2_editenv"] = strings.TrimSpace(string(out))
	case errors.As(err, &execErr):
		facts["grub_config"] = "not_applicable"
	default:
		return nil, err
	}

	return facts, nil
}

// parseGrubDefault parses /etc/default/grub's KEY="value" shell-style
// assignments (quotes optional). Takes an io.Reader for testability.
func parseGrubDefault(r io.Reader) map[string]string {
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
		value := strings.Trim(strings.TrimSpace(line[idx+1:]), `"`)
		values[key] = value
	}
	return values
}
