package compliance

import (
	"context"
	"os"
	"path/filepath"
	"time"
)

// RepositoriesCollector reads package repository definitions —
// /etc/yum.repos.d/*.repo (RHEL-family) or /etc/apt/sources.list plus
// /etc/apt/sources.list.d/*.list (Debian-family). Raw file contents per
// file, matching the sudoers_d/cron_d pattern elsewhere in this package —
// a rule checking "no untrusted third-party repo configured" can
// string-match the raw dump rather than needing a full .repo/.list
// grammar parser.
//
// ponytail: the newer deb822-style *.sources format (single-file, RFC822
// syntax) isn't read separately — it's rare enough on managed fleets today
// that adding a second Debian repo format is premature. Add a *.sources
// glob here if that changes.
type RepositoriesCollector struct{}

func NewRepositoriesCollector() *RepositoriesCollector { return &RepositoriesCollector{} }

func (c *RepositoriesCollector) Domain() string { return "repositories" }

func (c *RepositoriesCollector) Interval() time.Duration { return 0 }

func (c *RepositoriesCollector) Collect(ctx context.Context) (Facts, error) {
	facts := Facts{}

	if repos := readReposByGlob("/etc/yum.repos.d/*.repo"); len(repos) > 0 {
		facts["yum_repos"] = repos
	}

	aptSources := map[string][]string{}
	if lines := readLinesIfExists("/etc/apt/sources.list"); len(lines) > 0 {
		aptSources["sources.list"] = lines
	}
	for name, lines := range readReposByGlob("/etc/apt/sources.list.d/*.list") {
		aptSources[name] = lines
	}
	if len(aptSources) > 0 {
		facts["apt_sources"] = aptSources
	}

	return facts, nil
}

func readLinesIfExists(path string) []string {
	f, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer f.Close()
	return parseCronFileLines(f)
}

func readReposByGlob(pattern string) map[string][]string {
	matches, _ := filepath.Glob(pattern)
	result := map[string][]string{}
	for _, path := range matches {
		if lines := readLinesIfExists(path); len(lines) > 0 {
			result[filepath.Base(path)] = lines
		}
	}
	return result
}
