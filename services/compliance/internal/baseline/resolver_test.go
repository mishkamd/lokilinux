package baseline

import (
	"testing"

	"github.com/google/uuid"

	"github.com/lokilinux/compliance/internal/storage"
)

var (
	testAgentID    = uuid.MustParse("33333333-3333-3333-3333-333333333333")
	testVersionIDs = []uuid.UUID{
		uuid.MustParse("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"),
		uuid.MustParse("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2"),
		uuid.MustParse("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3"),
	}
)

func TestSelectorMatches_EmptySelectorMatchesEverything(t *testing.T) {
	attrs := storage.AgentAttributes{AgentID: testAgentID, OsDistro: "ol", OsVersion: "9"}
	if !selectorMatches(map[string]any{}, attrs) {
		t.Fatal("empty selector (GLOBAL) must match every agent")
	}
	if !selectorMatches(nil, attrs) {
		t.Fatal("nil selector (GLOBAL) must match every agent")
	}
}

func TestSelectorMatches_OsAttributes(t *testing.T) {
	attrs := storage.AgentAttributes{OsDistro: "OracleLinux", OsVersion: "9.4"}
	cases := []struct {
		name     string
		selector map[string]any
		want     bool
	}{
		{"exact match", map[string]any{"os_distro": "OracleLinux", "os_version": "9.4"}, true},
		{"case-insensitive distro", map[string]any{"os_distro": "oraclelinux"}, true},
		{"distro mismatch", map[string]any{"os_distro": "ubuntu"}, false},
		{"version mismatch", map[string]any{"os_version": "8"}, false},
		{"partial match is not enough", map[string]any{"os_distro": "oraclelinux", "os_version": "8"}, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := selectorMatches(tc.selector, attrs); got != tc.want {
				t.Fatalf("selectorMatches(%v) = %v, want %v", tc.selector, got, tc.want)
			}
		})
	}
}

func TestSelectorMatches_CategoryAndEnvironmentAlias(t *testing.T) {
	attrs := storage.AgentAttributes{Category: "Production", Project: "BillingApi"}
	cases := []struct {
		name     string
		selector map[string]any
		want     bool
	}{
		{"category key", map[string]any{"category": "production"}, true},
		{"environment aliases to category", map[string]any{"environment": "Production"}, true},
		{"project key", map[string]any{"project": "billingapi"}, true},
		{"application aliases to project", map[string]any{"application": "BillingApi"}, true},
		{"wrong environment", map[string]any{"environment": "staging"}, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := selectorMatches(tc.selector, attrs); got != tc.want {
				t.Fatalf("selectorMatches(%v) = %v, want %v", tc.selector, got, tc.want)
			}
		})
	}
}

func TestSelectorMatches_NoSourceColumnNeverMatches(t *testing.T) {
	// role/datacenter/cluster have no column source today — documented no-op,
	// must not accidentally match.
	attrs := storage.AgentAttributes{Category: "Production", Project: "BillingApi"}
	if selectorMatches(map[string]any{"datacenter": "us-east-1"}, attrs) {
		t.Fatal("datacenter selector must not match — no source column")
	}
	if selectorMatches(map[string]any{"role": "database"}, attrs) {
		t.Fatal("role selector must not match — no source column")
	}
}

func TestSelectorMatches_NonStringValueNeverMatches(t *testing.T) {
	attrs := storage.AgentAttributes{OsDistro: "ol"}
	if selectorMatches(map[string]any{"os_distro": 9}, attrs) {
		t.Fatal("non-string selector value must never match")
	}
}

func TestDeepMergeOverwrite_PerKeyNotPerDocument(t *testing.T) {
	dst := map[string]any{
		"sshd": map[string]any{
			"PermitRootLogin":        "no",
			"PasswordAuthentication": "no",
		},
	}
	src := map[string]any{
		"sshd": map[string]any{
			"PermitRootLogin": "yes",
		},
	}
	deepMergeOverwrite(dst, src)

	sshd, ok := dst["sshd"].(map[string]any)
	if !ok {
		t.Fatalf("sshd domain lost its object shape: %#v", dst["sshd"])
	}
	if sshd["PermitRootLogin"] != "yes" {
		t.Errorf("PermitRootLogin = %v, want yes (more specific wins)", sshd["PermitRootLogin"])
	}
	if sshd["PasswordAuthentication"] != "no" {
		t.Errorf("PasswordAuthentication = %v, want no (untouched key must survive)", sshd["PasswordAuthentication"])
	}
}

