package cloudprovider

import (
	"reflect"
	"testing"
)

// TestCanonicalIDs pins the wire id values. These cross a repo/process boundary
// (an org row's provider column, the create/migrate API body, the app dropdown
// value, the core canvas picker) so a change here is a breaking change for every
// consumer and MUST be a deliberate, reviewed edit — hence literal assertions.
func TestCanonicalIDs(t *testing.T) {
	cases := map[string]string{
		MoleculesServer: "molecules-server",
		AWS:             "aws",
		GCP:             "gcp",
		Hetzner:         "hetzner",
	}
	for got, want := range cases {
		if got != want {
			t.Errorf("provider id wire value drift: got %q want %q", got, want)
		}
	}
}

// TestBackendKeys pins the provisioner registry backend keys. The
// Molecules-Server id maps to the historical "local" backend key (LocalDocker),
// not to its own id — that mapping is the whole reason BackendKey exists.
func TestBackendKeys(t *testing.T) {
	cases := map[string]string{
		BackendLocal:   "local",
		BackendAWS:     "aws",
		BackendGCP:     "gcp",
		BackendHetzner: "hetzner",
	}
	for got, want := range cases {
		if got != want {
			t.Errorf("backend key wire value drift: got %q want %q", got, want)
		}
	}
}

// TestMoleculesServerIncluded is the explicit guard for the principal's
// requirement: the local self-hosted box is a FIRST-CLASS, selectable member of
// the canonical list with the exact display label "Molecules-Server", routing to
// the LocalDocker ("local") backend, flagged IsLocal.
func TestMoleculesServerIncluded(t *testing.T) {
	p, ok := ByID(MoleculesServer)
	if !ok {
		t.Fatal("Molecules-Server must be a canonical provider")
	}
	if p.Display != "Molecules-Server" {
		t.Errorf("Molecules-Server display = %q, want %q", p.Display, "Molecules-Server")
	}
	if p.BackendKey != BackendLocal {
		t.Errorf("Molecules-Server backend key = %q, want %q (LocalDocker)", p.BackendKey, BackendLocal)
	}
	if !p.IsLocal {
		t.Error("Molecules-Server must be flagged IsLocal")
	}
	// It must appear in the full selectable set...
	if !contains(IDs(), MoleculesServer) {
		t.Error("Molecules-Server must be in IDs() (the selectable set)")
	}
	// ...but NOT in the cloud-billing subset.
	if contains(CloudIDs(), MoleculesServer) {
		t.Error("Molecules-Server must NOT be in CloudIDs() (it has no cloud cost)")
	}
}

func TestAllShapeConsistency(t *testing.T) {
	if len(All) != 4 {
		t.Fatalf("expected 4 providers (aws, gcp, hetzner, molecules-server), got %d", len(All))
	}
	localCount := 0
	for _, p := range All {
		if p.ID == "" || p.Display == "" || p.BackendKey == "" {
			t.Errorf("provider %+v has an empty id/display/backend key", p)
		}
		// Every backend key must be one of the canonical Backend* values.
		switch p.BackendKey {
		case BackendLocal, BackendAWS, BackendGCP, BackendHetzner:
		default:
			t.Errorf("provider %q has unknown backend key %q", p.ID, p.BackendKey)
		}
		if p.IsLocal {
			localCount++
		}
	}
	if localCount != 1 {
		t.Errorf("expected exactly one IsLocal provider (Molecules-Server), got %d", localCount)
	}
	if len(CloudIDs()) != 3 {
		t.Errorf("expected 3 cloud ids, got %v", CloudIDs())
	}
}

func TestNormalize(t *testing.T) {
	cases := map[string]string{
		"":                 AWS,             // empty → default
		"   ":              AWS,             // blank → default
		"AWS":              AWS,             // case-insensitive
		" Hetzner ":        Hetzner,         // trim + case
		"GCP":              GCP,             //
		"molecules-server": MoleculesServer, //
		"local":            MoleculesServer, // alias → canonical
		"docker":           MoleculesServer, // PROVISIONER_BACKEND alias → canonical
		"LOCAL":            MoleculesServer, // alias case-insensitive
		"fly":              "fly",           // unknown passes through (then rejected)
	}
	for in, want := range cases {
		if got := Normalize(in); got != want {
			t.Errorf("Normalize(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestBackendKeyMapping(t *testing.T) {
	cases := map[string]string{
		MoleculesServer: BackendLocal,
		"local":         BackendLocal, // alias resolves to the same backend
		"docker":        BackendLocal,
		AWS:             BackendAWS,
		"":              BackendAWS, // default → aws backend
		GCP:             BackendGCP,
		Hetzner:         BackendHetzner,
	}
	for id, want := range cases {
		got, ok := BackendKey(id)
		if !ok || got != want {
			t.Errorf("BackendKey(%q) = %q,%v want %q,true", id, got, ok, want)
		}
	}
	if _, ok := BackendKey("azure"); ok {
		t.Error("BackendKey(azure) should be ok=false (unknown provider)")
	}
}

func TestIsValidRequest(t *testing.T) {
	for _, ok := range []string{"", "   ", AWS, GCP, Hetzner, MoleculesServer, "local", "docker", "AWS"} {
		if !IsValidRequest(ok) {
			t.Errorf("IsValidRequest(%q) = false, want true", ok)
		}
	}
	for _, bad := range []string{"fly", "azure", "digitalocean"} {
		if IsValidRequest(bad) {
			t.Errorf("IsValidRequest(%q) = true, want false", bad)
		}
	}
}

func TestDisplay(t *testing.T) {
	cases := map[string]string{
		AWS:             "AWS",
		GCP:             "GCP",
		Hetzner:         "Hetzner",
		MoleculesServer: "Molecules-Server",
		"local":         "Molecules-Server", // alias resolves to the same label
	}
	for id, want := range cases {
		got, ok := Display(id)
		if !ok || got != want {
			t.Errorf("Display(%q) = %q,%v want %q,true", id, got, ok, want)
		}
	}
}

func TestCloudIDsOrderAndContent(t *testing.T) {
	if !reflect.DeepEqual(CloudIDs(), []string{AWS, GCP, Hetzner}) {
		t.Errorf("CloudIDs() = %v, want [aws gcp hetzner]", CloudIDs())
	}
	// Returned slices must be copies (mutating must not corrupt the SSOT).
	ids := IDs()
	ids[0] = "tampered"
	if IDs()[0] == "tampered" {
		t.Error("IDs() must return a fresh copy, not the backing array")
	}
}

func contains(xs []string, want string) bool {
	for _, x := range xs {
		if x == want {
			return true
		}
	}
	return false
}
