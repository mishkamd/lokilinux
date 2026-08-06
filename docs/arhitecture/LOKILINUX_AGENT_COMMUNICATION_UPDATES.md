# LokiLinux — Complete Communication & Management Architecture
## Agent Protocol, Server Management, Centralized Updates & Deployment Guide

---

## I. AGENT COMMUNICATION PROTOCOL — OPTIMIZED & SECURE

### 1.1 Communication Overview

```
┌─────────────────────────────────────────────────────────────┐
│            AGENT COMMUNICATION ARCHITECTURE                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Agent (Client Side)         →  mTLS + gRPC  →  API Server │
│  ├─ Heartbeat (every 60s)                                  │
│  ├─ Job Execution                                          │
│  ├─ Metrics/Status                                         │
│  ├─ Local Cache (SQLite)                                   │
│  └─ Offline Resilience                                     │
│                                                             │
│  Connection Model:                                         │
│  - Persistent gRPC stream (mTLS)                           │
│  - Fallback: HTTPS polling (if stream fails)               │
│  - Queue local jobs when offline                           │
│  - Auto-reconnect with exponential backoff                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Secure Communication Protocol

**File:** `agent/internal/communication/protocol.proto`

```protobuf
syntax = "proto3";
package lokilinux.agent;

import "google/protobuf/timestamp.proto";
import "google/protobuf/struct.proto";

// ============================================================================
// HEARTBEAT PROTOCOL
// ============================================================================

message AgentHeartbeat {
  string agent_id = 1;
  google.protobuf.Timestamp timestamp = 2;
  
  // System Status
  SystemStatus system_status = 3;
  
  // Package Information
  repeated Package packages = 4;
  
  // Running Services
  repeated Service services = 5;
  
  // Repositories Configured
  repeated Repository repositories = 6;
  
  // Custom Metadata
  google.protobuf.Struct custom_facts = 7;
  
  // Vulnerability Status
  repeated CVEMatch vulnerabilities = 8;
  
  // Health Metrics
  AgentHealth health = 9;
  
  // Pending Job Count
  int32 pending_jobs = 10;
  
  // Agent Configuration Version (for policy updates)
  string config_version = 11;
}

message SystemStatus {
  string hostname = 1;
  string os_family = 2;     // linux
  string os_distro = 3;     // debian, ubuntu, rhel, rocky
  string os_version = 4;    // 20.04, 8.5
  string kernel_version = 5;
  string arch = 6;          // x86_64, arm64
  int32 cpu_count = 7;
  uint64 total_memory = 8;
  uint64 free_memory = 9;
  repeated Disk disks = 10;
  google.protobuf.Timestamp boot_time = 11;
}

message Disk {
  string mount_point = 1;
  string filesystem = 2;
  uint64 total_size = 3;
  uint64 used_size = 4;
  uint64 free_size = 5;
}

message Package {
  string name = 1;
  string version = 2;
  string architecture = 3;
  string source = 4;        // repository name
  string maintainer = 5;
  google.protobuf.Timestamp installed_date = 6;
  
  // Update Information
  bool update_available = 7;
  string latest_version = 8;
  bool is_security_update = 9;
  string security_advisory = 10;
}

message Repository {
  string name = 1;
  string type = 2;          // apt, dnf, yum, zypper
  string url = 3;
  string distribution = 4;  // focal, jammy, 8, 9
  repeated string components = 5;
  bool enabled = 6;
  google.protobuf.Timestamp last_update = 7;
  int32 package_count = 8;
}

message Service {
  string name = 1;
  bool is_running = 2;
  string status = 3;
  google.protobuf.Timestamp last_started = 4;
  int32 restart_count = 5;
  bool is_enabled = 6;
}

message CVEMatch {
  string cve_id = 1;
  string package_name = 2;
  string installed_version = 3;
  string fixed_version = 4;
  float cvss_score = 5;
  string severity = 6;      // low, medium, high, critical
  string description = 7;
  repeated string affected_components = 8;
}

message AgentHealth {
  enum Status {
    UNKNOWN = 0;
    HEALTHY = 1;
    DEGRADED = 2;
    UNHEALTHY = 3;
  }
  Status status = 1;
  float cpu_usage = 2;      // 0-100
  float memory_usage = 3;   // 0-100
  float disk_usage = 4;     // 0-100
  int32 network_latency_ms = 5;
  int32 connection_failures = 6;
  string last_error = 7;
}

// ============================================================================
// JOB EXECUTION
// ============================================================================

message Job {
  string job_id = 1;
  string job_type = 2;      // PACKAGE_UPDATE, SECURITY_PATCH, REPO_ADD, etc.
  
  // Target Scope
  string scope = 3;         // prod, dev, stage, uat, project-x
  repeated string target_packages = 4;
  
  // Parameters
  google.protobuf.Struct parameters = 5;
  
  // Execution
  google.protobuf.Timestamp scheduled_time = 6;
  int32 timeout_seconds = 7;
  
  // Configuration
  bool requires_approval = 8;
  bool allow_rollback = 9;
  string maintenance_window = 10;
}

message JobStatus {
  enum State {
    PENDING = 0;
    RUNNING = 1;
    COMPLETED = 2;
    FAILED = 3;
    TIMEOUT = 4;
    CANCELLED = 5;
    ROLLED_BACK = 6;
  }
  
  string job_id = 1;
  State state = 2;
  float progress_percent = 3;
  string output = 4;
  int32 exit_code = 5;
  string error_message = 6;
  google.protobuf.Timestamp updated_at = 7;
}

// ============================================================================
// STREAMING RPC SERVICES
// ============================================================================

service AgentService {
  // Bidirectional streaming: heartbeat with job responses
  rpc AgentHeartbeatStream(stream AgentHeartbeat) returns (stream ServerCommand);
  
  // Job execution with streaming output
  rpc ExecuteJobStream(Job) returns (stream JobStatus);
  
  // Metrics collection
  rpc ReportMetrics(stream MetricPoint) returns (MetricAck);
  
  // Configuration sync
  rpc SyncConfig(ConfigRequest) returns (ConfigData);
}

message ServerCommand {
  oneof command {
    Job execute_job = 1;
    ConfigData update_config = 2;
    string reboot_request = 3;
    string plugin_action = 4;
  }
}

message MetricPoint {
  string agent_id = 1;
  google.protobuf.Timestamp timestamp = 2;
  string metric_name = 3;
  double value = 4;
  map<string, string> tags = 5;
}

message MetricAck {
  bool success = 1;
}

message ConfigRequest {
  string agent_id = 1;
  string current_version = 2;
}

