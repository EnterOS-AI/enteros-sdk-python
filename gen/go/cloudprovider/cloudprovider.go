// Package cloudprovider is the single source of truth (SSOT) for the set of
// CLOUD / COMPUTE BACKENDS a MoleculesAI tenant or workspace can run on — the
// "where does this box physically run" axis: the local self-hosted box
// (Molecules-Server) and the three clouds (AWS / GCP / Hetzner).
//
// This is DELIBERATELY DISTINCT from the LLM provider registry
// (Anthropic/OpenAI/MiniMax/…). This package never mentions a model; it carries
// only the compute-backend identity. Conflating the two is the long-standing
// confusion this SSOT exists to end.
//
// Before this package the set was pasted independently in at least five places
// that could silently drift:
//   - controlplane internal/cloudprovider.Supported (org-create validation),
//   - controlplane internal/provisioner normalizeProviderKey (backend routing),
//   - controlplane internal/credits pricing tables (sweep.go),
//   - core workspace-server internal/handlers/workspace_compute.go (canvas
//     picker — a hand-maintained "deliberate mirror" of the CP list),
//   - the app cloud-provider dropdown.
//
// It is wire/identity DATA only (ids, display labels, and the provisioner
// backend key each id maps to) — NO provisioning logic, NO credentials, NO
// per-deploy behaviour — which is exactly why it can live in the neutral SDK
// that BOTH molecule-core (OSS) and molecule-controlplane (proprietary) import
// without either depending on the other. The provisioner backends that ACT on
// these ids (EC2 / GCP / Hetzner / LocalDocker) stay in their owning repo.
package cloudprovider

import "strings"

// Canonical provider IDENTIFIERS — the wire/UI value persisted on an org or
// workspace row and sent in the create / migrate API. These are the SSOT
// spellings; every consumer renders/validates against them.
const (
	// MoleculesServer is the local, self-hosted box (the "Molecules-Server").
	// It is the IS-LOCAL member, backed by the provisioner LocalDocker backend
	// (BackendLocal). It is selectable in the picker just like the clouds.
	MoleculesServer = "molecules-server"
	// AWS is the Amazon EC2 cloud backend (the historical implicit default — an
	// empty provider string Normalizes to AWS).
	AWS = "aws"
	// GCP is the Google Compute Engine cloud backend.
	GCP = "gcp"
	// Hetzner is the Hetzner Cloud backend.
	Hetzner = "hetzner"
)

// Provisioner BACKEND KEYS — the key the controlplane provider registry
// (provisioner.NewProviderRegistry / Select / Registered) routes on. For the
// clouds the backend key EQUALS the id; for the local box the id
// "molecules-server" maps to the historical backend key "local" — LocalDocker
// registers under "local", and existing org rows persist provider="local", so
// "local" (and the PROVISIONER_BACKEND spelling "docker") remain accepted
// Aliases that normalize to the MoleculesServer id.
const (
	BackendLocal   = "local"
	BackendAWS     = "aws"
	BackendGCP     = "gcp"
	BackendHetzner = "hetzner"
)

// Provider is one canonical entry: its wire id, human display label, the
// provisioner backend key it routes to, whether it is the local self-hosted
// box, and any alternate accepted wire spellings that normalize to ID.
type Provider struct {
	ID         string   // canonical wire/UI id (one of the id consts above)
	Display    string   // human label for pickers ("Molecules-Server","AWS",…)
	BackendKey string   // provisioner registry key (one of the Backend* consts)
	IsLocal    bool     // true only for the Molecules-Server local box
	Aliases    []string // alternate accepted wire spellings → normalize to ID
}

