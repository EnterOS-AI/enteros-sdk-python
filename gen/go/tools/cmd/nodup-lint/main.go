// Command nodup-lint is the SHARED no-duplication linter for the MoleculesAI
// repos. It is built ONCE here in the SDK and invoked (via `go run`) from BOTH
// molecule-core and molecule-controlplane CI, so the linter itself is never
// duplicated.
//
// It enforces the inverse of the retired "keep your copy byte-equal to the
// canonical" gate: there must be NO copy — you must IMPORT the SSOT. The
// ban-list is the embedded owned.yaml (the SDK owns the policy).
//
// Usage:
//
//	nodup-lint [-repo DIR] [-allow GLOB ...]
//
// Exit status is non-zero (1) if any violation is found, 2 on operational error.
package main

import (
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"flag"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"
)

//go:embed owned.yaml
var embedded embed.FS

type ownedSpec struct {
	ForbiddenPaths []string          `yaml:"forbidden_paths"`
	Symbols        []string          `yaml:"symbols"`
	Fingerprints   map[string]string `yaml:"fingerprints"`
	ImportHint     string            `yaml:"import_hint"`
}

type multiFlag []string

func (m *multiFlag) String() string { return strings.Join(*m, ",") }
func (m *multiFlag) Set(v string) error {
	for _, p := range strings.Split(v, ",") {
		if p = strings.TrimSpace(p); p != "" {
			*m = append(*m, p)
		}
	}
	return nil
}

type violation struct {
	file  string // repo-relative, forward-slashed
	line  int
	layer string
	msg   string
}

func main() {
	var repo string
	var allow multiFlag
	flag.StringVar(&repo, "repo", ".", "repo root to scan")
	flag.Var(&allow, "allow", "glob (repo-relative, /-separated) of a file to EXEMPT from symbol/fingerprint checks; repeatable or comma-separated. Use for the sanctioned per-repo re-export shim + endpoint adapter.")
	flag.Parse()

	spec, err := loadOwned()
	if err != nil {
		fmt.Fprintf(os.Stderr, "nodup-lint: cannot load ban-list: %v\n", err)
		os.Exit(2)
	}

	// An optional repo-local allow file augments the -allow flags so a repo can
	// document its sanctioned seams in-tree.
	allow = append(allow, readAllowFile(repo)...)

	vs, err := run(repo, spec, allow)
	if err != nil {
		fmt.Fprintf(os.Stderr, "nodup-lint: %v\n", err)
		os.Exit(2)
	}

	if len(vs) == 0 {
		fmt.Println("nodup-lint: OK — no duplicated SDK-owned code found.")
		return
	}
	sort.Slice(vs, func(i, j int) bool {
		if vs[i].file != vs[j].file {
			return vs[i].file < vs[j].file
		}
		return vs[i].line < vs[j].line
	})
	for _, v := range vs {
		fmt.Fprintf(os.Stderr, "%s:%d: [nodup-lint/%s] %s\n", v.file, v.line, v.layer, v.msg)
	}
	fmt.Fprintf(os.Stderr, "\nnodup-lint: FAIL — %d violation(s). %s\n", len(vs), spec.ImportHint)
	os.Exit(1)
}

func loadOwned() (*ownedSpec, error) {
	b, err := embedded.ReadFile("owned.yaml")
	if err != nil {
		return nil, err
	}
	var s ownedSpec
	if err := yaml.Unmarshal(b, &s); err != nil {
		return nil, err
	}
	return &s, nil
}

func readAllowFile(repo string) []string {
	b, err := os.ReadFile(filepath.Join(repo, ".nodup-lint-allow"))
	if err != nil {
		return nil
	}
	var out []string
	for _, ln := range strings.Split(string(b), "\n") {
		ln = strings.TrimSpace(ln)
		if ln == "" || strings.HasPrefix(ln, "#") {
			continue
		}
		out = append(out, ln)
	}
	return out
}

func run(repo string, spec *ownedSpec, allow []string) ([]violation, error) {
	symbolSet := make(map[string]bool, len(spec.Symbols))
	for _, s := range spec.Symbols {
		symbolSet[s] = true
	}
	fpSet := make(map[string]string) // sha -> name
	for name, sha := range spec.Fingerprints {
		fpSet[strings.ToLower(sha)] = name
	}

	var vs []violation
	fset := token.NewFileSet()

	err := filepath.WalkDir(repo, func(p string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel := relSlash(repo, p)
		if d.IsDir() {
			if skipDir(rel, d.Name()) {
				return filepath.SkipDir
			}
			return nil
		}

		// Layer A — forbidden path (structural). Applies even to allowlisted files.
		for _, fp := range spec.ForbiddenPaths {
			if matchGlob(fp, rel) {
				vs = append(vs, violation{rel, 0, "A:path", fmt.Sprintf("SDK-owned path re-appeared in this repo (pattern %q); delete it and import the SSOT", fp)})
			}
		}

		exempt := false
		for _, g := range allow {
			if matchGlob(g, rel) {
				exempt = true
				break
			}
		}

		// Layer C — fingerprint (copy detection). Skipped for exempt files.
		if !exempt && len(fpSet) > 0 {
			if sha, ok := fileSHA(p); ok {
				if name, hit := fpSet[sha]; hit {
					vs = append(vs, violation{rel, 0, "C:fingerprint", fmt.Sprintf("file content is byte-identical to SDK-owned blob %q; delete the copy and import the SSOT", name)})
				}
			}
		}

		// Layer B — owned-symbol AST lint. Go files only, skipped for exempt files.
		if !exempt && strings.HasSuffix(rel, ".go") && len(symbolSet) > 0 {
			vb, perr := scanGoFile(fset, p, rel, symbolSet)
			if perr != nil {
				// A file that won't parse is a real problem, but the consumer's own
				// build/vet already gates that; don't let a parse hiccup mask the
				// rest of the scan. Report it as an operational note, not a dup.
				fmt.Fprintf(os.Stderr, "nodup-lint: warning: parse %s: %v\n", rel, perr)
				return nil
			}
			vs = append(vs, vb...)
		}
		return nil
	})
	return vs, err
}

