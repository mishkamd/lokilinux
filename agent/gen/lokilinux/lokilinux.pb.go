// Hand-written Go equivalents of lokilinux.proto message types.
// ponytail: plain structs + JSON tags replace protoc-generated code.
//
//	Swap: run `protoc --go_out=gen --go-grpc_out=gen proto/lokilinux.proto`
//	once protoc is available, then remove jsonCodec override in grpc_client.go.
package lokilinux

import "time"

// ─── Heartbeat ───────────────────────────────────────────────────────────────

type AgentHeartbeatRequest struct {
	AgentId          string           `json:"agent_id"`
	Timestamp        time.Time        `json:"timestamp"`
	SystemStatus     *SystemStatus    `json:"system_status,omitempty"`
	Packages         []*Package       `json:"packages,omitempty"`
	Services         []*Service       `json:"services,omitempty"`
	Repositories     []*Repository    `json:"repositories,omitempty"`
	Vulnerabilities  []*Vulnerability `json:"vulnerabilities,omitempty"`
	Health           *AgentHealth     `json:"health,omitempty"`
	PendingJobs      int32            `json:"pending_jobs,omitempty"`
	ConfigVersion    string           `json:"config_version,omitempty"`
	PackagesChecksum string           `json:"packages_checksum,omitempty"`
	AgentVersion     string           `json:"agent_version,omitempty"`
	RecentLogs       []string         `json:"recent_logs,omitempty"`
	LogConnections   int32            `json:"log_connections,omitempty"`
	LogInformative   int32            `json:"log_informative,omitempty"`
	LogCritical      int32            `json:"log_critical,omitempty"`
	JobResults       []*JobResult     `json:"job_results,omitempty"`

	// DomainHashes/DomainFull carry the compliance module's per-domain delta
	// sync (docs/compliance/04-PROTOCOL.md §3) — DomainHashes goes out every
	// heartbeat (cheap), DomainFull only for domains the previous response's
	// ResyncDomains flagged.
	DomainHashes map[string]string                 `json:"domain_hashes,omitempty"`
	DomainFull   map[string]map[string]interface{} `json:"domain_full,omitempty"`
}

// AgentHeartbeatResponse carries the server's reply to one heartbeat.
// PendingJobs replaces the proto's single-job oneof (ExecuteJob) — the
// server can return up to 10 pending jobs per heartbeat (see
// AgentService.get_pending_jobs), which a oneof cannot represent.
type AgentHeartbeatResponse struct {
	PendingJobs   []*JobRequest `json:"pending_jobs,omitempty"`
	UpdatePolicy  *PolicyConfig `json:"update_policy,omitempty"`
	RebootRequest string        `json:"reboot_request,omitempty"`
	PluginAction  string        `json:"plugin_action,omitempty"`

	// ResyncDomains lists compliance domains whose last-reported hash didn't
	// match the server's latest snapshot — the agent sends a full body for
	// each of these in DomainFull on its *next* heartbeat (04-PROTOCOL.md §3).
	ResyncDomains []string `json:"resync_domains,omitempty"`
}

// ─── System ───────────────────────────────────────────────────────────────────

type SystemStatus struct {
	Hostname          string              `json:"hostname"`
	FQDN              string              `json:"fqdn,omitempty"`
	OSFamily          string              `json:"os_family"`
	OSDistro          string              `json:"os_distro"`
	OSVersion         string              `json:"os_version"`
	KernelVersion     string              `json:"kernel_version"`
	Arch              string              `json:"arch"`
	CPUCount          int32               `json:"cpu_count"`
	TotalMemory       uint64              `json:"total_memory"`
	FreeMemory        uint64              `json:"free_memory"`
	Disks             []*Disk             `json:"disks,omitempty"`
	BootTime          time.Time           `json:"boot_time,omitempty"`
	SystemUsers       []string            `json:"system_users,omitempty"`
	NetworkInterfaces []*NetworkInterface `json:"network_interfaces,omitempty"`
	BlockDevices      []*BlockDevice      `json:"block_devices,omitempty"`
	ListeningPorts    []*ListeningPort    `json:"listening_ports,omitempty"`
}

