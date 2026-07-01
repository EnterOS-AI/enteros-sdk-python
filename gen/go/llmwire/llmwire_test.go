package llmwire

import "testing"

// These tests pin the wire values. The values are a cross-repo contract (JSON
// fields, DB CHECK constraints, injected env keys); a change here is a breaking
// change for every consumer and MUST be a deliberate, reviewed edit — hence the
// explicit literal assertions rather than tautological self-comparisons.
func TestBillingModeWireValues(t *testing.T) {
	cases := map[string]string{
		LLMBillingModePlatformManaged: "platform_managed",
		LLMBillingModeBYOK:            "byok",
		LLMBillingModeDisabled:        "disabled",
	}
	for got, want := range cases {
		if got != want {
			t.Errorf("billing mode wire value drift: got %q want %q", got, want)
		}
	}
}

func TestRoutingModeWireValues(t *testing.T) {
	cases := map[string]string{
		LLMModePlatform: "platform",
		LLMModeByok:     "byok",
		LLMModeFaithful: "faithful",
	}
	for got, want := range cases {
		if got != want {
			t.Errorf("routing mode wire value drift: got %q want %q", got, want)
		}
	}
}

func TestModelEnvNames(t *testing.T) {
	cases := map[string]string{
		EnvModel:                   "MODEL",
		EnvMoleculeModel:           "MOLECULE_MODEL",
		EnvMoleculeLLMDefaultModel: "MOLECULE_LLM_DEFAULT_MODEL",
		EnvAnthropicSmallFastModel: "ANTHROPIC_SMALL_FAST_MODEL",
	}
	for got, want := range cases {
		if got != want {
			t.Errorf("model env name drift: got %q want %q", got, want)
		}
	}
}
