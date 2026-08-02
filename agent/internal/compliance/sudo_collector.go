package compliance

import (
	"bufio"
	"context"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// SudoCollector reads /etc/sudoers and /etc/sudoers.d/* directly rather
// than shelling to `visudo -c` (which only validates syntax, printing
// nothing useful to parse) or `sudo -l` (which reports the *caller's*
// permissions, not the fleet-wide ruleset).
//
// ponytail: sudoers has a real grammar (aliases, Defaults, digest specs,
// includedir recursion) that a full parser would need to handle correctly.
// This collector returns trimmed, comment-stripped, non-blank raw lines
// per source file instead of a semantic parse — good enough for rules like
// "no NOPASSWD: ALL line exists" via CEL's string matching, and honest
// about not attempting alias resolution. Upgrade to a real grammar parser
// if a rule needs it (e.g. resolving a Host_Alias before matching).
type SudoCollector struct{}

func NewSudoCollector() *SudoCollector { return &SudoCollector{} }

func (c *SudoCollector) Domain() string { return "sudo" }

func (c *SudoCollector) Interval() time.Duration { return 0 }

func (c *SudoCollector) Collect(ctx context.Context) (Facts, error) {
	facts := Facts{}

	if lines, err := readSudoersLines("/etc/sudoers"); err == nil {
		facts["sudoers"] = lines
	}

	dirEntries, err := os.ReadDir("/etc/sudoers.d")
	if err == nil {
		included := map[string][]string{}
		for _, entry := range dirEntries {
			if entry.IsDir() {
				continue
			}
			path := filepath.Join("/etc/sudoers.d", entry.Name())
			lines, err := readSudoersLines(path)
			if err != nil {
				continue // unreadable file (permissions) — skip, don't fail the whole collector
			}
			included[entry.Name()] = lines
		}
		if len(included) > 0 {
			facts["sudoers_d"] = included
		}
	}

	return facts, nil
}

func readSudoersLines(path string) ([]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	return parseSudoersFile(f), nil
}

// parseSudoersFile strips comments and blank lines, returning meaningful
// directive lines in file order. Takes a reader (not a path) for testability.
func parseSudoersFile(r io.Reader) []string {
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
