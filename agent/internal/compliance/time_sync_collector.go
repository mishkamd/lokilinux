package compliance

import (
	"context"
	"errors"
	"os/exec"
	"strings"
	"time"
)

// TimeSyncCollector captures `timedatectl` (universal on systemd hosts —
// reports which NTP implementation is active and whether it's
// synchronized) plus `chronyc tracking` detail when chrony specifically is
// the active implementation, since chrony exposes offset/stratum detail
// timedatectl's summary doesn't.
type TimeSyncCollector struct{}

func NewTimeSyncCollector() *TimeSyncCollector { return &TimeSyncCollector{} }

func (c *TimeSyncCollector) Domain() string { return "time_sync" }

func (c *TimeSyncCollector) Interval() time.Duration { return 0 }

func (c *TimeSyncCollector) Collect(ctx context.Context) (Facts, error) {
	facts := Facts{}

	out, err := exec.CommandContext(ctx, "timedatectl").Output()
	if err != nil {
		return nil, err
	}
	facts["timedatectl"] = strings.TrimSpace(string(out))

	out, err = exec.CommandContext(ctx, "chronyc", "tracking").Output()
	var execErr *exec.Error
	switch {
	case err == nil:
		facts["chrony_tracking"] = strings.TrimSpace(string(out))
	case errors.As(err, &execErr):
		// chrony not installed — systemd-timesyncd or ntpd handles sync instead
	default:
		return nil, err
	}

	return facts, nil
}