type Disk struct {
	MountPoint string `json:"mount_point"`
	Filesystem string `json:"filesystem"`
	TotalSize  uint64 `json:"total_size"`
	UsedSize   uint64 `json:"used_size"`
	FreeSize   uint64 `json:"free_size"`
}

type NetworkInterface struct {
	Name        string   `json:"name"`
	MacAddress  string   `json:"mac_address,omitempty"`
	IPAddresses []string `json:"ip_addresses,omitempty"`
	IsUp        bool     `json:"is_up"`
	RxBytes     uint64   `json:"rx_bytes,omitempty"`
	TxBytes     uint64   `json:"tx_bytes,omitempty"`
}

// BlockDevice mirrors `lsblk` output — flat list, ParentName links a
// partition/lvm-mapper entry back to its parent disk (empty for top-level disks).
type BlockDevice struct {
	Name       string `json:"name"`
	Type       string `json:"type"`
	Size       uint64 `json:"size"`
	MountPoint string `json:"mount_point,omitempty"`
	ParentName string `json:"parent_name,omitempty"`
}

// ListeningPort mirrors one `ss -tulpn` row — sockets in LISTEN state only.
type ListeningPort struct {
	Protocol     string `json:"protocol"`
	LocalAddress string `json:"local_address"`
	LocalPort    int32  `json:"local_port"`
	PID          int32  `json:"pid,omitempty"`
	ProcessName  string `json:"process_name,omitempty"`
}

type Package struct {
	Name             string    `json:"name"`
	Version          string    `json:"version"`
	Architecture     string    `json:"architecture"`
	Source           string    `json:"source,omitempty"`
	Maintainer       string    `json:"maintainer,omitempty"`
	InstalledDate    time.Time `json:"installed_date,omitempty"`
	UpdateAvailable  bool      `json:"update_available,omitempty"`
	LatestVersion    string    `json:"latest_version,omitempty"`
	IsSecurityUpdate bool      `json:"is_security_update,omitempty"`
	SecurityAdvisory string    `json:"security_advisory,omitempty"`
}

type Repository struct {
	Name         string    `json:"name"`
	Type         string    `json:"type"`
	URL          string    `json:"url"`
	Distribution string    `json:"distribution"`
	Components   []string  `json:"components,omitempty"`
	Enabled      bool      `json:"enabled"`
	LastUpdate   time.Time `json:"last_update,omitempty"`
	PackageCount int32     `json:"package_count,omitempty"`
}

type Service struct {
	Name         string    `json:"name"`
	IsRunning    bool      `json:"is_running"`
	Status       string    `json:"status"`
	LastStarted  time.Time `json:"last_started,omitempty"`
	RestartCount int32     `json:"restart_count,omitempty"`
	IsEnabled    bool      `json:"is_enabled"`
}

type Vulnerability struct {
	CveId              string   `json:"cve_id"`
	PackageName        string   `json:"package_name"`
	InstalledVersion   string   `json:"installed_version"`
	FixedVersion       string   `json:"fixed_version,omitempty"`
	CvssScore          float32  `json:"cvss_score,omitempty"`
	Severity           string   `json:"severity"`
	Description        string   `json:"description,omitempty"`
	AffectedComponents []string `json:"affected_components,omitempty"`
}

type AgentHealth struct {
	Status             AgentHealthStatus `json:"status"`
	CPUUsage           float32           `json:"cpu_usage"`
	CPUCount           int32             `json:"cpu_count,omitempty"`
	MemoryUsage        float32           `json:"memory_usage"`
	MemoryTotalBytes   uint64            `json:"memory_total_bytes,omitempty"`
	MemoryUsedBytes    uint64            `json:"memory_used_bytes,omitempty"`
	DiskUsage          float32           `json:"disk_usage"`
	DiskTotalBytes     uint64            `json:"disk_total_bytes,omitempty"`
	DiskUsedBytes      uint64            `json:"disk_used_bytes,omitempty"`
	SwapUsage          float32           `json:"swap_usage,omitempty"`
	SwapTotalBytes     uint64            `json:"swap_total_bytes,omitempty"`
	SwapUsedBytes      uint64            `json:"swap_used_bytes,omitempty"`
	NetworkLatencyMs   int32             `json:"network_latency_ms,omitempty"`
	ConnectionFailures int32             `json:"connection_failures,omitempty"`
	LastError          string            `json:"last_error,omitempty"`
}

