package main

import (
	"os"
	"path/filepath"
	"testing"
)

func writeFile(t *testing.T, dir, name, body string) {
	t.Helper()
	p := filepath.Join(dir, name)
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestLayerB_RepasteFails(t *testing.T) {
	spec, err := loadOwned()
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	writeFile(t, dir, "bad.go", "package p\nconst LLMBillingModeBYOK = \"byok\"\n")
	vs, err := run(dir, spec, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(vs) != 1 || vs[0].layer != "B:symbol" {
		t.Fatalf("expected 1 B:symbol violation, got %+v", vs)
	}
}

func TestLayerB_ReexportPasses(t *testing.T) {
	spec, err := loadOwned()
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	writeFile(t, dir, "good.go",
		"package p\nimport \"go.moleculesai.app/sdk/llmwire\"\nconst LLMBillingModeBYOK = llmwire.LLMBillingModeBYOK\n")
	vs, err := run(dir, spec, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(vs) != 0 {
		t.Fatalf("re-export alias must pass, got %+v", vs)
	}
}

func TestLayerB_UnownedLiteralPasses(t *testing.T) {
	// A different concept that happens to use the same wire value must NOT fire
	// (e.g. CP's capabilities.TierBYOK = "byok").
	spec, err := loadOwned()
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	writeFile(t, dir, "tier.go", "package p\nconst TierBYOK = \"byok\"\n")
	writeFile(t, dir, "cmp.go", "package p\nfunc f(m string) bool { return m == \"byok\" }\n")
	vs, err := run(dir, spec, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(vs) != 0 {
		t.Fatalf("unowned literal / comparison must pass, got %+v", vs)
	}
}

func TestAllowlistExempts(t *testing.T) {
	spec, err := loadOwned()
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	writeFile(t, dir, "internal/handlers/llm_wire_sdk.go", "package p\nconst LLMBillingModeBYOK = \"byok\"\n")
	vs, err := run(dir, spec, []string{"internal/handlers/llm_wire_sdk.go"})
	if err != nil {
		t.Fatal(err)
	}
	if len(vs) != 0 {
		t.Fatalf("allowlisted file must be exempt, got %+v", vs)
	}
}

func TestOwnedTypeAndFuncFail(t *testing.T) {
	// Forward-compat for the providers migration: owned type/func names can't be
	// re-exported as literals, so re-declaring them is always a violation.
	spec, err := loadOwned()
	if err != nil {
		t.Fatal(err)
	}
	spec.Symbols = append(spec.Symbols, "DeriveProvider", "Manifest")
	dir := t.TempDir()
	writeFile(t, dir, "a.go", "package p\ntype Manifest struct{}\nfunc DeriveProvider() {}\n")
	vs, err := run(dir, spec, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(vs) != 2 {
		t.Fatalf("expected type+func violations, got %+v", vs)
	}
}
