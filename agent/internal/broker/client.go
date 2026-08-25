// Package-level client the non-root agent uses to reach loki-agent-exec.
package broker

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net"
	"time"

	"github.com/lokilinux/agent/internal/modules"
)

type Client struct {
	socketPath string
}

func NewClient(socketPath string) *Client { return &Client{socketPath: socketPath} }

// Run executes one allowlisted operation via the broker and maps the
// response onto JobResult. No local fallback: transport errors surface as
// failed jobs (plan §17 fail-closed).
func (c *Client) Run(operation, jobID string, args map[string]interface{}, timeoutSec int) modules.JobResult {
	if timeoutSec <= 0 {
		timeoutSec = defaultTimeout
	}
	conn, err := net.DialTimeout("unix", c.socketPath, 5*time.Second)
	if err != nil {
		return modules.JobResult{JobID: jobID, ExitCode: 1,
			Error: fmt.Sprintf("broker unreachable at %s: %v", c.socketPath, err)}
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(time.Duration(timeoutSec)*time.Second + 10*time.Second))

	req := Request{RequestID: fmt.Sprintf("%d", time.Now().UnixNano()), JobID: jobID,
		Operation: operation, Arguments: args, TimeoutSec: timeoutSec}
	b, _ := json.Marshal(req)
	if _, err := conn.Write(append(b, '\n')); err != nil {
		return modules.JobResult{JobID: jobID, ExitCode: 1, Error: fmt.Sprintf("broker write: %v", err)}
	}
	var resp Response
	if err := json.NewDecoder(bufio.NewReader(conn)).Decode(&resp); err != nil {
		return modules.JobResult{JobID: jobID, ExitCode: 1, Error: fmt.Sprintf("broker read: %v", err)}
	}
	out := modules.JobResult{JobID: jobID, ExitCode: resp.ExitCode, Stdout: resp.Stdout, Stderr: resp.Stderr}
	if !resp.OK && out.ExitCode == 0 {
		out.ExitCode = 1
	}
	out.Error = resp.Error
	return out
}