type AgentHealthStatus int32

const (
	AgentHealthUnknown   AgentHealthStatus = 0
	AgentHealthHealthy   AgentHealthStatus = 1
	AgentHealthDegraded  AgentHealthStatus = 2
	AgentHealthUnhealthy AgentHealthStatus = 3
)

// ─── Jobs ─────────────────────────────────────────────────────────────────────

type JobRequest struct {
	JobId          string   `json:"job_id"`
	JobType        string   `json:"job_type"`
	Scope          string   `json:"scope,omitempty"`
	TargetPackages []string `json:"target_packages,omitempty"`
	// Parameters is map[string]interface{}, not map[string]string: the
	// control plane sends nested JSON here (playbook_content, extra_vars,
	// roles are all objects/arrays, not flat strings) — a flat string map
	// silently dropped every non-trivial job parameter.
	Parameters        map[string]interface{} `json:"parameters,omitempty"`
	ScheduledTime     time.Time              `json:"scheduled_time,omitempty"`
	TimeoutSeconds    int32                  `json:"timeout_seconds,omitempty"`
	RequiresApproval  bool                   `json:"requires_approval,omitempty"`
	AllowRollback     bool                   `json:"allow_rollback,omitempty"`
	MaintenanceWindow string                 `json:"maintenance_window,omitempty"`
}

type JobResult struct {
	JobId           string    `json:"job_id"`
	State           JobState  `json:"state"`
	ProgressPercent float32   `json:"progress_percent,omitempty"`
	Output          string    `json:"output,omitempty"`
	ExitCode        int32     `json:"exit_code,omitempty"`
	ErrorMessage    string    `json:"error_message,omitempty"`
	UpdatedAt       time.Time `json:"updated_at,omitempty"`
}

type JobState int32

const (
	JobPending    JobState = 0
	JobRunning    JobState = 1
	JobCompleted  JobState = 2
	JobFailed     JobState = 3
	JobTimeout    JobState = 4
	JobCancelled  JobState = 5
	JobRolledBack JobState = 6
)

// ─── Policy ───────────────────────────────────────────────────────────────────

type PolicyConfig struct {
	Version           string            `json:"version"`
	Policies          map[string]string `json:"policies,omitempty"`
	CommandWhitelist  []string          `json:"command_whitelist,omitempty"`
	HeartbeatInterval int32             `json:"heartbeat_interval,omitempty"`
}

type PolicySyncRequest struct {
	AgentId        string `json:"agent_id"`
	CurrentVersion string `json:"current_version"`
}

// ─── Metrics ──────────────────────────────────────────────────────────────────

type MetricsData struct {
	AgentId    string            `json:"agent_id"`
	Timestamp  time.Time         `json:"timestamp"`
	MetricName string            `json:"metric_name"`
	Value      float64           `json:"value"`
	Tags       map[string]string `json:"tags,omitempty"`
}

type MetricsAck struct {
	Success bool `json:"success"`
}

// ─── Plugins ──────────────────────────────────────────────────────────────────

type PluginInstallRequest struct {
	AgentId        string `json:"agent_id"`
	PluginName     string `json:"plugin_name"`
	PluginVersion  string `json:"plugin_version"`
	DownloadURL    string `json:"download_url"`
	ChecksumSha256 string `json:"checksum_sha256"`
}

type PluginInstallResult struct {
	Success      bool   `json:"success"`
	ErrorMessage string `json:"error_message,omitempty"`
}
