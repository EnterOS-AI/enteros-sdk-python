package molcontracts

import (
	"encoding/json"
	"testing"
)

func TestProvisionRequestContractExposesFieldsInContractOrder(t *testing.T) {
	want := []string{
		"org_id",
		"workspace_id",
		"runtime",
		"template",
		"tier",
		"instance_type",
		"disk_gb",
		"provider",
		"data_persistence",
		"kind",
		"display",
		"platform_url",
		"env",
		"config_files",
		"template_assets",
	}

	if ProvisionRequest.Endpoint != ProvisionRequestEndpoint {
		t.Fatalf("ProvisionRequest.Endpoint = %q, want %q", ProvisionRequest.Endpoint, ProvisionRequestEndpoint)
	}
	if got, want := len(ProvisionRequest.Fields), len(want); got != want {
		t.Fatalf("len(ProvisionRequest.Fields) = %d, want %d", got, want)
	}
	if got, want := ProvisionRequestFieldNames, want; len(got) != len(want) {
		t.Fatalf("len(ProvisionRequestFieldNames) = %d, want %d", len(got), len(want))
	} else {
		for i := range want {
			if got[i] != want[i] {
				t.Fatalf("ProvisionRequestFieldNames[%d] = %q, want %q", i, got[i], want[i])
			}
			if _, ok := ProvisionRequest.Fields[got[i]]; !ok {
				t.Fatalf("ProvisionRequest.Fields missing %q", got[i])
			}
		}
	}
}

func TestProvisionRequestTemplateAssetsIsConsumed(t *testing.T) {
	field, ok := ProvisionRequest.Fields["template_assets"]
	if !ok {
		t.Fatal("ProvisionRequest.Fields missing template_assets")
	}
	if field.Type != "map" {
		t.Fatalf("template_assets type = %q, want map", field.Type)
	}
	if !field.CPConsumes {
		t.Fatal("template_assets must stay marked cp_consumes=true")
	}
	if field.Note == "" {
		t.Fatal("template_assets should retain the contract note documenting why it is load-bearing")
	}
}

func TestPluginManifestSchemaJSONIsLoadable(t *testing.T) {
	var schema map[string]any
	if err := json.Unmarshal([]byte(PluginManifestSchemaJSON), &schema); err != nil {
		t.Fatalf("PluginManifestSchemaJSON is not valid JSON: %v", err)
	}
	if schema["$schema"] != "https://json-schema.org/draft/2020-12/schema" {
		t.Fatalf("PluginManifestSchemaJSON $schema = %v, want draft 2020-12", schema["$schema"])
	}
	properties, ok := schema["properties"].(map[string]any)
	if !ok {
		t.Fatal("PluginManifestSchemaJSON properties missing or not an object")
	}
	if _, ok := properties["contributes"]; !ok {
		t.Fatal("PluginManifestSchemaJSON missing contributes property")
	}
}