// All is the canonical, ORDERED list of every selectable provider — the SSOT a
// UI dropdown renders and a create/migrate validator accepts. Order is the
// preferred display order: the clouds first (AWS the historical default), then
// the local self-hosted box.
//
// Adding/removing a member here is the ONE edit that changes the provider set
// everywhere: CP validation + the app dropdown + (via CloudIDs) the core canvas
// picker all derive from this list.
var All = []Provider{
	{ID: AWS, Display: "AWS", BackendKey: BackendAWS, IsLocal: false},
	{ID: GCP, Display: "GCP", BackendKey: BackendGCP, IsLocal: false},
	{ID: Hetzner, Display: "Hetzner", BackendKey: BackendHetzner, IsLocal: false},
	{ID: MoleculesServer, Display: "Molecules-Server", BackendKey: BackendLocal, IsLocal: true, Aliases: []string{BackendLocal, "docker"}},
}

// DefaultID is the implicit provider when none is specified: an empty/blank
// provider string Normalizes to AWS (the historical default), preserving the
// pre-multi-provider wire contract that an absent provider means AWS.
const DefaultID = AWS

// byID and aliasToID are the O(1) lookup indexes built once from All — the
// SSOT shape can never disagree with itself because both derive from the same
// slice.
var (
	byID      = func() map[string]Provider {
		m := make(map[string]Provider, len(All))
		for _, p := range All {
			m[p.ID] = p
		}
		return m
	}()
	aliasToID = func() map[string]string {
		m := make(map[string]string, len(All))
		for _, p := range All {
			m[p.ID] = p.ID
			for _, a := range p.Aliases {
				m[strings.ToLower(strings.TrimSpace(a))] = p.ID
			}
		}
		return m
	}()
)

// Normalize lowercases + trims, resolves an Alias (e.g. "local"/"docker" →
// "molecules-server") to its canonical id, and maps the EMPTY string to the
// AWS default. An unknown non-empty value passes through unchanged (callers
// then reject it via IsValidID / IsValidRequest) so a typo fails LOUD rather
// than silently becoming AWS.
func Normalize(id string) string {
	id = strings.ToLower(strings.TrimSpace(id))
	if id == "" {
		return DefaultID
	}
	if canon, ok := aliasToID[id]; ok {
		return canon
	}
	return id
}

// ByID returns the canonical Provider for an id (after Normalize) and whether
// it is a known provider.
func ByID(id string) (Provider, bool) {
	p, ok := byID[Normalize(id)]
	return p, ok
}

// IsValidID reports whether id (after Normalize) is a canonical provider.
func IsValidID(id string) bool {
	_, ok := byID[Normalize(id)]
	return ok
}

// IsValidRequest reports whether a request-supplied provider value is
// acceptable: either the empty string (caller wants the default) or any valid
// id (incl. an alias). Create/validation paths use this to reject a typo with a
// clean 400 while still allowing an omitted provider.
func IsValidRequest(id string) bool {
	if strings.TrimSpace(id) == "" {
		return true
	}
	return IsValidID(id)
}

// BackendKey maps an id (after Normalize) to its provisioner registry backend
// key (e.g. "molecules-server" → "local"). Returns ok=false for an unknown id.
func BackendKey(id string) (string, bool) {
	if p, ok := byID[Normalize(id)]; ok {
		return p.BackendKey, true
	}
	return "", false
}

// Display maps an id (after Normalize) to its human label. Returns ok=false for
// an unknown id.
func Display(id string) (string, bool) {
	if p, ok := byID[Normalize(id)]; ok {
		return p.Display, true
	}
	return "", false
}

// IDs returns every canonical provider id in All order — the full selectable
// set (clouds + Molecules-Server). The returned slice is a fresh copy.
func IDs() []string {
	out := make([]string, 0, len(All))
	for _, p := range All {
		out = append(out, p.ID)
	}
	return out
}

// CloudIDs returns the non-local (cloud) provider ids in All order — the subset
// that has per-hour/per-GB cloud BILLING and that the core canvas mirror covers.
// The local Molecules-Server box is excluded (it has no cloud cost). The
// returned slice is a fresh copy.
func CloudIDs() []string {
	out := make([]string, 0, len(All))
	for _, p := range All {
		if !p.IsLocal {
			out = append(out, p.ID)
		}
	}
	return out
}