// scanGoFile flags re-DECLARATION of an SDK-owned identifier, while allowing a
// re-EXPORT alias. The distinction is the value expression:
//   - `const LLMBillingModeBYOK = "byok"`            -> BasicLit  -> FAIL (re-paste)
//   - `const LLMBillingModeBYOK = llmwire.LLMBillingModeBYOK` -> SelectorExpr -> PASS (alias)
//
// An owned type/func name re-declared is always a violation (an alias of those
// is a `var X = sdk.X` ValueSpec, not a TypeSpec/FuncDecl).
func scanGoFile(fset *token.FileSet, abs, rel string, symbols map[string]bool) ([]violation, error) {
	f, err := parser.ParseFile(fset, abs, nil, 0)
	if err != nil {
		return nil, err
	}
	var vs []violation
	for _, decl := range f.Decls {
		switch dd := decl.(type) {
		case *ast.GenDecl:
			for _, spec := range dd.Specs {
				switch s := spec.(type) {
				case *ast.ValueSpec: // const / var
					for i, name := range s.Names {
						if !symbols[name.Name] {
							continue
						}
						var val ast.Expr
						if i < len(s.Values) {
							val = s.Values[i]
						}
						if isStringLiteral(val) {
							vs = append(vs, violation{rel, fset.Position(name.Pos()).Line, "B:symbol",
								fmt.Sprintf("%q is owned by the SDK but is re-declared here with a literal value — import it instead (a re-export `= <sdkpkg>.%s` is fine; allowlist a shim file via -allow / .nodup-lint-allow)", name.Name, name.Name)})
						}
					}
				case *ast.TypeSpec:
					if symbols[s.Name.Name] {
						vs = append(vs, violation{rel, fset.Position(s.Name.Pos()).Line, "B:symbol",
							fmt.Sprintf("type %q is owned by the SDK — import it instead of redeclaring", s.Name.Name)})
					}
				}
			}
		case *ast.FuncDecl:
			if dd.Recv == nil && symbols[dd.Name.Name] {
				vs = append(vs, violation{rel, fset.Position(dd.Name.Pos()).Line, "B:symbol",
					fmt.Sprintf("func %q is owned by the SDK — import it instead of redeclaring", dd.Name.Name)})
			}
		}
	}
	return vs, nil
}

func isStringLiteral(e ast.Expr) bool {
	bl, ok := e.(*ast.BasicLit)
	return ok && bl.Kind == token.STRING
}

func skipDir(rel, name string) bool {
	switch name {
	case ".git", "vendor", "node_modules", ".gitea", "testdata":
		return true
	}
	// Skip the SDK's own tree if a consumer ever vendors it locally for dev.
	return false
}

func relSlash(repo, p string) string {
	r, err := filepath.Rel(repo, p)
	if err != nil {
		r = p
	}
	return filepath.ToSlash(r)
}

func fileSHA(p string) (string, bool) {
	b, err := os.ReadFile(p)
	if err != nil {
		return "", false
	}
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:]), true
}

// matchGlob matches a repo-relative, forward-slashed path against a pattern that
// supports `**` (any path segments) in addition to filepath.Match's per-segment
// `*`/`?`. Examples: "internal/providers/gen/registry_gen.go" (exact),
// "cmd/gen-providers/**" (prefix), "internal/**/llm_wire_sdk.go".
func matchGlob(pattern, name string) bool {
	if pattern == name {
		return true
	}
	if strings.Contains(pattern, "**") {
		// Translate ** into a regexp-free segment walk.
		parts := strings.Split(pattern, "**")
		// Anchor head.
		if !strings.HasPrefix(name, strings.TrimSuffix(parts[0], "/")) &&
			!strings.HasPrefix(name, parts[0]) {
			return false
		}
		rest := name
		for i, part := range parts {
			part = strings.Trim(part, "/")
			if part == "" {
				continue
			}
			idx := strings.Index(rest, part)
			if idx < 0 {
				return false
			}
			rest = rest[idx+len(part):]
			_ = i
		}
		return true
	}
	ok, err := filepath.Match(pattern, name)
	if err == nil && ok {
		return true
	}
	// Also try matching just the basename for convenience (e.g. "*.yaml").
	ok2, err2 := filepath.Match(pattern, filepath.Base(name))
	return err2 == nil && ok2
}
