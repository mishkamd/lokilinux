// loki-agent-exec — privileged execution broker (root daemon).
//
// Listens on a root-owned Unix socket, authenticates peers via SO_PEERCRED
// (UID must match --allowed-uid, default the loki-agent user's UID), and
// executes allowlisted operations through the agent's executor modules.
// See internal/broker for the security model.
package main

import (
	"flag"
	"log/slog"
	"net"
	"os"
	"os/user"
	"path/filepath"
	"strconv"
	"syscall"

	"github.com/lokilinux/agent/internal/broker"
)

const defaultSocketPath = "/run/lokilinux/exec.sock"

type slogAudit struct{ log *slog.Logger }

func (s slogAudit) Audit(event, jobID string, peerUID, exitCode, durationMs int) {
	s.log.Info("broker.audit", "event", event, "job_id", jobID,
		"peer_uid", peerUID, "exit_code", exitCode, "duration_ms", durationMs)
}

func main() {
	socketPath := flag.String("socket", defaultSocketPath, "unix socket path")
	agentUser := flag.String("agent-user", "loki-agent", "user allowed to connect")
	flag.Parse()

	log := slog.New(slog.NewJSONHandler(os.Stderr, nil))

	uid := -1
	if u, err := user.Lookup(*agentUser); err == nil {
		uid, _ = strconv.Atoi(u.Uid)
	} else {
		log.Warn("broker: agent user not found; allowing only numeric UID 0 owner checks disabled",
			"user", *agentUser)
	}

	if err := os.MkdirAll(filepath.Dir(*socketPath), 0o750); err != nil {
		log.Error("mkdir socket dir", "error", err)
		os.Exit(1)
	}
	_ = os.Remove(*socketPath) // stale socket from an unclean shutdown

	ln, err := net.Listen("unix", *socketPath)
	if err != nil {
		log.Error("listen", "error", err)
		os.Exit(1)
	}
	// 0770 root:loki-agent — kernel enforces group membership before our own
	// SO_PEERCRED check even runs.
	if err := os.Chmod(*socketPath, 0o770); err != nil {
		log.Error("chmod socket", "error", err)
		os.Exit(1)
	}
	if uid >= 0 {
		if g, gerr := user.LookupGroupId(strconv.Itoa(uid)); gerr == nil {
			gid, _ := strconv.Atoi(g.Gid)
			if cherr := os.Chown(*socketPath, 0, gid); cherr != nil {
				log.Warn("chown socket to agent group failed", "error", cherr)
			}
		}
	}

	log.Info("exec broker listening", "socket", *socketPath, "allowed_uid", uid)

	for {
		conn, err := ln.Accept()
		if err != nil {
			log.Error("accept", "error", err)
			continue
		}
		go handle(conn, uid, log)
	}
}

func handle(conn net.Conn, allowedUID int, log *slog.Logger) {
	unix, ok := conn.(*net.UnixConn)
	if !ok {
		conn.Close()
		return
	}
	raw, err := unix.SyscallConn()
	if err != nil {
		conn.Close()
		return
	}
	var peerUID = -1
	var credErr error
	if cerr := raw.Control(func(fd uintptr) {
		ucred, errno := syscall.GetsockoptUcred(int(fd), syscall.SOL_SOCKET, syscall.SO_PEERCRED)
		if errno != nil {
			credErr = errno
			return
		}
		peerUID = int(ucred.Uid)
	}); cerr != nil {
		conn.Close()
		return
	}
	if credErr != nil || peerUID < 0 {
		log.Warn("broker: could not read peer credentials — rejecting")
		conn.Close()
		return
	}
	broker.ServeConn(conn, peerUID, allowedUID, slogAudit{log: log})
}
