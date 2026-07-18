package agent

import (
	"testing"
	"time"
)

// TestNextDelay locks the heartbeat backoff curve: base interval until 3
// consecutive failures, then exponential (1x, 2x, 4x...) capped at 5 minutes.
func TestNextDelay(t *testing.T) {
	const interval = 60 * time.Second
	cases := []struct {
		failCount int
		want      time.Duration
	}{
		{0, interval},
		{2, interval},                  // still under threshold
		{3, interval},                  // 60s << 0 = 1x
		{4, 2 * interval},              // 2x = 120s
		{5, 4 * interval},              // 4x = 240s
		{6, maxHeartbeatBackoff},       // 8x = 480s > 300s cap
		{60, maxHeartbeatBackoff},      // huge shift must not overflow to <=0
	}
	for _, c := range cases {
		m := &Manager{failCount: c.failCount}
		if got := m.nextDelay(interval); got != c.want {
			t.Errorf("nextDelay(failCount=%d) = %v, want %v", c.failCount, got, c.want)
		}
	}
}