message ConfigData {
  string version = 1;
  google.protobuf.Struct policies = 2;
  repeated string command_whitelist = 3;
  int32 heartbeat_interval = 4;
}
```

### 1.3 Agent Communication Implementation

**File:** `agent/internal/communication/grpc_client.go`

```go
package communication

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/keepalive"
	"google.golang.org/grpc/status"
	"google.golang.org/grpc/codes"
)

type GRPCClient struct {
	conn              *grpc.ClientConn
	client            AgentServiceClient
	logger            *slog.Logger
	config            *ClientConfig
	reconnectBackoff  time.Duration
	maxReconnectWait  time.Duration
}

type ClientConfig struct {
	ServerURL     string
	CertPath      string
	KeyPath       string
	CAPath        string
	RequestTimeout time.Duration
	HeartbeatInterval time.Duration
}

func NewGRPCClient(cfg *ClientConfig, logger *slog.Logger) (*GRPCClient, error) {
	// Load mTLS credentials
	creds, err := credentials.NewClientTLSFromFile(
		cfg.CAPath,
		cfg.ServerURL,
	)
	if err != nil {
		return nil, fmt.Errorf("failed to load TLS credentials: %w", err)
	}

	// Keep-alive parameters (prevent connection drop)
	kacp := keepalive.ClientParameters{
		Time:                10 * time.Second,  // Send keep-alive every 10s
		Timeout:             5 * time.Second,   // Wait 5s for keep-alive response
		PermitWithoutStream: true,              // Send keep-alive even without active streams
	}

	// Create connection with optimizations
	conn, err := grpc.Dial(
		cfg.ServerURL,
		grpc.WithTransportCredentials(creds),
		grpc.WithKeepaliveParams(kacp),
		grpc.WithDefaultCallOptions(
			grpc.MaxCallRecvMsgSize(16*1024*1024), // 16MB max message
		),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to dial server: %w", err)
	}

	return &GRPCClient{
		conn:              conn,
		client:            NewAgentServiceClient(conn),
		logger:            logger,
		config:            cfg,
		reconnectBackoff:  1 * time.Second,
		maxReconnectWait:  5 * time.Minute,
	}, nil
}

// ============================================================================
// HEARTBEAT STREAMING
// ============================================================================

func (gc *GRPCClient) SendHeartbeatStream(ctx context.Context, heartbeatChan <-chan *AgentHeartbeat) {
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		// Create streaming connection
		stream, err := gc.client.AgentHeartbeatStream(ctx)
		if err != nil {
			gc.logger.Error("Failed to create heartbeat stream", "error", err)
			gc.backoffWait(ctx)
			continue
		}

		// Send heartbeats and receive commands
		err = gc.heartbeatLoop(stream, heartbeatChan)
		if err != nil {
			gc.logger.Error("Heartbeat stream error", "error", err)
			stream.CloseSend()
			gc.backoffWait(ctx)
			continue
		}
	}
}

func (gc *GRPCClient) heartbeatLoop(
	stream AgentService_AgentHeartbeatStreamClient,
	heartbeatChan <-chan *AgentHeartbeat,
) error {
	// Ticker for periodic heartbeat if not sent
	ticker := time.NewTicker(gc.config.HeartbeatInterval)
	defer ticker.Stop()

	for {
		select {
		case <-stream.Context().Done():
			return stream.Context().Err()

		case heartbeat := <-heartbeatChan:
			// Send heartbeat
			if err := stream.Send(heartbeat); err != nil {
				return fmt.Errorf("failed to send heartbeat: %w", err)
			}

		case <-ticker.C:
			// Send periodic heartbeat (keep connection alive)
			if err := stream.Send(&AgentHeartbeat{
				Timestamp: timestamppb.Now(),
			}); err != nil {
				return fmt.Errorf("failed to send periodic heartbeat: %w", err)
			}

		default:
			// Receive commands from server
			cmd, err := stream.Recv()
			if err != nil {
				if status.Code(err) == codes.Canceled {
					return nil
				}
				return fmt.Errorf("failed to receive command: %w", err)
			}

			// Process command
			gc.processServerCommand(cmd)
		}
	}
}

func (gc *GRPCClient) processServerCommand(cmd *ServerCommand) {
	switch cmd := cmd.Command.(type) {
	case *ServerCommand_ExecuteJob:
		gc.logger.Info("Received job from server", "job_id", cmd.ExecuteJob.JobId)
		// Handle job execution (will be processed by job executor)

	case *ServerCommand_UpdateConfig:
		gc.logger.Info("Received config update from server")
		// Handle config update

	case *ServerCommand_RebootRequest:
		gc.logger.Warn("Received reboot request", "reason", cmd.RebootRequest)
		// Request reboot (may require approval)

	case *ServerCommand_PluginAction:
		gc.logger.Info("Received plugin action", "action", cmd.PluginAction)
		// Handle plugin management
	}
}

func (gc *GRPCClient) backoffWait(ctx context.Context) {
	select {
	case <-ctx.Done():
		return
	case <-time.After(gc.reconnectBackoff):
		// Exponential backoff
		gc.reconnectBackoff *= 2
		if gc.reconnectBackoff > gc.maxReconnectWait {
			gc.reconnectBackoff = gc.maxReconnectWait
		}
	}
}

// ============================================================================
// JOB EXECUTION
// ============================================================================

func (gc *GRPCClient) ExecuteJob(ctx context.Context, job *Job) (*JobStatus, error) {
	ctx, cancel := context.WithTimeout(ctx, time.Duration(job.TimeoutSeconds)*time.Second)
	defer cancel()

	stream, err := gc.client.ExecuteJobStream(ctx, job)
	if err != nil {
		return nil, fmt.Errorf("failed to execute job: %w", err)
	}

	var finalStatus *JobStatus

	for {
		status, err := stream.Recv()
		if err != nil {
			if err == io.EOF {
				break
			}
			return nil, fmt.Errorf("failed to receive job status: %w", err)
		}

		finalStatus = status

		// Log progress
		gc.logger.Info("Job progress", 
			"job_id", job.JobId,
			"state", status.State.String(),
			"progress", status.ProgressPercent,
		)
	}

	return finalStatus, nil
}

// ============================================================================
// CLEANUP
// ============================================================================

func (gc *GRPCClient) Close() error {
	return gc.conn.Close()
}
```

### 1.4 Agent Heartbeat Manager

**File:** `agent/internal/agent/heartbeat.go`

```go
package agent

import (
	"context"
	"sync"
	"time"

	"github.com/lokilinux/agent/internal/communication"
	"github.com/lokilinux/agent/internal/modules"
)

type HeartbeatManager struct {
	agent          *Agent
	client         *communication.GRPCClient
	modulesMgr     *modules.ModuleManager
	interval       time.Duration
	heartbeatChan  chan *communication.AgentHeartbeat
	stopChan       chan struct{}
	wg             sync.WaitGroup
}

