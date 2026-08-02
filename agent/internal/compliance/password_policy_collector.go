package compliance

import (
	"bufio"
	"context"
	"io"
	"os"
	"strings"
	"time"
)

// PasswordPolicyCollector reads /etc/security/pwquality.conf — the same
// path on both RHEL-family (libpwquality) and Debian-family
// (libpam-pwquality) hosts per docs/compliance/03-AGENT-PLUGIN-SDK.md's
// per-distro table; only the package name differs, not the config path.
type PasswordPolicyCollector struct{}

func NewPasswordPolicyCollector() *PasswordPolicyCollector { return &PasswordPolicyCollector{} }

func (c *PasswordPolicyCollector) Domain() string { return "password_policy" }

func (c *PasswordPolicyCollector) Interval() time.Duration { return 0 }

func (c *PasswordPolicyCollector) Collect(ctx context.Context) (Facts, error) {
	f, err := os.Open("/etc/security/pwquality.conf")
	if err != nil {
		if os.IsNotExist(err) {
			return Facts{"installed": false}, nil
		}
		return nil, err
	}
	defer f.Close()
	facts := parsePwqualityConf(f)
	facts["installed"] = true
	return facts, nil
}

// parsePwqualityConf handles pwquality.conf's "option = value" lines and
// bare "option" flags with no value. Takes an io.Reader for testability.
func parsePwqualityConf(r io.Reader) Facts {
	facts := Facts{}
	scanner := bufio.NewScanner(r)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		idx := strings.Index(line, "=")
		if idx == -1 {
			facts[line] = ""
			continue
		}
		key := strings.TrimSpace(line[:idx])
		value := strings.TrimSpace(line[idx+1:])
		facts[key] = value
	}
	return facts
}
