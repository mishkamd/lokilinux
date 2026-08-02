package compliance

import (
	"bufio"
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// SystemdServicesCollector reports every unit file's enabled/disabled
// state plus any admin drop-in overrides — a service can be "enabled" in
// the unit file yet fully overridden by a *.conf under a `<unit>.d/`
// directory, which rules need visibility into separately.
type SystemdServicesCollector struct{}

func NewSystemdServicesCollector() *SystemdServicesCollector { return &SystemdServicesCollector{} }

func (c *SystemdServicesCollector) Domain() string { return "systemd_services" }

func (c *SystemdServicesCollector) Interval() time.Duration { return 0 }

// UnitFile is one line of `systemctl list-unit-files` output.
type UnitFile struct {
	Unit  string `json:"unit"`
	State string `json:"state"`
}

func (c *SystemdServicesCollector) Collect(ctx context.Context) (Facts, error) {
	facts := Facts{}

	out, err := exec.CommandContext(ctx, "systemctl", "list-unit-files", "--no-legend").Output()
	if err != nil {
		return nil, err
	}
	facts["unit_files"] = parseUnitFiles(string(out))

	overrides := map[string][]string{}
	dirs, _ := filepath.Glob("/etc/systemd/system/*.d")
	for _, dir := range dirs {
		unit := strings.TrimSuffix(filepath.Base(dir), ".d")
		confs, _ := filepath.Glob(filepath.Join(dir, "*.conf"))
		var lines []string
		for _, confPath := range confs {
			f, err := os.Open(confPath)
			if err != nil {
				continue
			}
			lines = append(lines, parseCronFileLines(f)...)
			f.Close()
		}
		if len(lines) > 0 {
			overrides[unit] = lines
		}
	}
	if len(overrides) > 0 {
		facts["overrides"] = overrides
	}

	return facts, nil
}

// parseUnitFiles parses "unit_name    state" rows (whitespace-separated,
// exactly the two columns --no-legend leaves).
func parseUnitFiles(output string) []UnitFile {
	var units []UnitFile
	scanner := bufio.NewScanner(strings.NewReader(output))
	for scanner.Scan() {
		fields := strings.Fields(scanner.Text())
		if len(fields) < 2 {
			continue
		}
		units = append(units, UnitFile{Unit: fields[0], State: fields[1]})
	}
	return units
}
