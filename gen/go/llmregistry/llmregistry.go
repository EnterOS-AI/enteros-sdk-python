// Package llmregistry is the single source of truth (SSOT) for the LLM
// PROVIDER / MODEL / RUNTIME registry a MoleculesAI workspace can use — the
// "which LLM vendor, which models, which agent runtime" axis.
//
// This is DELIBERATELY DISTINCT from cloudprovider (the compute-backend SSOT):
// cloudprovider answers "where does the box run" (AWS/GCP/Hetzner/local); this
// answers "which model does the agent talk to" (Anthropic/OpenAI/MiniMax/...) and
// "which runtime hosts it" (claude-code/codex/openclaw/hermes) with
// the RFC #340 narrow native model matrix.
//
// Before this package the registry was pasted independently in places that
// silently drifted: controlplane internal/providers/providers.yaml (the old
// canonical), core workspace-server internal/providers/providers.yaml (a byte
// mirror that actually drifted AHEAD), core handlers/provider_defaults.go, the
// runtime adapter_base ProviderRegistry, and every workspace-template config.yaml
// / adapter.py. This package ends that: the YAML here is canonical, and every
// consumer (core, controlplane, the runtime, the canvas) derives from it.
//
// It is wire/identity DATA only (provider ids, base-URL templates, auth-env
// names, model-prefix regexes, per-runtime native model sets) — NO routing
// logic, NO credentials, NO per-deploy behaviour — which is exactly why it can
// live in the neutral SDK that BOTH molecule-core (OSS) and molecule-controlplane
// (proprietary) import without either depending on the other. The routing logic
// that ACTS on this data (DeriveProvider / ResolveUpstream / ResolveEndpoint)
// stays in its owning repo and operates over this DATA.
package llmregistry

import _ "embed"

// RawYAML is the canonical providers/models/runtimes registry document
// (schema_version 1). Consumers parse it with their own loader+validator (e.g.
// core's providers.parseManifest) so the DATA is single-sourced here while the
// per-repo routing logic and struct methods stay in the consumer. Byte-stable:
// the contracts/llm-registry/llm-registry.yaml source is copied here verbatim by
// tools/gen-llm-registry.mjs and pinned by the codegen drift gate.
//
//go:embed llm-registry.yaml
var RawYAML []byte
