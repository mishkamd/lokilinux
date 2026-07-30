package compliance

import (
	"bufio"
	"context"
	"io"
	"os"
	"strings"
	"time"
)

// NetworkCollector reports DNS resolver configuration plus which network
// manager owns interface configuration (NetworkManager, netplan, or
// ifupdown). Only connection/profile *names* are read, never file
// contents — NetworkManager system-connection files and netplan configs
// can carry Wi-Fi PSKs or 802.1x credentials inline, and this collector
// has no need to ever see those.
type NetworkCollector struct{}

func NewNetworkCollector() *NetworkCollector { return &NetworkCollector{} }

func (c *NetworkCollector) Domain() string { return "network" }

func (c *NetworkCollector) Interval() time.Duration { return 0 }

func (c *NetworkCollector) Collect(ctx context.Context) (Facts, error) {
	facts := Facts{}

	if f, err := os.Open("/etc/resolv.conf"); err == nil {
		facts["resolv"] = parseResolvConf(f)
		f.Close()
	}

	switch {
	case dirExists("/etc/NetworkManager"):
		facts["manager"] = "networkmanager"
		facts["profiles"] = listDirNames("/etc/NetworkManager/system-connections")
	case dirExists("/etc/netplan"):
		facts["manager"] = "netplan"
		facts["profiles"] = listDirNames("/etc/netplan")
	case dirExists("/etc/network"):
		facts["manager"] = "ifupdown"
		facts["profiles"] = listDirNames("/etc/network/interfaces.d")
	default:
		facts["manager"] = "not_applicable"
	}

	return facts, nil
}

func dirExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

func listDirNames(path string) []string {
	entries, err := os.ReadDir(path)
	if err != nil {
		return nil
	}
	var names []string
	for _, entry := range entries {
		names = append(names, entry.Name())
	}
	return names
}

// ResolvConf is the parsed shape of /etc/resolv.conf.
type ResolvConf struct {
	Nameservers []string `json:"nameservers,omitempty"`
	Search      []string `json:"search,omitempty"`
	Options     []string `json:"options,omitempty"`
}

// parseResolvConf takes an io.Reader for testability.
func parseResolvConf(r io.Reader) ResolvConf {
	var conf ResolvConf
	scanner := bufio.NewScanner(r)
	for scanner.Scan() {
		fields := strings.Fields(scanner.Text())
		if len(fields) < 2 {
			continue
		}
		switch fields[0] {
		case "nameserver":
			conf.Nameservers = append(conf.Nameservers, fields[1])
		case "search":
			conf.Search = append(conf.Search, fields[1:]...)
		case "options":
			conf.Options = append(conf.Options, fields[1:]...)
		}
	}
	return conf
}
