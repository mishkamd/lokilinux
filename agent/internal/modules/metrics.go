package modules

import (
	"bufio"
	"os"
	"strconv"
	"strings"
	"time"
)

// Metrics holds a point-in-time snapshot of system resource usage.
type Metrics struct {
	Timestamp   time.Time
	CPUUsage    float32 // 0-100
	MemoryUsed  uint64  // bytes
	MemoryTotal uint64  // bytes
	DiskUsed    uint64  // bytes (root fs)
	DiskTotal   uint64  // bytes (root fs)
	LoadAvg1    float64
}

// MetricsCollector gathers system metrics from /proc and syscalls.
// Stateful: CPU usage is computed as a delta from the previous call.
type MetricsCollector struct {
	prevIdle  uint64
	prevTotal uint64
}

// NewMetricsCollector primes the CPU baseline so the first Collect() reports a
// real delta instead of 0%. Cheap: one /proc/stat read at startup.
func NewMetricsCollector() *MetricsCollector {
	m := &MetricsCollector{}
	m.prevIdle, m.prevTotal, _ = readCPUStat()
	return m
}

// Collect returns a current metrics snapshot.
func (m *MetricsCollector) Collect() (*Metrics, error) {
	cpu, _ := m.cpuUsage()
	mem := parseMemInfo() // reuses system_info.go helper (same package)
	disk, _ := rootDisk() // reuses system_info.go helper (same package)

	return &Metrics{
		Timestamp:   time.Now(),
		CPUUsage:    cpu,
		MemoryUsed:  (mem["MemTotal"] - mem["MemAvailable"]) * 1024,
		MemoryTotal: mem["MemTotal"] * 1024,
		DiskUsed:    disk.UsedBytes,
		DiskTotal:   disk.TotalBytes,
		LoadAvg1:    readLoadAvg(),
	}, nil
}

// cpuUsage computes CPU % using /proc/stat jiffie delta since last call.
func (m *MetricsCollector) cpuUsage() (float32, error) {
	idle, total, err := readCPUStat()
	if err != nil {
		return 0, err
	}
	deltaIdle := idle - m.prevIdle
	deltaTotal := total - m.prevTotal
	m.prevIdle = idle
	m.prevTotal = total
	if deltaTotal == 0 {
		return 0, nil
	}
	return float32(100) * float32(deltaTotal-deltaIdle) / float32(deltaTotal), nil
}

// readCPUStat reads aggregate idle and total jiffies from /proc/stat first cpu line.
func readCPUStat() (idle, total uint64, err error) {
	f, err := os.Open("/proc/stat")
	if err != nil {
		return 0, 0, err
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := scanner.Text()
		if !strings.HasPrefix(line, "cpu ") {
			continue
		}
		// cpu user nice system idle iowait irq softirq steal guest guest_nice
		for i, fld := range strings.Fields(line)[1:] {
			v, _ := strconv.ParseUint(fld, 10, 64)
			total += v
			if i == 3 { // idle column
				idle = v
			}
		}
		return idle, total, nil
	}
	return 0, 0, nil
}

// readLoadAvg returns the 1-minute load average from /proc/loadavg.
func readLoadAvg() float64 {
	data, err := os.ReadFile("/proc/loadavg")
	if err != nil {
		return 0
	}
	fields := strings.Fields(string(data))
	if len(fields) == 0 {
		return 0
	}
	v, _ := strconv.ParseFloat(fields[0], 64)
	return v
}
