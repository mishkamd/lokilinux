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

// PAMCollector reads every /etc/pam.d/* stack — one file per service
// (sshd, sudo, login, passwd, ...). Each stack is the ordered list of
// module lines that govern authentication for that service, which is what
// rules like "sshd requires pam_unix.so" or "no pam_permit.so anywhere"
// need to check.
type PAMCollector struct{}

func NewPAMCollector() *PAMCollector { return &PAMCollector{} }

func (c *PAMCollector) Domain() string { return "pam" }

func (c *PAMCollector) Interval() time.Duration { return 0 }

// PAMLine is one parsed line of a PAM stack file.
type PAMLine struct {
	Type    string   `json:"type"`    // auth/account/password/session
	Control string   `json:"control"` // required/requisite/sufficient/optional/include/substack, or a bracketed [..] value
	Module  string   `json:"module"`
	Args    []string `json:"args,omitempty"`
}

func (c *PAMCollector) Collect(ctx context.Context) (Facts, error) {
	entries, err := os.ReadDir("/etc/pam.d")
	if err != nil {
		return nil, err
	}

	stacks := map[string][]PAMLine{}
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		f, err := os.Open(filepath.Join("/etc/pam.d", entry.Name()))
		if err != nil {
			continue // unreadable — skip, don't fail the whole collector
		}
		stacks[entry.Name()] = parsePAMStack(f)
		f.Close()
	}

	return Facts{"pam_stacks": stacks}, nil
}

// parsePAMStack is a pure function over an io.Reader for testability.
// Handles both the plain-keyword control form ("required") and the
// bracketed form ("[success=ok default=die]") by treating a leading "["
// token as the start of a multi-token control value that runs until the
// matching "]".
func parsePAMStack(r io.Reader) []PAMLine {
	var lines []PAMLine
	scanner := bufio.NewScanner(r)
	for scanner.Scan() {
		text := strings.TrimSpace(scanner.Text())
		if text == "" || strings.HasPrefix(text, "#") {
			continue
		}
		fields := strings.Fields(text)
		if len(fields) < 3 {
			continue
		}

		line := PAMLine{Type: fields[0]}
		rest := fields[1:]

		if strings.HasPrefix(rest[0], "[") {
			control, consumed := joinBracketedControl(rest)
			line.Control = control
			rest = rest[consumed:]
		} else {
			line.Control = rest[0]
			rest = rest[1:]
		}

		if len(rest) == 0 {
			continue // malformed: no module after control
		}
		line.Module = rest[0]
		if len(rest) > 1 {
			line.Args = rest[1:]
		}
		lines = append(lines, line)
	}
	return lines
}

// joinBracketedControl reassembles "[success=ok default=die]" from its
// space-split tokens and returns how many tokens it consumed.
func joinBracketedControl(fields []string) (string, int) {
	for i, f := range fields {
		if strings.HasSuffix(f, "]") {
			return strings.Join(fields[:i+1], " "), i + 1
		}
	}
	return fields[0], 1 // unterminated bracket — degrade rather than consume everything
}
