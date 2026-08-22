package modules

import "testing"

func TestSystemActionUnitCmd(t *testing.T) {
	cases := []struct {
		action string
		want   string
		ok     bool
	}{
		{"reboot", "reboot", true},
		{"shutdown", "poweroff", true},
		{"hostname", "", false},
		{"", "", false},
	}
	for _, c := range cases {
		got, ok := systemActionUnitCmd[c.action]
		if ok != c.ok {
			t.Errorf("systemActionUnitCmd[%q] ok = %v, want %v", c.action, ok, c.ok)
		}
		if got != c.want {
			t.Errorf("systemActionUnitCmd[%q] = %q, want %q", c.action, got, c.want)
		}
	}
}