func TestMergeForAgent_SpecificityOrderAndVersionChain(t *testing.T) {
	attrs := storage.AgentAttributes{OsDistro: "ol", OsVersion: "9", Category: "Production"}
	published := []storage.PublishedBaseline{
		{
			VersionID:     testVersionIDs[0],
			BaselineID:    uuid.MustParse("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1"),
			ScopeType:     "GLOBAL",
			ScopeSelector: map[string]any{},
			ExpectedState: map[string]any{
				"sshd": map[string]any{"PermitRootLogin": "no", "PasswordAuthentication": "no"},
			},
		},
		{
			VersionID:     testVersionIDs[1],
			BaselineID:    uuid.MustParse("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2"),
			ScopeType:     "OS",
			ScopeSelector: map[string]any{"os_distro": "ol", "os_version": "9"},
			ExpectedState: map[string]any{
				"sshd": map[string]any{"PermitRootLogin": "yes"},
			},
		},
		{
			VersionID:     testVersionIDs[2],
			BaselineID:    uuid.MustParse("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb3"),
			ScopeType:     "ENVIRONMENT",
			ScopeSelector: map[string]any{"environment": "production"},
			ExpectedState: map[string]any{
				"sshd": map[string]any{"PermitRootLogin": "no"},
			},
		},
		// Scoped to a different environment — must not participate.
		{
			VersionID:     uuid.MustParse("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa4"),
			BaselineID:    uuid.MustParse("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb4"),
			ScopeType:     "APPLICATION",
			ScopeSelector: map[string]any{"application": "billing"},
			ExpectedState: map[string]any{"sshd": map[string]any{"MaxAuthTries": "99"}},
		},
	}

	eff := mergeForAgent(testAgentID, attrs, published)

	sshd := eff.MergedState["sshd"].(map[string]any)
	if sshd["PermitRootLogin"] != "no" {
		t.Errorf("PermitRootLogin = %v, want no (ENVIRONMENT beats OS beats GLOBAL)", sshd["PermitRootLogin"])
	}
	if sshd["PasswordAuthentication"] != "no" {
		t.Errorf("PasswordAuthentication = %v, want no (GLOBAL key survives the merge)", sshd["PasswordAuthentication"])
	}
	if _, ok := sshd["MaxAuthTries"]; ok {
		t.Error("non-matching APPLICATION baseline must not participate")
	}

	if len(eff.BaselineVersionIDs) != 3 {
		t.Fatalf("version chain = %d entries, want 3 (GLOBAL, OS, ENVIRONMENT)", len(eff.BaselineVersionIDs))
	}
	if eff.BaselineVersionIDs[0] != testVersionIDs[0] || eff.BaselineVersionIDs[1] != testVersionIDs[1] || eff.BaselineVersionIDs[2] != testVersionIDs[2] {
		t.Errorf("version chain order wrong: %v", eff.BaselineVersionIDs)
	}
}

func TestMergeForAgent_NoMatchingBaselineGivesEmptyState(t *testing.T) {
	attrs := storage.AgentAttributes{OsDistro: "ubuntu"}
	published := []storage.PublishedBaseline{
		{
			VersionID:     testVersionIDs[0],
			ScopeType:     "OS",
			ScopeSelector: map[string]any{"os_distro": "ol"},
			ExpectedState: map[string]any{"sshd": map[string]any{"PermitRootLogin": "no"}},
		},
	}
	eff := mergeForAgent(testAgentID, attrs, published)
	if eff.MergedState == nil {
		t.Fatal("MergedState must never be nil")
	}
	if len(eff.MergedState) != 0 {
		t.Fatalf("MergedState = %v, want empty", eff.MergedState)
	}
	if len(eff.BaselineVersionIDs) != 0 {
		t.Fatalf("version chain = %v, want empty", eff.BaselineVersionIDs)
	}
}

func TestCanonicalHash_Deterministic(t *testing.T) {
	state := map[string]any{
		"sshd":   map[string]any{"PermitRootLogin": "no", "PasswordAuthentication": "no"},
		"sysctl": map[string]any{"kernel.hostname": "x"},
	}
	h1, err := canonicalHash(state)
	if err != nil {
		t.Fatalf("canonicalHash error = %v", err)
	}
	h2, err := canonicalHash(state)
	if err != nil {
		t.Fatalf("canonicalHash error = %v", err)
	}
	if h1 != h2 {
		t.Fatalf("canonicalHash not deterministic: %s vs %s", h1, h2)
	}
	if len(h1) != 64 {
		t.Fatalf("hash length = %d, want 64 (blake3 hex)", len(h1))
	}

	other := map[string]any{
		"sshd":   map[string]any{"PermitRootLogin": "yes", "PasswordAuthentication": "no"},
		"sysctl": map[string]any{"kernel.hostname": "x"},
	}
	h3, err := canonicalHash(other)
	if err != nil {
		t.Fatalf("canonicalHash error = %v", err)
	}
	if h1 == h3 {
		t.Fatal("different states must hash differently")
	}
}

func TestCanonicalHash_KeyOrderIndependent(t *testing.T) {
	// encoding/json sorts map keys — insertion order must not matter.
	a, err := canonicalHash(map[string]any{"b": 1, "a": map[string]any{"z": true, "y": false}})
	if err != nil {
		t.Fatal(err)
	}
	b, err := canonicalHash(map[string]any{"a": map[string]any{"y": false, "z": true}, "b": 1})
	if err != nil {
		t.Fatal(err)
	}
	if a != b {
		t.Fatalf("key order changed the hash: %s vs %s", a, b)
	}
}
