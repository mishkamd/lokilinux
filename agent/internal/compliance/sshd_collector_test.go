package compliance

import "testing"

// Trimmed real-shaped `sshd -T` output — lowercase directive, space-
// separated value, one per line.
const sampleSSHDOutput = `port 22
addressfamily any
listenaddress [::]:22
listenaddress 0.0.0.0:22
permitrootlogin no
pubkeyauthentication yes
passwordauthentication no
permitemptypasswords no
x11forwarding no
acceptenv lang
acceptenv lc_ctype
acceptenv lc_all
hostkey /etc/ssh/ssh_host_rsa_key
hostkey /etc/ssh/ssh_host_ed25519_key
maxauthtries 6
`

func TestParseSSHDConfig_ScalarDirectives(t *testing.T) {
	facts := parseSSHDConfig(sampleSSHDOutput)

	tests := map[string]string{
		"port":                   "22",
		"permitrootlogin":        "no",
		"pubkeyauthentication":   "yes",
		"passwordauthentication": "no",
		"x11forwarding":          "no",
		"maxauthtries":           "6",
	}
	for key, want := range tests {
		got, ok := facts[key]
		if !ok {
			t.Errorf("facts[%q] missing", key)
			continue
		}
		if got != want {
			t.Errorf("facts[%q] = %v, want %q", key, got, want)
		}
	}
}

// TestParseSSHDConfig_RepeatedDirectivesBecomeSlice covers directives that
// legitimately appear on multiple lines (listenaddress, acceptenv,
// hostkey) — these must collect into a []string, not overwrite each other,
// or a rule checking "is ed25519 among the host keys" would silently only
// ever see the last line.
func TestParseSSHDConfig_RepeatedDirectivesBecomeSlice(t *testing.T) {
	facts := parseSSHDConfig(sampleSSHDOutput)

	hostkeys, ok := facts["hostkey"].([]string)
	if !ok {
		t.Fatalf("facts[\"hostkey\"] type = %T, want []string", facts["hostkey"])
	}
	if len(hostkeys) != 2 {
		t.Fatalf("hostkey count = %d, want 2", len(hostkeys))
	}
	if hostkeys[0] != "/etc/ssh/ssh_host_rsa_key" || hostkeys[1] != "/etc/ssh/ssh_host_ed25519_key" {
		t.Errorf("hostkeys = %v, want [rsa, ed25519] in encounter order", hostkeys)
	}

	acceptenv, ok := facts["acceptenv"].([]string)
	if !ok || len(acceptenv) != 3 {
		t.Fatalf("facts[\"acceptenv\"] = %#v, want a 3-element []string", facts["acceptenv"])
	}
}

func TestParseSSHDConfig_EmptyOutput(t *testing.T) {
	facts := parseSSHDConfig("")
	if len(facts) != 0 {
		t.Errorf("parseSSHDConfig(\"\") = %v, want empty Facts", facts)
	}
}

func TestParseSSHDConfig_BlankLinesIgnored(t *testing.T) {
	facts := parseSSHDConfig("port 22\n\n\npermitrootlogin no\n")
	if len(facts) != 2 {
		t.Errorf("facts = %v, want exactly 2 entries (blank lines must not become keys)", facts)
	}
}

// TestSSHDCollector_ImplementsCollector is a compile-time-adjacent check:
// if SSHDCollector's method set ever drifts from the Collector interface,
// this line fails to compile.
func TestSSHDCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*SSHDCollector)(nil)
	c := NewSSHDCollector()
	if c.Domain() != "sshd" {
		t.Errorf("Domain() = %q, want \"sshd\"", c.Domain())
	}
	if c.Interval() != 0 {
		t.Errorf("Interval() = %v, want 0 (every heartbeat)", c.Interval())
	}
}
