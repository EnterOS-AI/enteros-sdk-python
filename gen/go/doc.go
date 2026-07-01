// Package sdk is the module root for go.moleculesai.app/sdk — the MoleculesAI
// shared SSOT module.
//
// The SDK is OSS-licensed and NEUTRAL: it is imported by BOTH molecule-core
// (OSS) and molecule-controlplane (proprietary), and therefore depends on
// NEITHER. It contains only truly-shared, stable, environment-agnostic code.
// Environment-specific and proprietary logic stays in the owning repo.
//
// The dependency invariant is enforced by an automated guard — see
// deps_test.go (TestNoConsumerDependency) and the .gitea/workflows CI.
//
// Sub-packages:
//
//	llmwire — shared LLM wire constants (billing-mode + routing-mode strings,
//	          model-env-var names). No logic.
//
//	cloudprovider — the SSOT for the set of CLOUD/COMPUTE backends a tenant or
//	          workspace runs on (Molecules-Server/local, AWS, GCP, Hetzner):
//	          canonical ids, display labels, and the provisioner backend key
//	          each maps to. Distinct from the LLM provider registry. No logic.
//
// Tooling:
//
//	tools/cmd/nodup-lint — the shared no-duplication linter both consumers run.
package sdk
