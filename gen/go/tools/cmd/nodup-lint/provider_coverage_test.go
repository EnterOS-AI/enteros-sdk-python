package main

import "testing"

// The cloud-provider id constants (go.moleculesai.app/sdk/cloudprovider) are the
// SSOT for the provider LIST. Once the consumers (controlplane
// internal/cloudprovider, core workspace_compute.go) adopt the SDK, owned.yaml
// gains these symbol names so a re-introduced hardcoded provider list — the
// classic `const AWS = "aws"` re-paste — reds CI.
//
// These tests prove the lint MECHANISM covers the provider symbols, mirroring
// the existing TestOwnedTypeAndFuncFail forward-compat proof: they append the
// provider symbols to the spec in-test rather than asserting against the live
// owned.yaml, so this coverage proof is decoupled from the merge ordering (the
// live ban-list is tightened only once every consumer ships its re-export, so
// no consumer's CI goes red before it has adopted).
var providerSymbols = []string{
	"MoleculesServer", "AWS", "GCP", "Hetzner",
	"BackendLocal", "BackendAWS", "BackendGCP", "BackendHetzner",
}

func TestProviderList_RepasteFails(t *testing.T) {
	spec, err := loadOwned()
	if err != nil {
		t.Fatal(err)
	}
	spec.Symbols = append(spec.Symbols, providerSymbols...)

	dir := t.TempDir()
	// The exact shape of the old hand-pasted provider list: bare const literals.
	writeFile(t, dir, "internal/cloudprovider/cloudprovider.go",
		"package cloudprovider\nconst (\n\tAWS = \"aws\"\n\tHetzner = \"hetzner\"\n\tGCP = \"gcp\"\n\tMoleculesServer = \"molecules-server\"\n)\n")
	vs, err := run(dir, spec, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(vs) != 4 {
		t.Fatalf("expected 4 B:symbol violations for the re-pasted provider list, got %+v", vs)
	}
	for _, v := range vs {
		if v.layer != "B:symbol" {
			t.Errorf("unexpected layer %q for %+v", v.layer, v)
		}
	}
}

func TestProviderList_ReexportPasses(t *testing.T) {
	spec, err := loadOwned()
	if err != nil {
		t.Fatal(err)
	}
	spec.Symbols = append(spec.Symbols, providerSymbols...)

	dir := t.TempDir()
	// The sanctioned adoption: re-export aliases whose value is an import
	// selector (cloudprovider.X), not a re-pasted literal.
	writeFile(t, dir, "internal/cloudprovider/cloudprovider.go",
		"package cloudprovider\n"+
			"import sdkcp \"go.moleculesai.app/sdk/cloudprovider\"\n"+
			"const (\n"+
			"\tAWS = sdkcp.AWS\n"+
			"\tHetzner = sdkcp.Hetzner\n"+
			"\tGCP = sdkcp.GCP\n"+
			"\tMoleculesServer = sdkcp.MoleculesServer\n"+
			")\n")
	vs, err := run(dir, spec, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(vs) != 0 {
		t.Fatalf("re-export aliases of the provider SSOT must pass, got %+v", vs)
	}
}

// TestProviderList_UnownedUsagePasses proves the guard does NOT over-fire on the
// legitimate, ubiquitous uses of the provider VALUES (a struct field, a map key,
// a comparison) — only a const/var that RE-DECLARES an owned NAME with a literal
// trips. Without this the lint would be unusable (every `Provider: "aws"` row in
// CP would fail).
func TestProviderList_UnownedUsagePasses(t *testing.T) {
	spec, err := loadOwned()
	if err != nil {
		t.Fatal(err)
	}
	spec.Symbols = append(spec.Symbols, providerSymbols...)

	dir := t.TempDir()
	writeFile(t, dir, "use.go",
		"package p\n"+
			"type Row struct{ Provider string }\n"+
			"var r = Row{Provider: \"aws\"}\n"+
			"func f(p string) bool { return p == \"gcp\" || p == \"hetzner\" }\n"+
			"var prices = map[string]int{\"aws\": 1, \"gcp\": 2, \"hetzner\": 3}\n")
	vs, err := run(dir, spec, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(vs) != 0 {
		t.Fatalf("ubiquitous provider-value usage must pass (only re-declared owned names fail), got %+v", vs)
	}
}
