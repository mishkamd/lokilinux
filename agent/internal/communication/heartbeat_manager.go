package communication

import (
	"context"
	"log/slog"
	"time"

	gen "github.com/lokilinux/agent/gen/lokilinux"
)

// HeartbeatSender builds typed heartbeat requests and processes responses.
// Implemented by the agent manager; keeps HeartbeatManager decoupled from modules.
type HeartbeatSender interface {
	BuildRequest() (*gen.AgentHeartbeatRequest, error)
	HandleResponse(*gen.AgentHeartbeatResponse)
}

// HeartbeatManager drives the heartbeat loop using a fully-typed gRPC stream.
// ponytail: wired into AgentManager in Val 3; standalone for now.
type HeartbeatManager struct {
	client   *GRPCClient
	sender   HeartbeatSender
	interval time.Duration
}

func NewHeartbeatManager(client *GRPCClient, sender HeartbeatSender, interval time.Duration) *HeartbeatManager {
	return &HeartbeatManager{client: client, sender: sender, interval: interval}
}

// Run drives the heartbeat loop until ctx is cancelled.
func (h *HeartbeatManager) Run(ctx context.Context) {
	ticker := time.NewTicker(h.interval)
	defer ticker.Stop()
	h.beat(ctx)
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			h.beat(ctx)
		}
	}
}

func (h *HeartbeatManager) beat(ctx context.Context) {
	req, err := h.sender.BuildRequest()
	if err != nil {
		slog.Error("heartbeat build failed", "error", err)
		return
	}

	stream, err := h.client.HeartbeatStream(ctx)
	if err != nil {
		slog.Error("heartbeat stream open failed", "error", err)
		return
	}
	if err := stream.Send(req); err != nil {
		slog.Error("heartbeat send failed", "error", err)
		return
	}
	if err := stream.CloseSend(); err != nil {
		slog.Error("heartbeat close-send failed", "error", err)
		return
	}

	resp, err := stream.Recv()
	if err != nil {
		slog.Error("heartbeat recv failed", "error", err)
		return
	}

	h.sender.HandleResponse(resp)
	slog.Debug("heartbeat sent", "agent_id", req.AgentId)
}
