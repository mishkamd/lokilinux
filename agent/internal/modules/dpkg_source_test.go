package modules

import "testing"

func TestParseDpkgSources(t *testing.T) {
	// dpkg-query -W -f='${Package} ${source:Package}\n': a library whose source
	// name differs, a package whose source equals its name, and a line with no
	// source info (skipped).
	out := "libssl3 openssl\ncurl curl\nbroken\n"
	got := parseDpkgSources(out)

	if got["libssl3"] != "openssl" {
		t.Fatalf("libssl3 source = %q, want openssl", got["libssl3"])
	}
	if got["curl"] != "curl" {
		t.Fatalf("curl source = %q, want curl", got["curl"])
	}
	if _, ok := got["broken"]; ok {
		t.Fatal("a line with one field must not produce an entry")
	}
}
