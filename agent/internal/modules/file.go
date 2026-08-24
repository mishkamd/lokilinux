package modules

import (
	"context"
	"fmt"
	"os"
	"os/user"
	"regexp"
	"strconv"
	"syscall"
	"time"
)

var fileActions = map[string]bool{
	"create": true, "template": true, "copy": true,
	"delete": true, "chmod": true, "chown": true,
}

// ownerNameRe bounds owner/group values to POSIX username/groupname charset
// before they reach exec via chown's "owner:group" argument.
var ownerNameRe = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)

func isValidOwnerName(s string) bool { return s != "" && ownerNameRe.MatchString(s) }

// File runs create/template/copy/delete/chmod/chown against a single path.
// Every mutating action still goes through systemd-run (runViaSystemdRunArgv)
// — ProtectSystem=strict makes the agent's own process read-mostly, so a
// direct os.WriteFile/os.Chmod from inside the agent can't write most real
// target paths. Idempotency checks read the current state directly first
// (reads aren't blocked the way writes are) and skip the mutation when it
// would be a no-op. Native form of the backend compile-down path's
// `file(action, ...)` — see reboot.go's docstring on why this isn't yet the
// default dispatch path.
func File(ctx context.Context, jobID string, params map[string]interface{}, timeoutSec int) JobResult {
	start := time.Now()
	fail := func(format string, a ...interface{}) JobResult {
		return JobResult{JobID: jobID, ExitCode: 1, Error: fmt.Sprintf(format, a...), DurationMs: msSince(start)}
	}
	skip := func(format string, a ...interface{}) JobResult {
		return JobResult{JobID: jobID, ExitCode: 0, Stdout: fmt.Sprintf(format, a...), DurationMs: msSince(start)}
	}

	action, _ := params["action"].(string)
	path, _ := params["path"].(string)
	if !fileActions[action] {
		return fail("unsupported file action: %q", action)
	}
	if path == "" || path[0] != '/' {
		return fail("path must be a non-empty absolute path, got %q", path)
	}

	switch action {
	case "create", "template":
		content, _ := params["content"].(string)
		mode, _ := params["mode"].(string)
		if existing, err := os.ReadFile(path); err == nil && string(existing) == content {
			if mode == "" || modeMatches(path, mode) {
				return skip("%s already has the desired content — no-op", path)
			}
		}
		argv := []string{"/bin/sh", "-c", `printf '%s' "$1" > "$2"`, "--", content, path}
		result := runViaSystemdRunArgv(ctx, jobID, argv, "", timeoutSec, 64*1024, &ProfileHostMutation)
		if result.ExitCode != 0 || mode == "" {
			return result
		}
		return runViaSystemdRunArgv(ctx, jobID+"-chmod", []string{"chmod", mode, path}, "", timeoutSec, 64*1024, &ProfileHostMutation)

	case "copy":
		source, _ := params["source"].(string)
		if source == "" {
			return fail("config.source is required for action copy")
		}
		return runViaSystemdRunArgv(ctx, jobID, []string{"cp", source, path}, "", timeoutSec, 64*1024, &ProfileHostMutation)

	case "delete":
		if _, err := os.Stat(path); os.IsNotExist(err) {
			return skip("%s already absent — no-op", path)
		}
		return runViaSystemdRunArgv(ctx, jobID, []string{"rm", "-f", path}, "", timeoutSec, 64*1024, &ProfileHostMutation)

	case "chmod":
		mode, _ := params["mode"].(string)
		if mode == "" {
			return fail("config.mode is required for action chmod")
		}
		if modeMatches(path, mode) {
			return skip("%s already has mode %s — no-op", path, mode)
		}
		return runViaSystemdRunArgv(ctx, jobID, []string{"chmod", mode, path}, "", timeoutSec, 64*1024, &ProfileHostMutation)

	case "chown":
		owner, _ := params["owner"].(string)
		group, _ := params["group"].(string)
		if owner != "" && !isValidOwnerName(owner) {
			return fail("invalid owner: %q", owner)
		}
		if group != "" && !isValidOwnerName(group) {
			return fail("invalid group: %q", group)
		}
		spec := owner
		if group != "" {
			spec = owner + ":" + group
		}
		if spec == "" {
			return fail("config.owner and/or config.group is required for action chown")
		}
		if ownerMatches(path, owner, group) {
			return skip("%s already owned by %s — no-op", path, spec)
		}
		return runViaSystemdRunArgv(ctx, jobID, []string{"chown", spec, path}, "", timeoutSec, 64*1024, &ProfileHostMutation)
	}

	return fail("unsupported file action: %q", action) // unreachable, fileActions already gated
}

// modeMatches compares the file's current permission bits against a mode
// string like "0644" — false (not a no-op) on any parse or stat failure, so
// an unreadable/nonexistent file always falls through to the real mutation.
func modeMatches(path, mode string) bool {
	wanted, err := strconv.ParseUint(mode, 8, 32)
	if err != nil {
		return false
	}
	info, err := os.Stat(path)
	if err != nil {
		return false
	}
	return uint32(info.Mode().Perm()) == uint32(wanted)
}

// ownerMatches resolves owner/group names to uid/gid and compares against
// the file's current ownership. An empty owner or group means "don't care
// about that half" — chown's own two-field spec allows setting just one.
func ownerMatches(path, owner, group string) bool {
	info, err := os.Stat(path)
	if err != nil {
		return false
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return false
	}
	if owner != "" {
		u, err := user.Lookup(owner)
		if err != nil {
			return false
		}
		if uid, _ := strconv.Atoi(u.Uid); uint32(uid) != stat.Uid {
			return false
		}
	}
	if group != "" {
		g, err := user.LookupGroup(group)
		if err != nil {
			return false
		}
		if gid, _ := strconv.Atoi(g.Gid); uint32(gid) != stat.Gid {
			return false
		}
	}
	return true
}
