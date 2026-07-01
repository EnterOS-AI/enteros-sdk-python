// Package llmwire is the single source of truth (SSOT) for the small set of
// LLM-related WIRE CONSTANTS that molecule-core and molecule-controlplane must
// agree on byte-for-byte.
//
// These are *wire strings* and env-var *names* only — values that cross a
// repo/process boundary (a JSON response field, a DB CHECK-constraint value, a
// route body, an injected environment variable). They carry NO logic and NO
// deployment-specific behaviour, which is exactly why they can live in a neutral
// third module that BOTH repos import without either repo depending on the other.
//
// What is deliberately NOT here: the resolvers/charging engines that *use* these
// tokens (core's BillingModeResolution, CP's LLMModeForEnv / credits charging).
// Those are environment-specific and stay in their owning repo. Only the
// stable shared tokens move. See go.moleculesai.app/sdk for the design.
package llmwire

// LLM billing mode — the per-workspace answer to "how is this workspace's LLM
// usage paid for?". The strings are the SSOT for:
//   - core: the tenant_config response field + the workspaces.llm_billing_mode
//     column CHECK constraint + the admin route bodies.
//   - CP: internal/credits charging + the admin_workspace_billing_mode route.
//
// Historically each repo defined its own identical copy of these three strings
// (core internal/handlers/llm_billing_mode.go, CP internal/credits/llm_billing.go)
// and kept them in sync by code review — a silent-drift hazard. They are now
// defined once, here.
const (
	// LLMBillingModePlatformManaged: the platform strips vendor keys, forces the
	// metered CP llm_proxy, and bills platform credits. The default-closed mode.
	LLMBillingModePlatformManaged = "platform_managed"
	// LLMBillingModeBYOK: the workspace brings its own provider key; the platform
	// does not meter or bill its LLM usage.
	LLMBillingModeBYOK = "byok"
	// LLMBillingModeDisabled: LLM access is turned off for the workspace.
	LLMBillingModeDisabled = "disabled"
)
