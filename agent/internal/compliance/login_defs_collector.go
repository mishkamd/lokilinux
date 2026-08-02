package compliance

import (
	"bufio"
	"context"
	"io"
	"os"
	"strings"
	"time"
)

// LoginDefsCollector reads /etc/login.defs. The fields most compliance
// rules ask about (PASS_MAX_DAYS, PASS_MIN_LEN, UMASK, ENCRYPT_METHOD) are
// simple KEY value pairs, whitespace-separated rather than "="-separated
// like most other config files this package reads.
type LoginDefsCollector struct{}

func NewLoginDefsCollector() *LoginDefsCollector { return &LoginDefsCollector{} }

func (c *LoginDefsCollector) Domain() string { return "login_defs" }

func (c *LoginDefsCollector) Interval() time.Duration { return 0 }

func (c *LoginDefsCollector) Collect(ctx context.Context) (Facts, error) {
	f, err := os.Open("/etc/login.defs")
	if err != nil {
		return nil, err
	}
	defer f.Close()
	return parseLoginDefs(f), nil
}

// parseLoginDefs takes an io.Reader for testability. Format: "KEY value"
// per line, fields whitespace-separated, "#" comments, blank lines ignored.
func parseLoginDefs(r io.Reader) Facts {
	facts := Facts{}
	scanner := bufio.NewScanner(r)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		facts[fields[0]] = strings.Join(fields[1:], " ")
	}
	return facts
}