func NewHeartbeatManager(
	agent *Agent,
	client *communication.GRPCClient,
	modulesMgr *modules.ModuleManager,
	interval time.Duration,
) *HeartbeatManager {
	return &HeartbeatManager{
		agent:         agent,
		client:        client,
		modulesMgr:    modulesMgr,
		interval:      interval,
		heartbeatChan: make(chan *communication.AgentHeartbeat, 1),
		stopChan:      make(chan struct{}),
	}
}

func (hm *HeartbeatManager) Start(ctx context.Context) {
	// Start heartbeat ticker
	hm.wg.Add(1)
	go hm.heartbeatTicker(ctx)

	// Start streaming to server
	hm.wg.Add(1)
	go hm.streamHeartbeats(ctx)
}

func (hm *HeartbeatManager) heartbeatTicker(ctx context.Context) {
	defer hm.wg.Done()

	ticker := time.NewTicker(hm.interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-hm.stopChan:
			return
		case <-ticker.C:
			hm.sendHeartbeat(ctx)
		}
	}
}

func (hm *HeartbeatManager) sendHeartbeat(ctx context.Context) {
	// Collect system info
	systemStatus, _ := hm.modulesMgr.ExecuteModule("system_info")
	packages, _ := hm.modulesMgr.ExecuteModule("package_manager")
	repos, _ := hm.modulesMgr.ExecuteModule("repository_manager")
	vulnerabilities, _ := hm.modulesMgr.ExecuteModule("vulnerability_scanner")
	health, _ := hm.modulesMgr.ExecuteModule("health_checker")

	// Build heartbeat
	heartbeat := &communication.AgentHeartbeat{
		AgentId:          hm.agent.config.AgentID,
		Timestamp:        timestamppb.Now(),
		SystemStatus:     systemStatus.(*communication.SystemStatus),
		Packages:         packages.([]*communication.Package),
		Repositories:     repos.([]*communication.Repository),
		Vulnerabilities:  vulnerabilities.([]*communication.CVEMatch),
		Health:           health.(*communication.AgentHealth),
		ConfigVersion:    hm.agent.configVersion,
	}

	// Send via channel (non-blocking)
	select {
	case hm.heartbeatChan <- heartbeat:
	case <-hm.stopChan:
		return
	default:
		// Channel full, skip this heartbeat (prevent blocking)
	}
}

func (hm *HeartbeatManager) streamHeartbeats(ctx context.Context) {
	defer hm.wg.Done()

	hm.client.SendHeartbeatStream(ctx, hm.heartbeatChan)
}

func (hm *HeartbeatManager) Stop() {
	close(hm.stopChan)
	hm.wg.Wait()
}
```

---

## II. SERVER MANAGEMENT & INVENTORY

### 2.1 Server List with Repository Info

**File:** `backend/lokilinux/api/v1/routers/servers.py`

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional, List
from datetime import datetime, timedelta

from lokilinux.models import Agent, Package, Repository
from lokilinux.schemas import ServerDetailResponse, RepositoryInfo
from lokilinux.cache import RedisCache
from lokilinux.dependencies import get_db, get_cache

router = APIRouter(prefix="/servers", tags=["servers"])

# ============================================================================
# LIST SERVERS WITH INVENTORY
# ============================================================================

@router.get("")
async def list_servers(
    status: Optional[str] = Query(None, description="Filter by status"),
    scope: Optional[str] = Query(None, description="Filter by scope (prod, dev, stage)"),
    limit: int = Query(100),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
):
    """
    List all servers with agent information
    
    Returns:
    - Server name, OS, status
    - Last heartbeat
    - Update availability
    - Scope/category
    """
    
    cache_key = f"servers:list:{status}:{scope}:{limit}:{offset}"
    cached = await cache.get(cache_key)
    if cached:
        return cached
    
    # Build query
    query = select(Agent)
    
    if status:
        query = query.where(Agent.status == status)
    
    if scope:
        query = query.where(Agent.scope == scope)
    
    query = query.order_by(Agent.created_at.desc()).limit(limit).offset(offset)
    
    result = await db.execute(query)
    agents = result.scalars().all()
    
    # Count total
    count_query = select(func.count()).select_from(Agent)
    if status:
        count_query = count_query.where(Agent.status == status)
    if scope:
        count_query = count_query.where(Agent.scope == scope)
    
    count_result = await db.execute(count_query)
    total = count_result.scalar()
    
    # Build response
    servers = []
    for agent in agents:
        # Check if updates available
        pkg_query = select(Package).where(
            Package.agent_id == agent.id,
            Package.update_available == True
        )
        pkg_result = await db.execute(pkg_query)
        updates_available = len(pkg_result.scalars().all())
        
        servers.append({
            "id": str(agent.id),
            "agent_id": agent.agent_id,
            "hostname": agent.hostname,
            "os_distro": agent.os_distro,
            "os_version": agent.os_version,
            "kernel": agent.kernel_version,
            "arch": agent.arch,
            "status": agent.status,
            "scope": agent.scope,  # prod, dev, stage, uat, or project-x
            "last_heartbeat": agent.last_heartbeat.isoformat() if agent.last_heartbeat else None,
            "updates_available": updates_available,
            "cve_count": agent.cve_count,
            "tags": agent.tags,
        })
    
    response = {
        "servers": servers,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
    
    # Cache for 5 minutes
    await cache.set(cache_key, response, ttl=timedelta(minutes=5))
    
    return response


# ============================================================================
# SERVER DETAIL WITH REPOSITORIES & PACKAGES
# ============================================================================

@router.get("/{agent_id}")
async def get_server_detail(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
):
    """
    Get detailed server info including:
    - System information
    - Installed repositories
    - Installed packages (with update status)
    - Available updates
    - Vulnerabilities
    """
    
    cache_key = f"server:{agent_id}:detail"
    cached = await cache.get(cache_key)
    if cached:
        return cached
    
    # Get agent
    query = select(Agent).where(Agent.agent_id == agent_id)
    result = await db.execute(query)
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(status_code=404, detail="Server not found")
    
    # Get repositories
    repo_query = select(Repository).where(Repository.agent_id == agent.id)
    repo_result = await db.execute(repo_query)
    repositories = repo_result.scalars().all()
    
    # Get packages
    pkg_query = select(Package).where(Package.agent_id == agent.id)
    pkg_result = await db.execute(pkg_query)
    packages = pkg_result.scalars().all()
    
    # Separate installed and updatable
    installed_packages = []
    updatable_packages = []
    
    for pkg in packages:
        pkg_info = {
            "id": pkg.id,
            "name": pkg.name,
            "version": pkg.version,
            "architecture": pkg.arch,
            "source": pkg.source,
            "installed_date": pkg.installed_date.isoformat() if pkg.installed_date else None,
        }
        
        if pkg.update_available:
            pkg_info["latest_version"] = pkg.latest_version
            pkg_info["is_security_update"] = pkg.is_security_update
            updatable_packages.append(pkg_info)
        else:
            installed_packages.append(pkg_info)
    
    # Build response
    response = {
        "agent_id": agent.agent_id,
        "hostname": agent.hostname,
        "system": {
            "os_distro": agent.os_distro,
            "os_version": agent.os_version,
            "kernel": agent.kernel_version,
            "arch": agent.arch,
            "cpu_count": agent.cpu_count,
            "memory_total": agent.memory_total,
            "boot_time": agent.boot_time.isoformat() if agent.boot_time else None,
        },
        "repositories": [
            {
                "name": r.name,
                "type": r.type,  # apt, dnf, yum
                "url": r.url,
                "enabled": r.enabled,
                "package_count": r.package_count,
                "last_update": r.last_update.isoformat() if r.last_update else None,
            }
            for r in repositories
        ],
        "packages": {
            "total_installed": len(installed_packages),
            "total_with_updates": len(updatable_packages),
            "installed": installed_packages[:20],  # First 20
            "available_updates": updatable_packages,
        },
        "status": agent.status,
        "scope": agent.scope,
        "last_heartbeat": agent.last_heartbeat.isoformat() if agent.last_heartbeat else None,
        "cve_count": agent.cve_count,
        "tags": agent.tags,
    }
    
    # Cache for 5 minutes
    await cache.set(cache_key, response, ttl=timedelta(minutes=5))
    
    return response


# ============================================================================
# GET AVAILABLE UPDATES FOR SERVER
# ============================================================================

@router.get("/{agent_id}/updates")
async def get_server_updates(
    agent_id: str,
    security_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all available updates for a server
    
    If security_only=true, return only security updates
    """
    
    # Get agent
    query = select(Agent).where(Agent.agent_id == agent_id)
    result = await db.execute(query)
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(status_code=404)
    
    # Get updatable packages
    update_query = select(Package).where(
        Package.agent_id == agent.id,
        Package.update_available == True
    )
    
    if security_only:
        update_query = update_query.where(Package.is_security_update == True)
    
    result = await db.execute(update_query)
    packages = result.scalars().all()
    
    return {
        "agent_id": agent_id,
        "hostname": agent.hostname,
        "os_distro": agent.os_distro,
        "scope": agent.scope,
        "updates": [
            {
                "name": p.name,
                "current_version": p.version,
                "latest_version": p.latest_version,
                "is_security_update": p.is_security_update,
                "source": p.source,
            }
            for p in packages
        ],
        "total_updates": len(packages),
    }
```

