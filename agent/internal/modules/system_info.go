package modules

import (
	"bufio"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"syscall"
)

// SystemInfo holds the snapshot sent in every heartbeat.
type SystemInfo struct {
	Hostname      string
	FQDN          string
	OSFamily      string
	OSDistro      string
	OSVersion     string
	KernelVersion string
	Arch          string
	CPUCount      int
	TotalMemoryKB uint64
	FreeMemoryKB  uint64
	SwapTotalKB   uint64
	SwapFreeKB    uint64
	Disks         []DiskInfo
	SystemUsers   []string
	NetworkIfaces []NetworkIfaceInfo
	BlockDevices  []BlockDeviceInfo
	ListeningPorts []ListeningPortInfo
}

// ListeningPortInfo mirrors one `ss -tulpn` row — sockets in LISTEN state only.
type ListeningPortInfo struct {
	Protocol     string
	LocalAddress string
	LocalPort    int
	PID          int
	ProcessName  string
}

// DiskInfo describes a single mounted filesystem.
type DiskInfo struct {
	MountPoint string
	Filesystem string
	TotalBytes uint64
	UsedBytes  uint64
	FreeBytes  uint64
}

// NetworkIfaceInfo describes a single network interface.
type NetworkIfaceInfo struct {
	Name        string
	MacAddress  string
	IPAddresses []string
	IsUp        bool
	RxBytes     uint64
	TxBytes     uint64
}

// BlockDeviceInfo mirrors one `lsblk` row — flat list, ParentName links a
// partition/lvm-mapper entry back to its parent disk (empty for top-level disks).
type BlockDeviceInfo struct {
	Name       string
	Type       string
	SizeBytes  uint64
	MountPoint string
	ParentName string
}

// SystemInfoModule collects OS-level facts.
type SystemInfoModule struct{}

func NewSystemInfoModule() *SystemInfoModule { return &SystemInfoModule{} }

// Collect gathers a fresh SystemInfo snapshot.
func (m *SystemInfoModule) Collect() (*SystemInfo, error) {
	hostname, _ := os.Hostname()

	osInfo, err := parseOSRelease()
	if err != nil {
		osInfo = map[string]string{}
	}

	mem := parseMemInfo()

	return &SystemInfo{
		Hostname:      hostname,
		FQDN:          fqdn(hostname),
		OSFamily:      "linux",
		OSDistro:      osInfo["ID"],
		OSVersion:     osInfo["VERSION_ID"],
		KernelVersion: kernelVersion(),
		Arch:          runtime.GOARCH,
		CPUCount:      runtime.NumCPU(),
		TotalMemoryKB: mem["MemTotal"],
		FreeMemoryKB:  mem["MemAvailable"],
		SwapTotalKB:   mem["SwapTotal"],
		SwapFreeKB:    mem["SwapFree"],
		Disks:          allDisks(),
		SystemUsers:    systemUsers(),
		NetworkIfaces:  networkInterfaces(),
		BlockDevices:   blockDevices(),
		ListeningPorts: listeningPorts(),
	}, nil
}

// pseudoFilesystems are mount types with no real backing storage — skipped
// so disk usage only reflects actual filesystems (matches `df -h` output).
var pseudoFilesystems = map[string]bool{
	"proc": true, "sysfs": true, "devtmpfs": true, "tmpfs": true,
	"devpts": true, "cgroup": true, "cgroup2": true, "overlay": true,
	"squashfs": true, "mqueue": true, "debugfs": true, "tracefs": true,
	"configfs": true, "fusectl": true, "pstore": true, "bpf": true,
	"autofs": true, "securityfs": true, "hugetlbfs": true,
}

// allDisks parses /proc/mounts and statfs's every real filesystem — mirrors
// `df -h` output (root-only rootDisk() fallback kept for /proc-less systems).
func allDisks() []DiskInfo {
	f, err := os.Open("/proc/mounts")
	if err != nil {
		if d, derr := rootDisk(); derr == nil {
			return []DiskInfo{d}
		}
		return nil
	}
	defer f.Close()

	var disks []DiskInfo
	seenMount := map[string]bool{}
	seenDevice := map[string]bool{}
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		fields := strings.Fields(scanner.Text())
		if len(fields) < 3 {
			continue
		}
		device, mountPoint, fsType := fields[0], fields[1], fields[2]
		if pseudoFilesystems[fsType] || seenMount[mountPoint] {
			continue
		}
		// Bind mounts (systemd's PrivateTmp/ReadWritePaths sandboxing, among
		// others) share the same source device as an already-listed mount —
		// the kernel reports them as "device[/subpath]" in /proc/mounts, so
		// strip the bracketed subpath before comparing to catch the match.
		if bracket := strings.IndexByte(device, '['); bracket != -1 {
			device = device[:bracket]
		}
		if device != "none" && seenDevice[device] {
			continue
		}
		seenMount[mountPoint] = true
		seenDevice[device] = true

		var stat syscall.Statfs_t
		if err := syscall.Statfs(mountPoint, &stat); err != nil {
			continue
		}
		bsize := uint64(stat.Bsize)
		total := stat.Blocks * bsize
		if total == 0 {
			continue // skip 0-size pseudo-mounts that slipped past the type filter
		}
		free := stat.Bfree * bsize
		disks = append(disks, DiskInfo{
			MountPoint: mountPoint,
			Filesystem: fsType,
			TotalBytes: total,
			UsedBytes:  total - free,
			FreeBytes:  free,
		})
	}
	return disks
}

