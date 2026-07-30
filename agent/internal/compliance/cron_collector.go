package compliance

import (
	"bufio"
	"context"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// CronCollector covers both classic cron (/etc/crontab, /etc/cron.d/*, the
// run-parts directories) and systemd timers — modern distros increasingly
// schedule work via timers instead of cron, so a rule checking "is there a
// scheduled backup job" needs visibility into both mechanisms.
//
// ponytail: per-user `crontab -l` isn't read — that needs iterating every
// account and running as each user, a much bigger jump in complexity than
// the system-wide files below cover. Add it if a rule needs per-user cron
// visibility specifically.
type CronCollector struct{}

func NewCronCollector() *CronCollector { return &CronCollector{} }

func (c *CronCollector) Domain() string { return "cron" }

func (c *CronCollector) Interval() time.Duration { return 0 }

func (c *CronCollector) Collect(ctx context.Context) (Facts, error) {
	facts := Facts{}

	if f, err := os.Open("/etc/crontab"); err == nil {
		facts["crontab"] = parseCronFileLines(f)
		f.Close()
	}

	if entries, err := os.ReadDir("/etc/cron.d"); err == nil {
		cronD := map[string][]string{}
		for _, entry := range entries {
			if entry.IsDir() {
				continue
			}
			f, err := os.Open(filepath.Join("/etc/cron.d", entry.Name()))
			if err != nil {
				continue // unreadable — skip, don't fail the whole collector
			}
			cronD[entry.Name()] = parseCronFileLines(f)
			f.Close()
		}
		if len(cronD) > 0 {
			facts["cron_d"] = cronD
		}
	}

	for _, dir := range []string{"hourly", "daily", "weekly", "monthly"} {
		entries, err := os.ReadDir("/etc/cron." + dir)
		if err != nil {
			continue
		}
		var names []string
		for _, entry := range entries {
			names = append(names, entry.Name())
		}
		if len(names) > 0 {
			facts["cron_"+dir] = names
		}
	}

	out, err := exec.CommandContext(ctx, "systemctl", "list-timers", "--all", "--no-legend").Output()
	var execErr *exec.Error
	switch {
	case err == nil:
		facts["timers"] = parseCronFileLines(strings.NewReader(string(out)))
	case errors.As(err, &execErr):
		// no systemd on this host — cron-only, an honest gap not a failure
	default:
		return nil, err
	}

	return facts, nil
}

// parseCronFileLines strips comments and blank lines, returning meaningful
// lines in file order. Takes a reader for testability; also reused by
// systemd_services_collector.go (drop-in override files) and
// repositories_collector.go (repo file dumps) — same "raw non-comment
// lines" shape all three need.
func parseCronFileLines(r io.Reader) []string {
	var lines []string
	scanner := bufio.NewScanner(r)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		lines = append(lines, line)
	}
	return lines
}