---

## III. CENTRALIZED UPDATE MANAGEMENT

### 3.1 Update Strategy & Categorization

**File:** `backend/lokilinux/models/update_strategy.py`

```python
from enum import Enum
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

class Scope(str, Enum):
    """Server scope/environment"""
    PRODUCTION = "prod"
    STAGING = "stage"
    DEVELOPMENT = "dev"
    UAT = "uat"
    PROJECT = "project"  # project-{name}


class UpdateStrategy(str, Enum):
    """Update execution strategy"""
    IMMEDIATE = "immediate"
    STAGED = "staged"         # Wave-based (25%, 50%, 75%, 100%)
    CANARY = "canary"         # Canary (5% → 25% → 100% if successful)
    MAINTENANCE_WINDOW = "maintenance_window"  # During maintenance only
    MANUAL = "manual"         # Require approval


class UpdatePolicy(BaseModel):
    """Update policy for scope"""
    id: str
    scope: Scope
    
    # Update types
    security_only: bool = False
    include_minor_versions: bool = True
    include_major_versions: bool = False
    
    # Timing
    auto_update_enabled: bool = True
    update_strategy: UpdateStrategy = UpdateStrategy.STAGED
    
    # If staged: hours between waves
    staging_wave_hours: int = 24
    
    # If canary: percentages
    canary_waves: List[int] = [5, 25, 100]
    canary_wait_hours: int = 6
    
    # Maintenance window (e.g., "Sunday 2:00 AM")
    maintenance_window: Optional[str] = None
    
    # Approval
    requires_approval: bool = False
    approval_roles: List[str] = ["admin", "manager"]
    
    # Post-update
    auto_reboot_if_required: bool = True
    reboot_wait_hours: int = 24
    
    # Notifications
    notify_on_completion: bool = True
    notification_channels: List[str] = ["email"]
    
    created_at: datetime
    updated_at: datetime


class UpdateJob(BaseModel):
    """Represents an update job across multiple servers"""
    id: str
    scope: Scope
    
    # What to update
    package_filter: Optional[str] = None  # Package name pattern
    security_only: bool = False
    
    # Target servers
    target_count: int
    completed_count: int = 0
    failed_count: int = 0
    
    # Execution
    strategy: UpdateStrategy
    status: str  # pending, running, completed, failed, rolled_back
    
    # Waves (if staged)
    current_wave: int = 0
    total_waves: int = 1
    
    # Tracking
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Results
    changelog: List[Dict[str, Any]] = []
```

### 3.2 Update Job Management API

**File:** `backend/lokilinux/api/v1/routers/updates.py`

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime, timedelta
from typing import Optional, List

from lokilinux.models import Agent, Package, UpdateJob, UpdatePolicy
from lokilinux.services.update_service import UpdateService
from lokilinux.models.update_strategy import Scope, UpdateStrategy
from lokilinux.dependencies import get_db, get_current_user

router = APIRouter(prefix="/updates", tags=["updates"])

# ============================================================================
# GET UPDATE POLICY FOR SCOPE
# ============================================================================

@router.get("/policies/{scope}")
async def get_update_policy(
    scope: str,
    db: AsyncSession = Depends(get_db),
):
    """Get update policy for a scope (prod, dev, stage, etc.)"""
    
    query = select(UpdatePolicy).where(UpdatePolicy.scope == scope)
    result = await db.execute(query)
    policy = result.scalar_one_or_none()
    
    if not policy:
        raise HTTPException(status_code=404, detail=f"No policy for scope {scope}")
    
    return policy.dict()


# ============================================================================
# CREATE UPDATE JOB FOR SCOPE
# ============================================================================