// fqdn resolves the fully-qualified hostname via `hostname -f`, falling back
// to the plain hostname when the command is unavailable or returns nothing
// (e.g. no reverse DNS / no domain configured).
func fqdn(hostname string) string {
	out, err := exec.Command("hostname", "-f").Output()
	if err != nil {
		return hostname
	}
	result := strings.TrimSpace(string(out))
	if result == "" {
		return hostname
	}
	return result
}

// systemUsers lists local OS accounts with UID >= 1000 and a real login shell
// (excludes service/system accounts and nologin/false shells).
func systemUsers() []string {
	f, err := os.Open("/etc/passwd")
	if err != nil {
		return nil
	}
	defer f.Close()

	var users []string
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		fields := strings.Split(scanner.Text(), ":")
		if len(fields) < 7 {
			continue
		}
		uid, err := strconv.Atoi(fields[2])
		if err != nil || uid < 1000 {
			continue
		}
		shell := fields[6]
		if strings.HasSuffix(shell, "nologin") || strings.HasSuffix(shell, "/false") {
			continue
		}
		users = append(users, fields[0])
	}
	return users
}

// parseOSRelease reads /etc/os-release into a key→value map.
func parseOSRelease() (map[string]string, error) {
	f, err := os.Open("/etc/os-release")
	if err != nil {
		return nil, err
	}
	defer f.Close()

	result := make(map[string]string)
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := scanner.Text()
		parts := strings.SplitN(line, "=", 2)
		if len(parts) != 2 {
			continue
		}
		result[parts[0]] = strings.Trim(parts[1], `"`)
	}
	return result, scanner.Err()
}

// parseMemInfo reads /proc/meminfo returning values in kB.
func parseMemInfo() map[string]uint64 {
	result := map[string]uint64{}
	f, err := os.Open("/proc/meminfo")
	if err != nil {
		return result
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		parts := strings.Fields(scanner.Text())
		if len(parts) < 2 {
			continue
		}
		key := strings.TrimSuffix(parts[0], ":")
		val, _ := strconv.ParseUint(parts[1], 10, 64)
		result[key] = val
	}
	return result
}

// kernelVersion reads the kernel release string from /proc/version.
func kernelVersion() string {
	data, err := os.ReadFile("/proc/version")
	if err != nil {
		return "unknown"
	}
	// "Linux version 5.15.0-91-generic ..."
	fields := strings.Fields(string(data))
	if len(fields) >= 3 {
		return fields[2]
	}
	return strings.TrimSpace(string(data))
}

// Health is a lightweight resource snapshot attached to each heartbeat.
type Health struct {
	CPUUsagePercent    float64
	CPUCount           int

	MemoryUsagePercent float64
	MemoryTotalBytes   uint64
	MemoryUsedBytes    uint64

	DiskUsagePercent float64
	DiskTotalBytes   uint64
	DiskUsedBytes    uint64

	SwapUsagePercent float64
	SwapTotalBytes   uint64
	SwapUsedBytes    uint64
}

// CollectHealth derives a resource snapshot from the same data Collect()
// already gathers (mem/disk) plus /proc/loadavg for a CPU proxy.
//
// ponytail: load-average-over-cpu-count is a proxy for CPU busy%, not a true
// sampled delta from /proc/stat — good enough for the dashboard's "is this
// host under load" signal. Upgrade to a real /proc/stat delta if the
// dashboard ever needs precise CPU%.
func (m *SystemInfoModule) CollectHealth(info *SystemInfo) Health {
	h := Health{CPUCount: info.CPUCount}

	if info.TotalMemoryKB > 0 {
		h.MemoryTotalBytes = info.TotalMemoryKB * 1024
		h.MemoryUsedBytes = (info.TotalMemoryKB - info.FreeMemoryKB) * 1024
		h.MemoryUsagePercent = float64(h.MemoryUsedBytes) / float64(h.MemoryTotalBytes) * 100
	}

	if info.SwapTotalKB > 0 {
		h.SwapTotalBytes = info.SwapTotalKB * 1024
		h.SwapUsedBytes = (info.SwapTotalKB - info.SwapFreeKB) * 1024
		h.SwapUsagePercent = float64(h.SwapUsedBytes) / float64(h.SwapTotalBytes) * 100
	}

	for _, d := range info.Disks {
		if d.MountPoint == "/" && d.TotalBytes > 0 {
			h.DiskTotalBytes = d.TotalBytes
			h.DiskUsedBytes = d.UsedBytes
			h.DiskUsagePercent = float64(d.UsedBytes) / float64(d.TotalBytes) * 100
			break
		}
	}

	if load, err := loadAvg1(); err == nil && info.CPUCount > 0 {
		pct := load / float64(info.CPUCount) * 100
		if pct > 100 {
			pct = 100
		}
		h.CPUUsagePercent = pct
	}

	return h
}

