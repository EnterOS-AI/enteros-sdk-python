package sdk

import (
	"os"
	"strings"
	"testing"
)

// forbiddenModuleSubstrings are module paths the SDK must NEVER depend on. The
// whole point of the SDK is to be a NEUTRAL third module that both consumers
// import; if it ever required one of them, it would re-introduce the very
// core<->CP coupling the SDK exists to prevent.
var forbiddenModuleSubstrings = []string{
	"go.moleculesai.app/controlplane",                                // CP (vanity)
	"molecule-controlplane",                                          // CP (repo)
	"git.moleculesai.app/molecule-ai/molecule-core/workspace-server", // core module
	"go.moleculesai.app/core",                                        // core (vanity)
}

func TestNoConsumerDependency(t *testing.T) {
	for _, f := range []string{"go.mod", "go.sum"} {
		b, err := os.ReadFile(f)
		if err != nil {
			if f == "go.sum" && os.IsNotExist(err) {
				continue // a depless module may have no go.sum
			}
			t.Fatalf("read %s: %v", f, err)
		}
		body := string(b)
		for _, bad := range forbiddenModuleSubstrings {
			if strings.Contains(body, bad) {
				t.Errorf("%s references forbidden module %q — the SDK must depend on NEITHER consumer repo", f, bad)
			}
		}
	}
}