@router.post("/execute/{scope}")
async def create_update_job_for_scope(
    scope: str,
    security_only: bool = False,
    package_filter: Optional[str] = None,
    dry_run: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    Create update job for all servers in a scope
    
    Examples:
    - POST /api/v1/updates/execute/prod (all updates for production)
    - POST /api/v1/updates/execute/dev?security_only=true (security only for dev)
    - POST /api/v1/updates/execute/stage?package_filter=kernel (kernel updates for stage)
    - POST /api/v1/updates/execute/project-x (all updates for project-x servers)
    """
    
    # Check permission
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Permission denied")
    
    # Get policy for scope
    policy_query = select(UpdatePolicy).where(UpdatePolicy.scope == scope)
    policy_result = await db.execute(policy_query)
    policy = policy_result.scalar_one_or_none()
    
    if not policy:
        raise HTTPException(status_code=404, detail=f"No policy for scope {scope}")
    
    # Find target servers
    agent_query = select(Agent).where(
        Agent.scope == scope,
        Agent.status == "ACTIVE"
    )
    agent_result = await db.execute(agent_query)
    agents = agent_result.scalars().all()
    
    if not agents:
        raise HTTPException(status_code=400, detail=f"No active servers in scope {scope}")
    
    # Find updatable packages for these servers
    target_agents = [a.id for a in agents]
    
    pkg_query = select(Package).where(
        Package.agent_id.in_(target_agents),
        Package.update_available == True
    )
    
    if security_only:
        pkg_query = pkg_query.where(Package.is_security_update == True)
    
    if package_filter:
        pkg_query = pkg_query.where(Package.name.ilike(f"%{package_filter}%"))
    
    pkg_result = await db.execute(pkg_query)
    packages = pkg_result.scalars().all()
    
    if not packages and not dry_run:
        return {
            "status": "no_updates",
            "message": f"No updates available for scope {scope}",
        }
    
    # If dry run, return plan
    if dry_run:
        return {
            "status": "dry_run",
            "scope": scope,
            "servers_affected": len(agents),
            "packages_to_update": len(packages),
            "strategy": policy.update_strategy,
            "packages": [
                {
                    "name": p.name,
                    "current_version": p.version,
                    "latest_version": p.latest_version,
                    "is_security_update": p.is_security_update,
                }
                for p in packages
            ],
        }
    
    # Check if requires approval
    if policy.requires_approval and current_user.role not in policy.approval_roles:
        raise HTTPException(status_code=403, detail="This update requires approval")
    
    # Create update job
    update_service = UpdateService(db)
    
    job = await update_service.create_update_job(
        scope=scope,
        servers=agents,
        packages=packages,
        security_only=security_only,
        strategy=policy.update_strategy,
        policy=policy,
        user=current_user,
    )
    
    return {
        "status": "created",
        "job_id": str(job.id),
        "scope": scope,
        "servers": len(agents),
        "packages": len(packages),
        "strategy": policy.update_strategy,
    }


# ============================================================================
# GET UPDATE JOB STATUS
# ============================================================================

@router.get("/jobs/{job_id}")
async def get_update_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get status of an update job"""
    
    query = select(UpdateJob).where(UpdateJob.id == job_id)
    result = await db.execute(query)
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404)
    
    # Calculate progress
    progress = (job.completed_count / job.target_count * 100) if job.target_count > 0 else 0
    
    return {
        "id": str(job.id),
        "scope": job.scope,
        "status": job.status,
        "progress": progress,
        "servers": {
            "target": job.target_count,
            "completed": job.completed_count,
            "failed": job.failed_count,
        },
        "strategy": job.strategy,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "current_wave": job.current_wave,
        "total_waves": job.total_waves,
        "changelog": job.changelog[-10:],  # Last 10 events
    }


# ============================================================================
# ROLLBACK UPDATE
# ============================================================================

@router.post("/jobs/{job_id}/rollback")
async def rollback_update_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """Rollback completed update job"""
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403)
    
    query = select(UpdateJob).where(UpdateJob.id == job_id)
    result = await db.execute(query)
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404)
    
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Can only rollback completed jobs")
    
    update_service = UpdateService(db)
    
    rollback_job = await update_service.create_rollback_job(job)
    
    return {
        "status": "rollback_initiated",
        "original_job_id": str(job.id),
        "rollback_job_id": str(rollback_job.id),
    }