// loadAvg1 reads the 1-minute load average from /proc/loadavg.
func loadAvg1() (float64, error) {
	data, err := os.ReadFile("/proc/loadavg")
	if err != nil {
		return 0, err
	}
	fields := strings.Fields(string(data))
	if len(fields) == 0 {
		return 0, os.ErrInvalid
	}
	return strconv.ParseFloat(fields[0], 64)
}

// rootDisk returns disk usage for the root filesystem via syscall.Statfs.
func rootDisk() (DiskInfo, error) {
	var stat syscall.Statfs_t
	if err := syscall.Statfs("/", &stat); err != nil {
		return DiskInfo{}, err
	}
	bsize := uint64(stat.Bsize)
	total := stat.Blocks * bsize
	free := stat.Bfree * bsize
	return DiskInfo{
		MountPoint: "/",
		TotalBytes: total,
		UsedBytes:  total - free,
		FreeBytes:  free,
	}, nil
}

// networkInterfaces lists real network interfaces (loopback excluded) with
// their IPs and byte counters from /sys/class/net/<iface>/statistics.
func networkInterfaces() []NetworkIfaceInfo {
	ifaces, err := net.Interfaces()
	if err != nil {
		return nil
	}

	var result []NetworkIfaceInfo
	for _, iface := range ifaces {
		if iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		var ips []string
		if addrs, err := iface.Addrs(); err == nil {
			for _, a := range addrs {
				ips = append(ips, a.String())
			}
		}
		result = append(result, NetworkIfaceInfo{
			Name:        iface.Name,
			MacAddress:  iface.HardwareAddr.String(),
			IPAddresses: ips,
			IsUp:        iface.Flags&net.FlagUp != 0,
			RxBytes:     readIfaceCounter(iface.Name, "rx_bytes"),
			TxBytes:     readIfaceCounter(iface.Name, "tx_bytes"),
		})
	}
	return result
}

func readIfaceCounter(name, counter string) uint64 {
	data, err := os.ReadFile(fmt.Sprintf("/sys/class/net/%s/statistics/%s", name, counter))
	if err != nil {
		return 0
	}
	v, _ := strconv.ParseUint(strings.TrimSpace(string(data)), 10, 64)
	return v
}

// lsblkDevice mirrors the JSON shape of `lsblk -J -b -o NAME,SIZE,TYPE,MOUNTPOINT`.
type lsblkDevice struct {
	Name       string        `json:"name"`
	Size       json.Number   `json:"size"`
	Type       string        `json:"type"`
	MountPoint string        `json:"mountpoint"`
	Children   []lsblkDevice `json:"children,omitempty"`
}

// blockDevices shells out to `lsblk` (util-linux, present on all mainstream
// distros) and flattens its device tree into a parent-linked list.
func blockDevices() []BlockDeviceInfo {
	out, err := exec.Command("lsblk", "-J", "-b", "-o", "NAME,SIZE,TYPE,MOUNTPOINT").Output()
	if err != nil {
		return nil
	}
	var parsed struct {
		BlockDevices []lsblkDevice `json:"blockdevices"`
	}
	if err := json.Unmarshal(out, &parsed); err != nil {
		return nil
	}

	var flatten func(devs []lsblkDevice, parent string) []BlockDeviceInfo
	flatten = func(devs []lsblkDevice, parent string) []BlockDeviceInfo {
		var result []BlockDeviceInfo
		for _, d := range devs {
			size, _ := d.Size.Int64()
			result = append(result, BlockDeviceInfo{
				Name:       d.Name,
				Type:       d.Type,
				SizeBytes:  uint64(size),
				MountPoint: d.MountPoint,
				ParentName: parent,
			})
			result = append(result, flatten(d.Children, d.Name)...)
		}
		return result
	}
	return flatten(parsed.BlockDevices, "")
}

