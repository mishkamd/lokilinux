package modules

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// AnsibleExecutor runs a playbook locally against this host
// (ansible-playbook --connection=local) — no SSH, no remote inventory.
// Playbook content and extra_vars arrive as data (not shell text), so they
// are written to files and passed to ansible-playbook via argv, never
// interpolated into a shell string. Unlike JobExecutor.Execute, which runs
// arbitrary shell commands, playbook/extra_vars content here is untrusted
// user YAML/JSON and must never pass through /bin/sh -c.
type AnsibleExecutor struct {
	maxOutputBytes int
	binary         string
}

func NewAnsibleExecutor() *AnsibleExecutor {
	return &AnsibleExecutor{maxOutputBytes: 4 * 1024 * 1024, binary: "ansible-playbook"}
}

// ansibleTmpBase is a real (non-PrivateTmp) directory: the playbook actually
// runs via systemd-run in a transient unit outside the agent's namespace
// (see systemd_run.go), so staging it under the default os.TempDir() (/tmp,
// virtualized per-service by PrivateTmp=true) would write it somewhere that
// transient unit can never see. /var/lib/lokilinux is already writable by
// the agent's own sandbox and is a real host path.
const ansibleTmpBase = "/var/lib/lokilinux/ansible-tmp"

// maxPlaybookBytes (plan P7) — cumulative cap over the playbook plus every
// role file's content, checked before any os.WriteFile so an oversized
// payload never touches disk at all.
const maxPlaybookBytes = 1 * 1024 * 1024

// rolesTotalSize sums the byte length of every role file's content —
// mirrors writeRoles' own type-asserting walk so the size check sees
// exactly what would actually get written.
func rolesTotalSize(roles map[string]any) int {
	total := 0
	for _, filesAny := range roles {
		files, ok := filesAny.(map[string]any)
		if !ok {
			continue
		}
		for _, contentAny := range files {
			if content, ok := contentAny.(string); ok {
				total += len(content)
			}
		}
	}
	return total
}

// writeRoles materializes roles under dir/roles/<name>/<relpath>.
// roles maps role name → {relative path → file content}. Paths are
// validated against traversal: the backend validates on write, but the
// agent must not trust job payloads blindly (defense in depth — a
// compromised control plane must not get arbitrary file writes here).
func writeRoles(dir string, roles map[string]any) error {
	for roleName, filesAny := range roles {
		if roleName == "" || strings.Contains(roleName, "/") || strings.Contains(roleName, "..") {
			return fmt.Errorf("invalid role name %q", roleName)
		}
		files, ok := filesAny.(map[string]any)
		if !ok {
			continue
		}
		for relPath, contentAny := range files {
			content, ok := contentAny.(string)
			if !ok {
				continue
			}
			if relPath == "" || filepath.IsAbs(relPath) {
				return fmt.Errorf("invalid role file path %q", relPath)
			}
			cleaned := filepath.Clean(relPath)
			if strings.HasPrefix(cleaned, "..") {
				return fmt.Errorf("path traversal in role file %q", relPath)
			}
			full := filepath.Join(dir, "roles", roleName, cleaned)
			if err := os.MkdirAll(filepath.Dir(full), 0700); err != nil {
				return err
			}
			if err := os.WriteFile(full, []byte(content), 0600); err != nil {
				return err
			}
		}
	}
	return nil
}

// Execute writes playbookContent, extraVars and roles to a temp dir and
// runs ansible-playbook against localhost with connection=local. Roles are
// written under <dir>/roles/, where ansible resolves them automatically
// (adjacent to the playbook). checkMode adds ansible's own --check --diff
// (dry-run: report what would change, apply nothing) — the ansible half of
// remediation dry-run (docs/compliance §13, §14); real ansible-core
// functionality, not an agent-side stand-in.
func (e *AnsibleExecutor) Execute(ctx context.Context, jobID, playbookContent string, extraVars map[string]any, roles map[string]any, timeoutSec int, checkMode bool) JobResult {
	start := time.Now()

	if total := len(playbookContent) + rolesTotalSize(roles); total > maxPlaybookBytes {
		return JobResult{
			JobID: jobID, ExitCode: 1,
			Error:      fmt.Sprintf("playbook+roles size %d exceeds %d byte cap", total, maxPlaybookBytes),
			DurationMs: msSince(start),
		}
	}

	if _, err := exec.LookPath(e.binary); err != nil {
		return JobResult{
			JobID: jobID, ExitCode: 1,
			Error:      "ansible-core not installed on target (ansible-playbook not found in PATH)",
			DurationMs: msSince(start),
		}
	}

	if err := os.MkdirAll(ansibleTmpBase, 0700); err != nil {
		return JobResult{JobID: jobID, ExitCode: 1, Error: err.Error(), DurationMs: msSince(start)}
	}
	dir, err := os.MkdirTemp(ansibleTmpBase, "job-"+jobID+"-")
	if err != nil {
		return JobResult{JobID: jobID, ExitCode: 1, Error: err.Error(), DurationMs: msSince(start)}
	}
	defer os.RemoveAll(dir)

	playbookPath := filepath.Join(dir, "playbook.yml")
	if err := os.WriteFile(playbookPath, []byte(playbookContent), 0600); err != nil {
		return JobResult{JobID: jobID, ExitCode: 1, Error: err.Error(), DurationMs: msSince(start)}
	}

	if len(roles) > 0 {
		if err := writeRoles(dir, roles); err != nil {
			return JobResult{JobID: jobID, ExitCode: 1, Error: err.Error(), DurationMs: msSince(start)}
		}
	}

	extraVarsPath := filepath.Join(dir, "extravars.json")
	extraVarsJSON, err := json.Marshal(extraVars)
	if err != nil {
		return JobResult{JobID: jobID, ExitCode: 1, Error: err.Error(), DurationMs: msSince(start)}
	}
	if err := os.WriteFile(extraVarsPath, extraVarsJSON, 0600); err != nil {
		return JobResult{JobID: jobID, ExitCode: 1, Error: err.Error(), DurationMs: msSince(start)}
	}

	// argv array — no shell, so playbook/extra_vars content can't break out
	// of a command string regardless of what it contains. Escapes the
	// agent's own sandbox via systemd-run (see systemd_run.go): the
	// playbook's whole point is mutating the host, which ProtectSystem=strict
	// forbids from inside the agent's own namespace. WorkingDirectory=dir
	// keeps roles/ resolving next to the playbook, same as cmd.Dir did.
	argv := []string{e.binary,
		"-i", "localhost,",
		"-c", "local",
		"-e", "@" + extraVarsPath,
	}
	if checkMode {
		argv = append(argv, "--check", "--diff")
	}
	argv = append(argv, playbookPath)
	result := runViaSystemdRunArgv(ctx, jobID, argv, dir, timeoutSec, e.maxOutputBytes, &ProfileArbitraryCode)
	result.DurationMs = msSince(start)
	return result
}