```

---

## IV. DATABASE UPDATES & MIGRATIONS

### 4.1 Update-Related Schema Changes

**File:** `backend/alembic/versions/002_update_management.py`

```python
"""
Add update management tables and fields
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade():
    """Create update management tables"""
    
    # Add scope to agents table
    op.add_column('agents', sa.Column('scope', sa.String(50), default='prod'))
    op.create_index('idx_agent_scope', 'agents', ['scope'])
    
    # Add CVE fields to agents
    op.add_column('agents', sa.Column('cve_count', sa.Integer, default=0))
    op.add_column('agents', sa.Column('cve_last_scan', sa.DateTime))
    
    # Update packages table
    op.add_column('packages', sa.Column('source', sa.String(255)))
    op.add_column('packages', sa.Column('is_security_update', sa.Boolean, default=False))
    op.add_column('packages', sa.Column('installed_date', sa.DateTime))
    
    # Create repositories table
    op.create_table(
        'repositories',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agents.id')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('type', sa.String(50)),  # apt, dnf, yum
        sa.Column('url', sa.String(512)),
        sa.Column('enabled', sa.Boolean, default=True),
        sa.Column('package_count', sa.Integer, default=0),
        sa.Column('last_update', sa.DateTime),
        sa.Column('created_at', sa.DateTime, default=sa.func.now()),
        sa.Index('idx_repo_agent_id', 'agent_id'),
    )
    
    # Create update policies table
    op.create_table(
        'update_policies',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('scope', sa.String(50), nullable=False),
        sa.Column('security_only', sa.Boolean, default=False),
        sa.Column('include_minor', sa.Boolean, default=True),
        sa.Column('include_major', sa.Boolean, default=False),
        sa.Column('auto_update_enabled', sa.Boolean, default=True),
        sa.Column('update_strategy', sa.String(50)),  # immediate, staged, canary
        sa.Column('staging_wave_hours', sa.Integer, default=24),
        sa.Column('requires_approval', sa.Boolean, default=False),
        sa.Column('auto_reboot_if_required', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime, default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, default=sa.func.now()),
    )
    
    # Create update jobs table
    op.create_table(
        'update_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('scope', sa.String(50), nullable=False),
        sa.Column('strategy', sa.String(50)),
        sa.Column('target_count', sa.Integer),
        sa.Column('completed_count', sa.Integer, default=0),
        sa.Column('failed_count', sa.Integer, default=0),
        sa.Column('status', sa.String(50)),  # pending, running, completed, failed
        sa.Column('current_wave', sa.Integer, default=0),
        sa.Column('total_waves', sa.Integer, default=1),
        sa.Column('package_filter', sa.String(255)),
        sa.Column('security_only', sa.Boolean, default=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True)),
        sa.Column('created_at', sa.DateTime, default=sa.func.now()),
        sa.Column('started_at', sa.DateTime),
        sa.Column('completed_at', sa.DateTime),
        sa.Index('idx_update_job_scope', 'scope'),
        sa.Index('idx_update_job_status', 'status'),
    )
    
    # Create update job results (per server)
    op.create_table(
        'update_job_results',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('job_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('update_jobs.id')),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agents.id')),
        sa.Column('status', sa.String(50)),  # pending, running, completed, failed
        sa.Column('packages_updated', sa.Integer, default=0),
        sa.Column('exit_code', sa.Integer),
        sa.Column('output', sa.Text),
        sa.Column('error_message', sa.Text),
        sa.Column('started_at', sa.DateTime),
        sa.Column('completed_at', sa.DateTime),
        sa.Index('idx_update_result_job_id', 'job_id'),
        sa.Index('idx_update_result_agent_id', 'agent_id'),
    )

def downgrade():
    """Rollback update management tables"""
    op.drop_table('update_job_results')
    op.drop_table('update_jobs')
    op.drop_table('update_policies')
    op.drop_table('repositories')
    op.drop_column('packages', 'installed_date')
    op.drop_column('packages', 'is_security_update')
    op.drop_column('packages', 'source')
    op.drop_column('agents', 'cve_last_scan')
    op.drop_column('agents', 'cve_count')
    op.drop_column('agents', 'scope')
```

---

## V. FRONTEND DASHBOARDS

### 5.1 Server Management Dashboard

**File:** `frontend/pages/servers/index.vue`

```vue
<template>
  <div class="container-max py-8">
    <!-- Page Header -->
    <div class="mb-8">
      <h1 class="text-3xl font-bold">Server Inventory</h1>
      <p class="text-muted-foreground">{{ servers.length }} servers with agent installed</p>
    </div>

    <!-- Filters -->
    <div class="grid grid-cols-4 gap-4 mb-8">
      <div>
        <label class="text-sm font-medium">Status</label>
        <select v-model="filters.status" class="w-full border rounded-md px-3 py-2">
          <option value="">All</option>
          <option value="ACTIVE">Active</option>
          <option value="INACTIVE">Inactive</option>
          <option value="UNHEALTHY">Unhealthy</option>
        </select>
      </div>
      
      <div>
        <label class="text-sm font-medium">Scope</label>
        <select v-model="filters.scope" class="w-full border rounded-md px-3 py-2">
          <option value="">All</option>
          <option value="prod">Production</option>
          <option value="stage">Staging</option>
          <option value="dev">Development</option>
          <option value="uat">UAT</option>
        </select>
      </div>
      
      <div>
        <label class="text-sm font-medium">OS</label>
        <select v-model="filters.os" class="w-full border rounded-md px-3 py-2">
          <option value="">All</option>
          <option value="ubuntu">Ubuntu</option>
          <option value="debian">Debian</option>
          <option value="rhel">RHEL</option>
          <option value="rocky">Rocky</option>
        </select>
      </div>
      
      <div>
        <label class="text-sm font-medium">Updates Available</label>
        <select v-model="filters.has_updates" class="w-full border rounded-md px-3 py-2">
          <option value="">All</option>
          <option value="true">Has Updates</option>
          <option value="false">No Updates</option>
        </select>
      </div>
    </div>

    <!-- Server Grid -->
    <div class="grid gap-4">
      <div
        v-for="server in filteredServers"
        :key="server.agent_id"
        class="border rounded-lg p-4 hover:shadow-md transition-shadow cursor-pointer"
        @click="goToDetail(server.agent_id)"
      >
        <div class="grid grid-cols-5 gap-4">
          <!-- Hostname -->
          <div>
            <h3 class="font-semibold">{{ server.hostname }}</h3>
            <p class="text-sm text-muted-foreground">{{ server.agent_id.slice(0, 8) }}</p>
          </div>
          
          <!-- OS & Kernel -->
          <div>
            <p class="text-sm font-medium">{{ server.os_distro }} {{ server.os_version }}</p>
            <p class="text-xs text-muted-foreground">{{ server.kernel }}</p>
          </div>
          
          <!-- Scope -->
          <div>
            <span :class="['px-2 py-1 rounded text-sm font-medium', scopeClass(server.scope)]">
              {{ server.scope.toUpperCase() }}
            </span>
            <p class="text-xs text-muted-foreground mt-1">{{ server.arch }}</p>
          </div>
          
          <!-- Status -->
          <div>
            <div :class="['flex items-center gap-2', statusColor(server.status)]">
              <div class="w-3 h-3 rounded-full" :class="statusDotColor(server.status)"></div>
              <span class="text-sm font-medium">{{ server.status }}</span>
            </div>
            <p class="text-xs text-muted-foreground mt-1">
              {{ formatTime(server.last_heartbeat) }}
            </p>
          </div>
          
          <!-- Updates & CVE -->
          <div class="text-right">
            <div class="flex justify-end gap-2 mb-2">
              <span v-if="server.updates_available > 0" class="bg-orange-100 text-orange-800 px-2 py-1 rounded text-xs font-medium">
                {{ server.updates_available }} updates
              </span>
              <span v-if="server.cve_count > 0" class="bg-red-100 text-red-800 px-2 py-1 rounded text-xs font-medium">
                {{ server.cve_count }} CVE
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const servers = ref([])
const filters = ref({
  status: '',
  scope: '',
  os: '',
  has_updates: '',
})

onMounted(async () => {
  const response = await $fetch('/api/v1/servers')
  servers.value = response.servers
})

const filteredServers = computed(() => {
  return servers.value.filter(s => {
    if (filters.value.status && s.status !== filters.value.status) return false
    if (filters.value.scope && s.scope !== filters.value.scope) return false
    if (filters.value.os && !s.os_distro.toLowerCase().includes(filters.value.os)) return false
    if (filters.value.has_updates && (s.updates_available > 0) !== (filters.value.has_updates === 'true')) return false
    return true
  })
})

const formatTime = (date) => {
  if (!date) return 'Never'
  const diff = Date.now() - new Date(date).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'Just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

const scopeClass = (scope) => {
  const classes = {
    prod: 'bg-red-100 text-red-800',
    stage: 'bg-yellow-100 text-yellow-800',
    dev: 'bg-blue-100 text-blue-800',
    uat: 'bg-purple-100 text-purple-800',
  }
  return classes[scope] || 'bg-gray-100 text-gray-800'
}

const statusColor = (status) => {
  const colors = {
    ACTIVE: 'text-green-600',
    INACTIVE: 'text-gray-600',
    UNHEALTHY: 'text-red-600',
  }
  return colors[status] || 'text-gray-600'
}

const statusDotColor = (status) => {
  const colors = {
    ACTIVE: 'bg-green-500',
    INACTIVE: 'bg-gray-500',
    UNHEALTHY: 'bg-red-500',
  }
  return colors[status] || 'bg-gray-500'
}

const goToDetail = (agentId) => {
  router.push(`/servers/${agentId}`)
}
</script>
```

### 5.2 Update Management Dashboard

**File:** `frontend/pages/updates/index.vue`

```vue
<template>
  <div class="container-max py-8">
    <!-- Header -->
    <div class="mb-8">
      <h1 class="text-3xl font-bold">Update Management</h1>
      <p class="text-muted-foreground">Centralized updates across all scopes</p>
    </div>

    <!-- Create Update Job -->
    <div class="bg-card border rounded-lg p-6 mb-8">
      <h2 class="text-lg font-semibold mb-4">Create Update Job</h2>
      
      <form @submit.prevent="createUpdateJob" class="space-y-4">
        <div class="grid grid-cols-2 gap-4">
          <!-- Scope Selection -->
          <div>
            <label class="text-sm font-medium">Scope</label>
            <select v-model="newJob.scope" class="w-full border rounded-md px-3 py-2">
              <option value="">Select scope...</option>
              <option value="prod">Production</option>
              <option value="stage">Staging</option>
              <option value="dev">Development</option>
              <option value="uat">UAT</option>
              <option value="project-all">All Projects</option>
            </select>
          </div>
          
          <!-- Update Type -->
          <div>
            <label class="text-sm font-medium">Update Type</label>
            <select v-model="newJob.security_only" class="w-full border rounded-md px-3 py-2">
              <option :value="false">All Updates</option>
              <option :value="true">Security Only</option>
            </select>
          </div>
        </div>
        
        <!-- Package Filter -->
        <div>
          <label class="text-sm font-medium">Package Filter (optional)</label>
          <input
            v-model="newJob.package_filter"
            type="text"
            placeholder="e.g., kernel, openssl"
            class="w-full border rounded-md px-3 py-2"
          />
        </div>
        
        <!-- Buttons -->
        <div class="flex gap-4">
          <button
            type="button"
            @click="dryRunUpdateJob"
            class="px-4 py-2 border rounded-md hover:bg-muted"
          >
            Dry Run (Preview)
          </button>
          <button
            type="submit"
            class="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
          >
            Execute Update
          </button>
        </div>
      </form>
    </div>

    <!-- Update Jobs -->
    <div class="space-y-4">
      <h2 class="text-lg font-semibold">Update Jobs</h2>
      
      <div
        v-for="job in updateJobs"
        :key="job.id"
        class="border rounded-lg p-4 space-y-4"
      >
        <div class="flex items-center justify-between">
          <div>
            <h3 class="font-semibold">{{ job.scope.toUpperCase() }} Updates</h3>
            <p class="text-sm text-muted-foreground">{{ job.created_at }}</p>
          </div>
          
          <span :class="['px-3 py-1 rounded-full text-sm font-medium', jobStatusClass(job.status)]">
            {{ job.status }}
          </span>
        </div>
        
        <!-- Progress -->
        <div>
          <div class="flex justify-between mb-2">
            <span class="text-sm">Progress</span>
            <span class="text-sm font-medium">{{ job.progress }}%</span>
          </div>
          <div class="w-full bg-gray-200 rounded-full h-2">
            <div
              class="bg-primary h-2 rounded-full"
              :style="{ width: `${job.progress}%` }"
            ></div>
          </div>
        </div>
        
        <!-- Stats -->
        <div class="grid grid-cols-4 gap-4 text-sm">
          <div>
            <p class="text-muted-foreground">Target</p>
            <p class="font-semibold">{{ job.servers.target }}</p>
          </div>
          <div>
            <p class="text-muted-foreground">Completed</p>
            <p class="font-semibold text-green-600">{{ job.servers.completed }}</p>
          </div>
          <div>
            <p class="text-muted-foreground">Failed</p>
            <p class="font-semibold text-red-600">{{ job.servers.failed }}</p>
          </div>
          <div>
            <p class="text-muted-foreground">Wave</p>
            <p class="font-semibold">{{ job.current_wave }}/{{ job.total_waves }}</p>
          </div>
        </div>
        
        <!-- Actions -->
        <div class="flex gap-2">
          <button
            class="px-3 py-2 text-sm border rounded-md hover:bg-muted"
            @click="showJobDetails(job.id)"
          >
            View Details
          </button>
          
          <button
            v-if="job.status === 'completed'"
            class="px-3 py-2 text-sm bg-red-100 text-red-800 rounded-md hover:bg-red-200"
            @click="rollbackJob(job.id)"
          >
            Rollback
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

const newJob = ref({
  scope: '',
  security_only: false,
  package_filter: '',
})

const updateJobs = ref([])

onMounted(async () => {
  // Load update jobs
})

const dryRunUpdateJob = async () => {
  const response = await $fetch(`/api/v1/updates/execute/${newJob.value.scope}`, {
    method: 'POST',
    query: {
      security_only: newJob.value.security_only,
      dry_run: true,
      package_filter: newJob.value.package_filter,
    },
  })
  
  alert(`Dry Run: ${response.servers_affected} servers, ${response.packages_to_update} packages`)
}

const createUpdateJob = async () => {
  const response = await $fetch(`/api/v1/updates/execute/${newJob.value.scope}`, {
    method: 'POST',
    body: {
      security_only: newJob.value.security_only,
      package_filter: newJob.value.package_filter,
    },
  })
  
  // Add to list
  updateJobs.value.push(response)
  
  // Reset form
  newJob.value = { scope: '', security_only: false, package_filter: '' }
}

const rollbackJob = async (jobId) => {
  await $fetch(`/api/v1/updates/jobs/${jobId}/rollback`, {
    method: 'POST',
  })
  
  alert('Rollback initiated')
}

const showJobDetails = (jobId) => {
  // Navigate to job detail page
}

const jobStatusClass = (status) => {
  const classes = {
    pending: 'bg-blue-100 text-blue-800',
    running: 'bg-yellow-100 text-yellow-800',
    completed: 'bg-green-100 text-green-800',
    failed: 'bg-red-100 text-red-800',
  }
  return classes[status] || 'bg-gray-100 text-gray-800'
}
</script>
```

---

## VI. OPTIMIZATION & SECURITY RECOMMENDATIONS

### 6.1 Agent Optimization

```
✅ HEARTBEAT OPTIMIZATION:
├─ Use persistent gRPC stream (not polling)
├─ Delta sync: only send changed data
├─ Compress payloads (gzip > 1KB)
├─ Local caching: reduce agent CPU
└─ Exponential backoff on failure

✅ NETWORK EFFICIENCY:
├─ Package list delta sync (not full list)
├─ Repository info cached (48h)
├─ Metrics batching (5 min intervals)
├─ Offline queue (local SQLite)
└─ Bandwidth limiting per policy

✅ SECURITY HARDENING:
├─ mTLS mutual authentication
├─ Certificate pinning
├─ Command whitelist enforcement
├─ Job sandboxing (namespace/cgroup)
├─ Audit all job execution
└─ No shell access, no terminal emulation
```

### 6.2 API Optimization

```
✅ CACHING STRATEGY:
├─ Server list: 5 minutes
├─ Server detail: 5 minutes
├─ Repository info: 24 hours
├─ CVE database: 24 hours
├─ Update policies: 1 hour
└─ Cache invalidation on changes

✅ DATABASE OPTIMIZATION:
├─ Indexes on: agent_id, status, scope, heartbeat
├─ Partitioning: jobs by month
├─ Archive: audit logs > 1 year
├─ Connection pooling: 20 connections
└─ Query optimization: explain analyze

✅ API RATE LIMITING:
├─ Per-user: 1000 req/min
├─ Per-IP: 10000 req/min
├─ Agent endpoints: 100 req/min
└─ Exponential backoff
```

### 6.3 Security Best Practices

```
✅ RBAC LEVELS:
├─ Admin: all operations
├─ Manager: create jobs, policies
├─ Operator: execute jobs, view inventory
└─ Viewer: read-only access

✅ AUDIT LOGGING:
├─ All API calls (user, action, resource)
├─ All job executions (command, output, exit code)
├─ All config changes (before/after)
├─ All access to sensitive data
└─ Retention: 2 years

✅ ENCRYPTION:
├─ At-rest: database encryption
├─ In-transit: mTLS for all connections
├─ Credentials: AES-256 in database
├─ Backups: encrypted, offline storage
└─ Key rotation: annual

✅ FIREWALL & NETWORK:
├─ Agent: outbound-only communication
├─ API: behind reverse proxy (NGINX)
├─ Database: private network
├─ Cache: private network
└─ No direct internet access
```

---

## VII. COMPLETE ARCHITECTURE CHECKLIST

### ✅ Phase 1: Core Platform (Weeks 1-4)
```
Backend:
  ✓ FastAPI app structure
  ✓ PostgreSQL schema + migrations
  ✓ Redis caching layer
  ✓ Authentication/RBAC
  ✓ Basic API routes (servers, packages)
  ✓ Heartbeat streaming (gRPC)
  
Frontend:
  ✓ Nuxt 4 setup + routing
  ✓ Server list page
  ✓ Server detail page (with packages/repos)
  ✓ Admin panel skeleton
  
Agent:
  ✓ Go binary structure
  ✓ gRPC client implementation
  ✓ System info collector
  ✓ Package manager module
  ✓ Heartbeat loop
  ✓ Local cache (SQLite)
  
Infrastructure:
  ✓ docker-compose.yml
  ✓ .env configuration template
  ✓ Database initialization script
  ✓ Certificate generation script
```

### ✅ Phase 2: Update Management (Weeks 5-8)
```
Backend:
  ✓ Update policy service
  ✓ Update job engine
  ✓ Staged/canary strategies
  ✓ Rollback mechanism
  ✓ Repository info tracking
  ✓ Update job APIs
  ✓ Update status streaming
  
Frontend:
  ✓ Update management dashboard
  ✓ Job creation wizard
  ✓ Job status monitoring
  ✓ Server scope filtering
  ✓ Dry-run preview
  
Agent:
  ✓ Repository management module
  ✓ Package update executor
  ✓ Job execution sandbox
  ✓ Rollback support
  ✓ Post-update hook
  
Infrastructure:
  ✓ Update job database tables
  ✓ Kubernetes manifests for scaling
```

### ✅ Phase 3: Vulnerability Management (Weeks 9-12)
```
Backend:
  ✓ CVE database ingestion
  ✓ CVE matching engine
  ✓ Vulnerability scanning service
  ✓ Risk scoring algorithm
  ✓ Remediation recommendations
  ✓ CVE APIs
  
Frontend:
  ✓ CVE dashboard
  ✓ Vulnerability detail pages
  ✓ Remediation plan wizard
  ✓ Auto-remediation execution
  
Agent:
  ✓ Local CVE matching
  ✓ Security advisory tracking
  ✓ Vulnerability reporting
```

### ✅ Phase 4: Plugin System (Weeks 13-16)
```
Backend:
  ✓ Plugin manager service
  ✓ Plugin API endpoints
  ✓ Plugin configuration storage (encrypted)
  ✓ Plugin lifecycle hooks
  ✓ Plugin SDK
  
Frontend:
  ✓ Plugin marketplace UI
  ✓ Plugin install/enable UI
  ✓ Dynamic config forms (from JSON schema)
  ✓ Plugin status monitoring
  
Plugins:
  ✓ Zabbix connector
  ✓ Nessus scanner
  ✓ Jira ticketing
  ✓ Plugin documentation
```

### ✅ Phase 5: Monitoring & Operations (Weeks 17-20)
```
Backend:
  ✓ Metrics collection
  ✓ Alerting engine
  ✓ Notification channels
  ✓ Monitoring APIs
  
Frontend:
  ✓ Metrics dashboard
  ✓ Alert management
  ✓ Health monitoring
  ✓ Performance analytics
  
Infrastructure:
  ✓ Prometheus metrics
  ✓ Grafana dashboards
  ✓ Log aggregation (ELK/Loki)
  ✓ Distributed tracing
```

---

## VIII. RECOMMENDED NEXT STEPS

### 1️⃣ **Start with Agent Communication Protocol**
```
Create: `agent/internal/communication/protocol.proto`
Status: Define gRPC service definitions
Timeline: 1-2 days
Dependencies: None
```

### 2️⃣ **Implement Heartbeat Streaming**
```
Create: `agent/internal/communication/grpc_client.go`
Create: `agent/internal/agent/heartbeat.go`
Status: Agent sends heartbeat to platform
Timeline: 2-3 days
Dependencies: Protocol definitions
```

### 3️⃣ **Build Server Inventory APIs**
```
Create: `backend/lokilinux/api/v1/routers/servers.py`
Create: `backend/lokilinux/models/server.py`
Status: List servers, view packages/repos
Timeline: 2-3 days
Dependencies: Heartbeat receiving
```

### 4️⃣ **Build Update Management**
```
Create: `backend/lokilinux/services/update_service.py`
Create: `backend/lokilinux/api/v1/routers/updates.py`
Create: `agent/internal/modules/package_updater.go`
Status: Create update jobs by scope
Timeline: 3-5 days
Dependencies: Server inventory, agent jobs
```

### 5️⃣ **Frontend Server Management UI**
```
Create: `frontend/pages/servers/index.vue`
Create: `frontend/pages/servers/[id].vue`
Create: `frontend/pages/updates/index.vue`
Status: View servers, create update jobs
Timeline: 3-4 days
Dependencies: APIs complete
```

---

Perfect! Ai ghidul complet pentru elaborare! 🚀 Vrei să aprofundez vreo secțiune?
