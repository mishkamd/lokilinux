package compliance

import (
	"strings"
	"testing"
)

const samplePasswdFile = `root:x:0:0:root:/root:/bin/bash
daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin
nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin
alice:x:1000:1000:Alice:/home/alice:/bin/bash
bob:x:1001:1001:Bob:/home/bob:/bin/zsh
svc-app:x:999:999:service account:/var/lib/svc-app:/bin/false
`

func TestParsePasswdFile_FiltersByUIDAndShell(t *testing.T) {
	users := parsePasswdFile(strings.NewReader(samplePasswdFile))

	if len(users) != 2 {
		t.Fatalf("users = %+v, want exactly 2 (alice, bob)", users)
	}
	names := map[string]User{}
	for _, u := range users {
		names[u.Name] = u
	}
	if _, ok := names["alice"]; !ok {
		t.Error("alice missing from filtered users")
	}
	if _, ok := names["bob"]; !ok {
		t.Error("bob missing from filtered users")
	}
	if _, ok := names["root"]; ok {
		t.Error("root (UID 0) should have been excluded")
	}
	if _, ok := names["daemon"]; ok {
		t.Error("daemon (nologin shell) should have been excluded")
	}
	if _, ok := names["svc-app"]; ok {
		t.Error("svc-app (UID<1000, /bin/false shell) should have been excluded")
	}
}

func TestParsePasswdFile_FieldsPopulatedCorrectly(t *testing.T) {
	users := parsePasswdFile(strings.NewReader(samplePasswdFile))
	var alice *User
	for i := range users {
		if users[i].Name == "alice" {
			alice = &users[i]
		}
	}
	if alice == nil {
		t.Fatal("alice not found")
	}
	if alice.UID != 1000 || alice.GID != 1000 || alice.Home != "/home/alice" || alice.Shell != "/bin/bash" {
		t.Errorf("alice = %+v, want uid=1000 gid=1000 home=/home/alice shell=/bin/bash", alice)
	}
}

func TestParsePasswdFile_MalformedLineSkipped(t *testing.T) {
	users := parsePasswdFile(strings.NewReader("not:enough:fields\nalice:x:1000:1000:Alice:/home/alice:/bin/bash\n"))
	if len(users) != 1 {
		t.Errorf("users = %+v, want exactly 1 (malformed line skipped, not a crash)", users)
	}
}

func TestParsePasswdFile_EmptyFile(t *testing.T) {
	users := parsePasswdFile(strings.NewReader(""))
	if len(users) != 0 {
		t.Errorf("users = %+v, want empty", users)
	}
}

func TestUsersCollector_ImplementsCollector(t *testing.T) {
	var _ Collector = (*UsersCollector)(nil)
	c := NewUsersCollector()
	if c.Domain() != "users" {
		t.Errorf("Domain() = %q, want users", c.Domain())
	}
}
