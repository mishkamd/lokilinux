package modules

import "testing"

func TestPackageUpdateCommand(t *testing.T) {
	cases := []struct {
		mgr     string
		names   []string
		want    string
		wantErr bool
	}{
		{"apt", nil, "apt-get update && apt-get upgrade -y", false},
		{"apt", []string{"nginx", "curl"}, "apt-get update && apt-get install --only-upgrade -y nginx curl", false},
		{"dnf", []string{"nginx"}, "dnf upgrade -y nginx", false},
		{"yum", nil, "yum upgrade -y", false},
		{"zypper", []string{"nginx"}, "zypper update -y nginx", false},
		{"unknown", nil, "", true},
	}
	for _, c := range cases {
		got, err := packageUpdateCommand(c.mgr, c.names)
		if c.wantErr {
			if err == nil {
				t.Errorf("packageUpdateCommand(%q, %v): expected error, got nil", c.mgr, c.names)
			}
			continue
		}
		if err != nil {
			t.Errorf("packageUpdateCommand(%q, %v): unexpected error: %v", c.mgr, c.names, err)
		}
		if got != c.want {
			t.Errorf("packageUpdateCommand(%q, %v) = %q, want %q", c.mgr, c.names, got, c.want)
		}
	}
}
