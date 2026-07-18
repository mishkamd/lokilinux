// Hand-written gRPC client stubs for lokilinux.proto services.
// ponytail: replace with protoc-generated output once protoc is available.
package lokilinux

import (
	"context"

	"google.golang.org/grpc"
)

// ─── AgentService client ──────────────────────────────────────────────────────

// AgentServiceClient is the client API for AgentService (agent → control plane).
type AgentServiceClient interface {
	// Bidirectional stream: agent sends heartbeats, server sends back commands.
	HeartbeatStream(ctx context.Context, opts ...grpc.CallOption) (AgentService_HeartbeatStreamClient, error)
	// Agent streams metrics in bulk; server acknowledges.
	ReportMetrics(ctx context.Context, opts ...grpc.CallOption) (AgentService_ReportMetricsClient, error)
	// Agent pulls latest policy configuration.
	SyncPolicy(ctx context.Context, in *PolicySyncRequest, opts ...grpc.CallOption) (*PolicyConfig, error)
}

type agentServiceClient struct{ cc grpc.ClientConnInterface }

// NewAgentServiceClient returns a new AgentServiceClient backed by cc.
func NewAgentServiceClient(cc grpc.ClientConnInterface) AgentServiceClient {
	return &agentServiceClient{cc}
}

// ── HeartbeatStream (bidirectional) ──────────────────────────────────────────

type AgentService_HeartbeatStreamClient interface {
	Send(*AgentHeartbeatRequest) error
	Recv() (*AgentHeartbeatResponse, error)
	grpc.ClientStream
}

type agentServiceHeartbeatStreamClient struct{ grpc.ClientStream }

func (x *agentServiceHeartbeatStreamClient) Send(m *AgentHeartbeatRequest) error {
	return x.ClientStream.SendMsg(m)
}

func (x *agentServiceHeartbeatStreamClient) Recv() (*AgentHeartbeatResponse, error) {
	m := new(AgentHeartbeatResponse)
	if err := x.ClientStream.RecvMsg(m); err != nil {
		return nil, err
	}
	return m, nil
}

func (c *agentServiceClient) HeartbeatStream(ctx context.Context, opts ...grpc.CallOption) (AgentService_HeartbeatStreamClient, error) {
	stream, err := c.cc.NewStream(ctx,
		&grpc.StreamDesc{ServerStreams: true, ClientStreams: true},
		"/lokilinux.AgentService/HeartbeatStream", opts...)
	if err != nil {
		return nil, err
	}
	return &agentServiceHeartbeatStreamClient{stream}, nil
}

// ── ReportMetrics (client streaming) ─────────────────────────────────────────

type AgentService_ReportMetricsClient interface {
	Send(*MetricsData) error
	CloseAndRecv() (*MetricsAck, error)
	grpc.ClientStream
}

type agentServiceReportMetricsClient struct{ grpc.ClientStream }

func (x *agentServiceReportMetricsClient) Send(m *MetricsData) error {
	return x.ClientStream.SendMsg(m)
}

func (x *agentServiceReportMetricsClient) CloseAndRecv() (*MetricsAck, error) {
	if err := x.ClientStream.CloseSend(); err != nil {
		return nil, err
	}
	m := new(MetricsAck)
	if err := x.ClientStream.RecvMsg(m); err != nil {
		return nil, err
	}
	return m, nil
}

func (c *agentServiceClient) ReportMetrics(ctx context.Context, opts ...grpc.CallOption) (AgentService_ReportMetricsClient, error) {
	stream, err := c.cc.NewStream(ctx,
		&grpc.StreamDesc{ClientStreams: true},
		"/lokilinux.AgentService/ReportMetrics", opts...)
	if err != nil {
		return nil, err
	}
	return &agentServiceReportMetricsClient{stream}, nil
}

// ── SyncPolicy (unary) ───────────────────────────────────────────────────────

func (c *agentServiceClient) SyncPolicy(ctx context.Context, in *PolicySyncRequest, opts ...grpc.CallOption) (*PolicyConfig, error) {
	out := new(PolicyConfig)
	if err := c.cc.Invoke(ctx, "/lokilinux.AgentService/SyncPolicy", in, out, opts...); err != nil {
		return nil, err
	}
	return out, nil
}
