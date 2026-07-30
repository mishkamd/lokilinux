package compliance

import (
	"context"
	"encoding/hex"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"lukechampine.com/blake3"
)

// ProcessesCollector snapshots running processes from /proc. Cmdline
// arguments are hashed (BLAKE3), never sent as plaintext — arguments
// commonly carry secrets (--password=..., API tokens) that must never
// leave the host even inside an otherwise-trusted compliance payload.
type ProcessesCollector struct{}

func NewProcessesCollector() *ProcessesCollector { return &ProcessesCollector{} }

func (c *ProcessesCollector) Domain() string { return "processes" }

func (c *ProcessesCollector) Interval() time.Duration { return 0 }

// ProcessFacts is one /proc/<pid> snapshot.
type ProcessFacts struct {
	PID         int    `json:"pid"`
	Name        string `json:"name"`
	UID         int    `json:"uid"`
	CmdlineHash string `json:"cmdline_hash,omitempty"`
}

func (c *ProcessesCollector) Collect(ctx context.Context) (Facts, error) {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return nil, err
	}

	var processes []ProcessFacts
	for _, entry := range entries {
		pid, err := strconv.Atoi(entry.Name())
		if err != nil {
			continue // not a PID directory (e.g. "self", "net")
		}
		proc, ok := readProcessFacts(pid)
		if !ok {
			continue // process exited between readdir and read — not an error
		}
		processes = append(processes, proc)
	}

	return Facts{"processes": processes}, nil
}

// readProcessFacts reads comm/status/cmdline directly rather than parsing
// /proc/<pid>/stat's parenthesized comm field, which can itself contain
// spaces or parens and complicate splitting the fixed-format stat line.
func readProcessFacts(pid int) (ProcessFacts, bool) {
	base := filepath.Join("/proc", strconv.Itoa(pid))

	name, err := os.ReadFile(filepath.Join(base, "comm"))
	if err != nil {
		return ProcessFacts{}, false
	}

	proc := ProcessFacts{PID: pid, Name: strings.TrimSpace(string(name))}

	if status, err := os.ReadFile(filepath.Join(base, "status")); err == nil {
		proc.UID = parseStatusUID(string(status))
	}

	if cmdline, err := os.ReadFile(filepath.Join(base, "cmdline")); err == nil && len(cmdline) > 0 {
		sum := blake3.Sum256(cmdline)
		proc.CmdlineHash = hex.EncodeToString(sum[:])
	}

	return proc, true
}

// parseStatusUID extracts the real UID (first of four values on the
// "Uid:" line: real, effective, saved, filesystem).
func parseStatusUID(status string) int {
	for _, line := range strings.Split(status, "\n") {
		if !strings.HasPrefix(line, "Uid:") {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) < 2 {
			return 0
		}
		uid, _ := strconv.Atoi(fields[1])
		return uid
	}
	return 0
}
