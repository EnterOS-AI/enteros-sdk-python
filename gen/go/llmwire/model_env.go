package llmwire

// Model-related ENVIRONMENT VARIABLE NAMES that both repos inject into / read
// from a workspace's runtime environment. These are the variable *names* (keys),
// not their values — the values are per-workspace/per-deploy and never belong in
// the SDK.
//
// Today both repos spell these as bare string literals at their call sites
// (core workspace_provision_shared.go / platform_agent.go, CP tenant_config.go /
// provisioner). Centralising the NAMES here lets a future cleanup replace those
// scattered literals with one import so a rename is a single edit. Adopting them
// at every call site is an incremental follow-up; this file is the destination.
const (
	// EnvModel ("MODEL") — the primary model selector consumed by the runtime
	// (e.g. "openai/gpt-5.5", "minimax/MiniMax-M2").
	EnvModel = "MODEL"
	// EnvMoleculeModel ("MOLECULE_MODEL") — Molecule-namespaced model selector.
	EnvMoleculeModel = "MOLECULE_MODEL"
	// EnvMoleculeLLMDefaultModel ("MOLECULE_LLM_DEFAULT_MODEL") — the deployment
	// default model surfaced to a workspace when no explicit model is set.
	EnvMoleculeLLMDefaultModel = "MOLECULE_LLM_DEFAULT_MODEL"
	// EnvAnthropicSmallFastModel ("ANTHROPIC_SMALL_FAST_MODEL") — the small/fast
	// model the Anthropic-compatible runtime uses for cheap auxiliary calls.
	EnvAnthropicSmallFastModel = "ANTHROPIC_SMALL_FAST_MODEL"
)
