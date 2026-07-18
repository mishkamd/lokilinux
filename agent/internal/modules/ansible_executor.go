package modules

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
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
// (adjacent to the playbook).
func (e *AnsibleExecutor) Execute(ctx context.Context, jobID, playbookContent string, extraVars map[string]any, roles map[string]any, timeoutSec int) JobResult {
	start := time.Now()

	if _, err := exec.LookPath(e.binary); err != nil {
		return JobResult{
			JobID: jobID, ExitCode: 1,
			Error:      "ansible-core not installed on target (ansible-playbook not found in PATH)",
			DurationMs: msSince(start),
		}
	}

	dir, err := os.MkdirTemp("", "lokilinux-ansible-"+jobID)
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

	if timeoutSec > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, time.Duration(timeoutSec)*time.Second)
		defer cancel()
	}

	var stdout, stderr bytes.Buffer
	// argv array — no shell, so playbook/extra_vars content can't break out
	// of a command string regardless of what it contains.
	cmd := exec.CommandContext(ctx, e.binary,
		"-i", "localhost,",
		"-c", "local",
		"-e", "@"+extraVarsPath,
		playbookPath,
	)
	cmd.Dir = dir // roles/ resolves relative to the playbook dir
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		if cmd.Process != nil {
			return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
		}
		return nil
	}
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	runErr := cmd.Run()

	code := 0
	errMsg := ""
	if cmd.ProcessState != nil {
		code = cmd.ProcessState.ExitCode()
	}
	if runErr != nil && code == 0 {
		errMsg = runErr.Error()
		code = 1
	}

	return JobResult{
		JobID:      jobID,
		ExitCode:   code,
		Stdout:     truncateOutput(stdout.String(), e.maxOutputBytes),
		Stderr:     truncateOutput(stderr.String(), e.maxOutputBytes),
		DurationMs: msSince(start),
		Error:      errMsg,
	}
}