// ListeningPorts exports listeningPorts for reuse by the compliance
// package's open_ports collector — same scan, same data, so a compliance
// rule and the fleet dashboard never see diverging results.
func ListeningPorts() []ListeningPortInfo { return listeningPorts() }

// listeningPorts parses /proc/net/{tcp,tcp6,udp,udp6} for sockets in LISTEN
// state (TCP: st==0A; UDP is connectionless so any bound socket counts —
// mirrors `ss -tulpn`'s UNCONN rows), then resolves each socket inode to its
// owning process via /proc/*/fd symlinks. No shelling out to `ss` — it may
// not be present or reachable under systemd sandboxing.
func listeningPorts() []ListeningPortInfo {
	inodeToPID := buildInodeToPIDMap()

	var ports []ListeningPortInfo
	specs := []struct {
		path     string
		protocol string
		listenSt string
	}{
		{"/proc/net/tcp", "tcp", "0A"},
		{"/proc/net/tcp6", "tcp", "0A"},
		{"/proc/net/udp", "udp", "07"},
		{"/proc/net/udp6", "udp", "07"},
	}
	for _, spec := range specs {
		ports = append(ports, parseProcNet(spec.path, spec.protocol, spec.listenSt, inodeToPID)...)
	}
	return ports
}

func parseProcNet(path, protocol, listenState string, inodeToPID map[string][2]string) []ListeningPortInfo {
	f, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer f.Close()

	var result []ListeningPortInfo
	scanner := bufio.NewScanner(f)
	scanner.Scan() // header line
	for scanner.Scan() {
		fields := strings.Fields(scanner.Text())
		if len(fields) < 10 {
			continue
		}
		if fields[3] != listenState {
			continue
		}
		addr, port, err := parseHexAddrPort(fields[1])
		if err != nil {
			continue
		}
		inode := fields[9]
		pid, name := "", ""
		if p, ok := inodeToPID[inode]; ok {
			pid, name = p[0], p[1]
		}
		pidNum, _ := strconv.Atoi(pid)
		result = append(result, ListeningPortInfo{
			Protocol:     protocol,
			LocalAddress: addr,
			LocalPort:    port,
			PID:          pidNum,
			ProcessName:  name,
		})
	}
	return result
}

// parseHexAddrPort decodes a /proc/net/{tcp,udp}* "address:port" field —
// hex-encoded, host byte order (so bytes come out reversed vs. dotted form).
func parseHexAddrPort(field string) (string, int, error) {
	parts := strings.SplitN(field, ":", 2)
	if len(parts) != 2 {
		return "", 0, fmt.Errorf("malformed addr:port %q", field)
	}
	rawIP, err := hex.DecodeString(parts[0])
	if err != nil {
		return "", 0, err
	}
	port, err := strconv.ParseInt(parts[1], 16, 32)
	if err != nil {
		return "", 0, err
	}

	ip := make(net.IP, len(rawIP))
	// Stored as groups of 4 bytes in host (little-endian) order — reverse
	// each group to get network byte order.
	for i := 0; i < len(rawIP); i += 4 {
		end := i + 4
		if end > len(rawIP) {
			end = len(rawIP)
		}
		group := rawIP[i:end]
		for j, k := 0, len(group)-1; j < k; j, k = j+1, k-1 {
			group[j], group[k] = group[k], group[j]
		}
		copy(ip[i:end], group)
	}
	return ip.String(), int(port), nil
}

// buildInodeToPIDMap walks /proc/<pid>/fd/* once and maps each socket inode
// to [pid, process_name] — avoids an O(processes × sockets) rescan per port.
func buildInodeToPIDMap() map[string][2]string {
	result := map[string][2]string{}
	procDirs, err := os.ReadDir("/proc")
	if err != nil {
		return result
	}
	for _, entry := range procDirs {
		pid := entry.Name()
		if !entry.IsDir() {
			continue
		}
		if _, err := strconv.Atoi(pid); err != nil {
			continue // not a PID directory
		}
		fdDir := filepath.Join("/proc", pid, "fd")
		fds, err := os.ReadDir(fdDir)
		if err != nil {
			continue // permission denied or process exited — skip
		}
		var name string
		for _, fd := range fds {
			link, err := os.Readlink(filepath.Join(fdDir, fd.Name()))
			if err != nil {
				continue
			}
			if !strings.HasPrefix(link, "socket:[") {
				continue
			}
			inode := strings.TrimSuffix(strings.TrimPrefix(link, "socket:["), "]")
			if name == "" {
				name = processName(pid)
			}
			result[inode] = [2]string{pid, name}
		}
	}
	return result
}

func processName(pid string) string {
	data, err := os.ReadFile(filepath.Join("/proc", pid, "comm"))
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(data))
}
