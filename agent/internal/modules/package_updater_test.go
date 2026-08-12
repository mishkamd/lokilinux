package modules

import (
	"reflect"
	"testing"
)

func TestPackageUpdateArgv(t *testing.T) {
	cases := []struct {
		mgr     string
		names   []string
		want    []string
		wantErr bool
	}{
		{"apt", nil, []string{"/bin/sh", "-c", "apt-get update && apt-get upgrade -y"}, false},
		{"apt", []string{"nginx", "curl"}, []string{"/bin/sh", "-c", `apt-get update && apt-get install --only-upgrade -y "$@"`, "--", "nginx", "curl"}, false},
		{"dnf", []string{"nginx"}, []string{"dnf", "upgrade", "-y", "nginx"}, false},
		{"yum", nil, []string{"yum", "upgrade", "-y"}, false},
		{"zypper", []string{"nginx"}, []string{"zypper", "update", "-y", "nginx"}, false},
		{"unknown", nil, nil, true},
	}
	for _, c := range cases {
		got, err := packageUpdateArgv(c.mgr, c.names)
		if c.wantErr {
			if err == nil {
				t.Errorf("packageUpdateArgv(%q, %v): expected error, got nil", c.mgr, c.names)
			}
			continue
		}
		if err != nil {
			t.Errorf("packageUpdateArgv(%q, %v): unexpected error: %v", c.mgr, c.names, err)
		}
		if !reflect.DeepEqual(got, c.want) {
			t.Errorf("packageUpdateArgv(%q, %v) = %q, want %q", c.mgr, c.names, got, c.want)
		}
	}
}

func TestPackageNameRe(t *testing.T) {
	valid := []string{"nginx", "libssl-dev", "python3.11", "pkg:amd64", "a+b"}
	invalid := []string{"nginx; rm -rf /", "curl|sh", "$(whoami)", "pkg && evil", "a b"}
	for _, n := range valid {
		if !packageNameRe.MatchString(n) {
			t.Errorf("expected %q to be a valid package name", n)
		}
	}
	for _, n := range invalid {
		if packageNameRe.MatchString(n) {
			t.Errorf("expected %q to be rejected as a package name", n)
		}
	}
}
