package modules

import "testing"

func TestClampTimeoutSeconds(t *testing.T) {
	cases := []struct {
		name string
		in   int
		want int
	}{
		{"zero uses default", 0, maxTimeoutSec},
		{"negative uses default", -5, maxTimeoutSec},
		{"within ceiling passes through", 60, 60},
		{"exactly at ceiling passes through", maxTimeoutSec, maxTimeoutSec},
		{"above ceiling clamped", 999999, maxTimeoutSec},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := clampTimeoutSeconds(tc.in); got != tc.want {
				t.Fatalf("clampTimeoutSeconds(%d) = %d, want %d", tc.in, got, tc.want)
			}
		})
	}
}
