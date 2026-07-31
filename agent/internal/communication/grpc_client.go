// Package communication handles transport to the LokiLinux control plane.
package communication

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"net"
	"os"
	"sync"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/encoding"
	"google.golang.org/grpc/keepalive"

	gen "github.com/lokilinux/agent/gen/lokilinux"
	"github.com/lokilinux/agent/internal/modules"
)

func init() {
	// ponytail: JSON codec overrides proto so plain Go structs work over gRPC.
	// Swap: remove this init() and gen/*.pb.go once protoc generates real types
	// and the control plane speaks binary protobuf.
	encoding.RegisterCodec(jsonCodec{})
}

type jsonCodec struct{}

func (jsonCodec) Marshal(v interface{}) ([]byte, error)      { return json.Marshal(v) }
func (jsonCodec) Unmarshal(data []byte, v interface{}) error { return json.Unmarshal(data, v) }
func (jsonCodec) Name() string                               { return "proto" }

const (
	maxMsgSize       = 16 * 1024 * 1024 // 16 MB — matches server MaxRecvMsgSize
	keepaliveTime    = 30 * time.Second
	keepaliveTimeout = 10 * time.Second
)

// GRPCClient is an mTLS gRPC client for the LokiLinux control plane.
// Connection is lazy — established on the first RPC call.
type GRPCClient struct {
	endpoint string
	certPath string
	keyPath  string
	caPath   string

	mu  sync.Mutex
	cc  *grpc.ClientConn
	svc gen.AgentServiceClient
}

// NewGRPCClient creates a client. Dial happens on first use.
func NewGRPCClient(endpoint, certPath, keyPath, caPath string) *GRPCClient {
	return &GRPCClient{
		endpoint: endpoint,
		certPath: certPath,
		keyPath:  keyPath,
		caPath:   caPath,
	}
}

// dial establishes an mTLS connection. Safe to call concurrently; dials at most once.
func (c *GRPCClient) dial() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.cc != nil {
		return nil
	}

	cert, err := tls.LoadX509KeyPair(c.certPath, c.keyPath)
	if err != nil {
		return err
	}
	ca, err := os.ReadFile(c.caPath)
	if err != nil {
		return err
	}
	pool := x509.NewCertPool()
	pool.AppendCertsFromPEM(ca)

	host, _, err := net.SplitHostPort(c.endpoint)
	if err != nil {
		host = c.endpoint // endpoint without port
	}
	creds := credentials.NewTLS(&tls.Config{
		Certificates: []tls.Certificate{cert},
		RootCAs:      pool,
		MinVersion:   tls.VersionTLS13,
		ServerName:   host,
	})

	conn, err := grpc.Dial(c.endpoint, //nolint:staticcheck -- DialContext replacement is grpc.NewClient in v1.63+
		grpc.WithTransportCredentials(creds),
		grpc.WithDefaultCallOptions(
			grpc.MaxCallRecvMsgSize(maxMsgSize),
			grpc.MaxCallSendMsgSize(maxMsgSize),
		),
		grpc.WithKeepaliveParams(keepalive.ClientParameters{
			Time:                keepaliveTime,
			Timeout:             keepaliveTimeout,
			PermitWithoutStream: true,
		}),
	)
	if err != nil {
		return err
	}
	c.cc = conn
	c.svc = gen.NewAgentServiceClient(conn)
	return nil
}

// Close releases the underlying gRPC connection.
func (c *GRPCClient) Close() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.cc != nil {
		return c.cc.Close()
	}
	return nil
}

// Reconnect tears down the current connection (if any) and dials a fresh
// one. grpc-go's built-in reconnect logic doesn't always recover a stream
// that's been failing with EOF (e.g. after the server restarts) — seen in
// production where an agent sat in a failure loop for hours until manually
// restarted. Manager calls this after a run of consecutive failures so a
// dead transport gets replaced instead of retried forever.
func (c *GRPCClient) Reconnect() error {
	c.mu.Lock()
	old := c.cc
	c.cc = nil
	c.svc = nil
	c.mu.Unlock()

	if old != nil {
		old.Close() //nolint:errcheck
	}
	return c.dial()
}

