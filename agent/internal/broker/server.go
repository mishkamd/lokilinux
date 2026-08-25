// Package broker implements loki-agent-exec: a root daemon that executes
// allowlisted privileged operations on behalf of the (non-root) agent over a
// Unix domain socket with SO_PEERCRED authentication.
//
// Security model (docs/security/EXECUTION_MODEL.md §broker):
//   - Socket /run/lokilinux/exec.sock, mode 0770 root:loki-agent.
//   - Every connection: peer UID must equal the configured agent UID.
//   - Requests are strictly-typed JSON with an operation ALLOWLIST that maps
//     onto the agent's existing executor modules (no arbitrary exec).
//   - Output capped, per-request timeout, audit line per request (no payload).
//
// Honest limitation: SO_PEERCRED authenticates the PEER USER, not the peer
// process. A attacker already running as loki-agent can open the socket too;
// the broker raises the bar (structured schema, allowlist, audit) but the
// definitive boundary for that threat remains the signed-job gate upstream.
package broker

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net"

	"github.com/lokilinux/agent/internal/modules"
)

const (
	maxRequestBytes  = 2 << 20 // 2 MiB — largest legit op is an ansible playbook ≤1MB
	maxOutputPerCall = 4 << 20 // mirrors executors' cap
	defaultTimeout   = 3600
)

type Request struct {
	RequestID  string                 `json:"request_id"`
	JobID      string                 `json:"job_id"`
	Operation  string                 `json:"operation"`
	Arguments  map[string]interface{} `json:"arguments"`
	TimeoutSec int                    `json:"timeout_sec,omitempty"`
}

type Response struct {
	RequestID string `json:"request_id"`
	OK        bool   `json:"ok"`
	ExitCode  int    `json:"exit_code,omitempty"`
	Stdout    string `json:"stdout,omitempty"`
	Stderr    string `json:"stderr,omitempty"`
	Error     string `json:"error,omitempty"`
}

func decodeRequest(r *bufio.Reader) (*Request, error) {
	var raw json.RawMessage
	dec := json.NewDecoder(r) // stream-limited by conn deadline + bufio size below
	if err := dec.Decode(&raw); err != nil {
		return nil, fmt.Errorf("invalid json: %w", err)
	}
	if len(raw) > maxRequestBytes {
		return nil, fmt.Errorf("request exceeds %d bytes", maxRequestBytes)
	}
	var req Request
	if err := json.Unmarshal(raw, &req); err != nil {
		return nil, fmt.Errorf("schema: %w", err)
	}
	if req.RequestID == "" || req.Operation == "" {
		return nil, fmt.Errorf("request_id and operation are required")
	}
	if len(req.Arguments) > 64 {
		return nil, fmt.Errorf("too many argument keys")
	}
	return &req, nil
}

// ServeConn handles one authenticated connection (NDJSON: one request per line).
func ServeConn(conn net.Conn, peerUID int, allowedUID int, log Logger) {
	defer conn.Close()
	if peerUID != allowedUID {
		writeResp(conn, Response{Error: "peer uid not permitted"})
		log.Audit("denied_peer_uid", "", peerUID, -1, 0)
		metricsDenied("peer_uid")
		return
	}
	reader := bufio.NewReaderSize(conn, maxRequestBytes)
	for {
		req, err := decodeRequest(reader)
		if err != nil {
			writeResp(conn, Response{Error: fmt.Sprintf("rejected [bad_request]: %v", err)})
			log.Audit("rejected_bad_request", "", peerUID, -1, 0)
			metricsDenied("bad_request")
			return // protocol error kills the connection
		}
		res := Execute(req)
		resp := Response{
			RequestID: req.RequestID,
			OK:        res.ExitCode == 0 && res.Error == "",
			ExitCode:  res.ExitCode,
			Stdout:    res.Stdout,
			Stderr:    res.Stderr,
			Error:     res.Error,
		}
		writeResp(conn, resp)
		log.Audit(req.Operation, req.JobID, peerUID, res.ExitCode, int(res.DurationMs))
	}
}

func writeResp(conn net.Conn, r Response) {
	b, _ := json.Marshal(r)
	b = append(b, '\n')
	_, _ = conn.Write(b)
}

var _ = modules.NewJobExecutor // keep import until operations.go lands (same package set)
