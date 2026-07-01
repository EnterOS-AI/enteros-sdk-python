package llmwire

// LLM routing mode — the per-workspace answer to "where do this workspace's LLM
// calls go, and is the metered CP proxy injected?". These are the shared wire
// TOKENS only. The *resolver* that maps an environment identity (MOLECULE_ENV,
// LOCAL_LLM_MODE, per-tenant override) to one of these tokens is deployment
// behaviour and stays in CP (internal/provisioner/llm_mode.go LLMModeForEnv).
//
// Defined here so that if core ever needs to reason about the routing token it
// imports the SSOT rather than re-pasting the strings.
const (
	// LLMModePlatform routes a workspace through the metered CP llm_proxy
	// (MOLECULE_LLM_USAGE_TOKEN + base_url -> CP). The managed/billed path.
	LLMModePlatform = "platform"
	// LLMModeByok points the runtime DIRECTLY at the provider's
	// Anthropic-compatible endpoint with a native key and DROPS the proxy env so
	// it can't fall back through the meter. The bring-your-own-key path.
	LLMModeByok = "byok"
	// LLMModeFaithful is an EXPLICIT no-op: leave the tenant-seeded env untouched.
	// Must be requested explicitly so a production CP can never silently fall into
	// "inject nothing".
	LLMModeFaithful = "faithful"
)
