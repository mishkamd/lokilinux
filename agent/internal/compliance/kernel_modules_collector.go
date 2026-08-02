package compliance

import (
	"bufio"
	"context"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// KernelModulesCollector reports currently loaded modules (`lsmod`) plus
// modules explicitly blacklisted via /etc/modprobe.d/*.conf — a rule like
// "cramfs must be blacklisted" needs the config intent, not just current
// load state, since a blacklisted module can still show loaded if it was
// loaded before the blacklist was added and the host hasn't rebooted.
type KernelModulesCollector struct{}

func NewKernelModulesCollector() *KernelModulesCollector { return &KernelModulesCollector{} }

func (c *KernelModulesCollector) Domain() string { return "kernel_modules" }

func (c *KernelModulesCollector) Interval() time.Duration { return 0 }

func (c *KernelModulesCollector) Collect(ctx context.Context) (Facts, error) {
	out, err := exec.CommandContext(ctx, "lsmod").Output()
	if err != nil {
		return nil, err
	}

	facts := Facts{"loaded": parseLsmod(string(out))}

	confs, _ := filepath.Glob("/etc/modprobe.d/*.conf")
	var blacklisted []string
	for _, path := range confs {
		f, err := os.Open(path)
		if err != nil {
			continue
		}
		blacklisted = append(blacklisted, parseModprobeBlacklist(f)...)
		f.Close()
	}
	if len(blacklisted) > 0 {
		facts["blacklisted"] = blacklisted
	}

	return facts, nil
}

// parseLsmod skips lsmod's header row and returns just the module names
// (first column) — size and refcount columns aren't compliance-relevant.
func parseLsmod(output string) []string {
	var modules []string
	scanner := bufio.NewScanner(strings.NewReader(output))
	first := true
	for scanner.Scan() {
		if first {
			first = false
			continue // "Module Size Used by" header
		}
		fields := strings.Fields(scanner.Text())
		if len(fields) == 0 {
			continue
		}
		modules = append(modules, fields[0])
	}
	return modules
}

// parseModprobeBlacklist extracts module names from "blacklist <name>"
// directives, ignoring "install"/"options"/other modprobe.d directives.
func parseModprobeBlacklist(r io.Reader) []string {
	var names []string
	scanner := bufio.NewScanner(r)
	for scanner.Scan() {
		fields := strings.Fields(strings.TrimSpace(scanner.Text()))
		if len(fields) == 2 && fields[0] == "blacklist" {
			names = append(names, fields[1])
		}
	}
	return names
}
