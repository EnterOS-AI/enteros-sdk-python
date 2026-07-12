package molcontracts

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestRuntimeIDIsOpenAndPathSafe(t *testing.T) {
	valid := []string{"claude-code", "claude_code", "acme-agent", "acme_agent", "constructor", "a"}
	invalid := []string{
		"", "../acme", "acme/agent", `acme\agent`, "acme agent", "acme\nagent",
		"acme\n", "acme\r", "acme\u2028", "acme\u2029",
		"Acme", "acme--agent", strings.Repeat("a", RuntimeIDMaxLength+1),
	}

	for _, runtimeID := range valid {
		if !IsValidRuntimeID(runtimeID) {
			t.Fatalf("valid runtime ID rejected: %q", runtimeID)
		}
	}
	for _, runtimeID := range invalid {
		if IsValidRuntimeID(runtimeID) {
			t.Fatalf("invalid runtime ID accepted: %q", runtimeID)
		}
	}
}

func TestNormalizeRuntimeIDPreservesCustomIDs(t *testing.T) {
	if got, ok := NormalizeRuntimeID("claude_code"); !ok || got != "claude-code" {
		t.Fatalf("alias normalization = %q, %v", got, ok)
	}
	if got, ok := NormalizeRuntimeID("acme-agent"); !ok || got != "acme-agent" {
		t.Fatalf("custom normalization = %q, %v", got, ok)
	}
	if IsOfficialRuntimeID("acme-agent") {
		t.Fatal("custom runtime reported as official")
	}
}

func TestOpenOrgDefaultsPreserveHeterogeneousKeys(t *testing.T) {
	defaults := map[string]any{
		"runtime":          "acme-agent",
		"tier":             3,
		"plugins":          []string{"custom-plugin"},
		"category_routing": map[string]any{"engineering": "dev"},
	}
	values := []any{
		&OrgTemplate{Defaults: defaults},
		&CatalogEntryOrgTemplateSpec{Defaults: defaults},
	}

	for _, value := range values {
		encoded, err := json.Marshal(value)
		if err != nil {
			t.Fatal(err)
		}
		var roundTripped map[string]any
		if err := json.Unmarshal(encoded, &roundTripped); err != nil {
			t.Fatal(err)
		}
		got, ok := roundTripped["defaults"].(map[string]any)
		if !ok {
			t.Fatalf("defaults did not round-trip as an open object: %#v", roundTripped)
		}
		for key := range defaults {
			if _, ok := got[key]; !ok {
				t.Errorf("defaults key %q was dropped: %#v", key, got)
			}
		}
	}
}