// HeartbeatStream opens a bidirectional stream for heartbeat exchange.
// Used by HeartbeatManager for typed access; see also SendHeartbeat.
func (c *GRPCClient) HeartbeatStream(ctx context.Context) (gen.AgentService_HeartbeatStreamClient, error) {
	if err := c.dial(); err != nil {
		return nil, err
	}
	return c.svc.HeartbeatStream(ctx)
}

// SendHeartbeat sends one heartbeat over a short-lived stream and returns the response.
// Payload keys consumed: "agent_id" (string), "packages_checksum" (string).
// ponytail: map interface preserved for AgentManager compat; HeartbeatManager uses
// HeartbeatStream directly with fully-typed requests (Val 3 wires it in).
func (c *GRPCClient) SendHeartbeat(
	ctx context.Context,
	payload map[string]interface{},
) (map[string]interface{}, error) {
	req := payloadToRequest(payload)

	stream, err := c.HeartbeatStream(ctx)
	if err != nil {
		return nil, err
	}
	if err := stream.Send(req); err != nil {
		return nil, err
	}
	if err := stream.CloseSend(); err != nil {
		return nil, err
	}

	resp, err := stream.Recv()
	if err != nil {
		return nil, err
	}
	return responseToMap(resp), nil
}

func payloadToRequest(m map[string]interface{}) *gen.AgentHeartbeatRequest {
	req := &gen.AgentHeartbeatRequest{Timestamp: time.Now()}
	if v, ok := m["agent_id"].(string); ok {
		req.AgentId = v
	}
	if v, ok := m["packages_checksum"].(string); ok {
		req.PackagesChecksum = v
	}
	if v, ok := m["agent_version"].(string); ok {
		req.AgentVersion = v
	}
	if v, ok := m["recent_logs"].([]string); ok {
		req.RecentLogs = v
	}
	if v, ok := m["log_connections"].(int); ok {
		req.LogConnections = int32(v)
	}
	if v, ok := m["log_informative"].(int); ok {
		req.LogInformative = int32(v)
	}
	if v, ok := m["log_critical"].(int); ok {
		req.LogCritical = int32(v)
	}
	if v, ok := m["domain_hashes"].(map[string]string); ok {
		req.DomainHashes = v
	}
	if v, ok := m["domain_full"].(map[string]map[string]interface{}); ok {
		req.DomainFull = v
	}
	if sys, ok := m["system"].(*modules.SystemInfo); ok {
		var disks []*gen.Disk
		for _, d := range sys.Disks {
			disks = append(disks, &gen.Disk{
				MountPoint: d.MountPoint,
				Filesystem: d.Filesystem,
				TotalSize:  d.TotalBytes,
				UsedSize:   d.UsedBytes,
				FreeSize:   d.FreeBytes,
			})
		}
		var ifaces []*gen.NetworkInterface
		for _, n := range sys.NetworkIfaces {
			ifaces = append(ifaces, &gen.NetworkInterface{
				Name:        n.Name,
				MacAddress:  n.MacAddress,
				IPAddresses: n.IPAddresses,
				IsUp:        n.IsUp,
				RxBytes:     n.RxBytes,
				TxBytes:     n.TxBytes,
			})
		}
		var blockDevs []*gen.BlockDevice
		for _, b := range sys.BlockDevices {
			blockDevs = append(blockDevs, &gen.BlockDevice{
				Name:       b.Name,
				Type:       b.Type,
				Size:       b.SizeBytes,
				MountPoint: b.MountPoint,
				ParentName: b.ParentName,
			})
		}
		var ports []*gen.ListeningPort
		for _, p := range sys.ListeningPorts {
			ports = append(ports, &gen.ListeningPort{
				Protocol:     p.Protocol,
				LocalAddress: p.LocalAddress,
				LocalPort:    int32(p.LocalPort),
				PID:          int32(p.PID),
				ProcessName:  p.ProcessName,
			})
		}
		req.SystemStatus = &gen.SystemStatus{
			Hostname:          sys.Hostname,
			FQDN:              sys.FQDN,
			OSFamily:          sys.OSFamily,
			OSDistro:          sys.OSDistro,
			OSVersion:         sys.OSVersion,
			KernelVersion:     sys.KernelVersion,
			Arch:              sys.Arch,
			CPUCount:          int32(sys.CPUCount),
			TotalMemory:       sys.TotalMemoryKB * 1024,
			FreeMemory:        sys.FreeMemoryKB * 1024,
			SystemUsers:       sys.SystemUsers,
			Disks:             disks,
			NetworkInterfaces: ifaces,
			BlockDevices:      blockDevs,
			ListeningPorts:    ports,
		}
	}
	if h, ok := m["health"].(modules.Health); ok {
		req.Health = &gen.AgentHealth{
			CPUUsage:         float32(h.CPUUsagePercent),
			CPUCount:         int32(h.CPUCount),
			MemoryUsage:      float32(h.MemoryUsagePercent),
			MemoryTotalBytes: h.MemoryTotalBytes,
			MemoryUsedBytes:  h.MemoryUsedBytes,
			DiskUsage:        float32(h.DiskUsagePercent),
			DiskTotalBytes:   h.DiskTotalBytes,
			DiskUsedBytes:    h.DiskUsedBytes,
			SwapUsage:        float32(h.SwapUsagePercent),
			SwapTotalBytes:   h.SwapTotalBytes,
			SwapUsedBytes:    h.SwapUsedBytes,
		}
	}
	if results, ok := m["job_results"].([]modules.JobResult); ok {
		for _, r := range results {
			state := gen.JobCompleted
			if r.ExitCode != 0 {
				state = gen.JobFailed
			}
			output := r.Stdout
			if r.Stderr != "" {
				output += "\n--- stderr ---\n" + r.Stderr
			}
			req.JobResults = append(req.JobResults, &gen.JobResult{
				JobId:        r.JobID,
				State:        state,
				Output:       output,
				ExitCode:     int32(r.ExitCode),
				ErrorMessage: r.Error,
				UpdatedAt:    time.Now(),
			})
		}
	}
	if pkgs, ok := m["packages"].([]modules.Package); ok {
		for _, p := range pkgs {
			req.Packages = append(req.Packages, &gen.Package{
				Name:             p.Name,
				Version:          p.Version,
				Architecture:     p.Architecture,
				LatestVersion:    p.LatestVersion,
				UpdateAvailable:  p.UpdateAvailable,
				IsSecurityUpdate: p.IsSecurityUpdate,
			})
		}
	}
	if vulns, ok := m["vulnerabilities"].([]modules.Vulnerability); ok {
		for _, v := range vulns {
			req.Vulnerabilities = append(req.Vulnerabilities, &gen.Vulnerability{
				CveId:            v.CVEId,
				PackageName:      v.PackageName,
				InstalledVersion: v.InstalledVer,
				FixedVersion:     v.FixedVer,
				Severity:         v.Severity,
			})
		}
	}
	return req
}

func responseToMap(resp *gen.AgentHeartbeatResponse) map[string]interface{} {
	if resp == nil {
		return nil
	}
	result := map[string]interface{}{}
	if len(resp.PendingJobs) > 0 {
		jobs := make([]interface{}, 0, len(resp.PendingJobs))
		for _, j := range resp.PendingJobs {
			if j == nil {
				continue
			}
			jobs = append(jobs, map[string]interface{}{
				"job_id":          j.JobId,
				"job_type":        j.JobType,
				"parameters":      j.Parameters,
				"timeout_seconds": j.TimeoutSeconds,
			})
		}
		if len(jobs) > 0 {
			result["pending_jobs"] = jobs
		}
	}
	if resp.UpdatePolicy != nil {
		result["policy"] = resp.UpdatePolicy
	}
	if resp.RebootRequest != "" {
		result["reboot"] = resp.RebootRequest
	}
	if resp.PluginAction != "" {
		result["plugin_action"] = resp.PluginAction
	}
	if len(resp.ResyncDomains) > 0 {
		result["resync_domains"] = resp.ResyncDomains
	}
	if len(result) == 0 {
		return nil
	}
	return result
}
