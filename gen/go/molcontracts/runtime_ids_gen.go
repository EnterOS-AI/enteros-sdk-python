// Code generated from contracts/adapter/runtime-id.schema.json and official-runtimes.registry.json by tools/gen-runtimes.mjs. DO NOT EDIT.

package molcontracts

import "regexp"

const RuntimeIDMaxLength = 64
const RuntimeIDPattern = "^[a-z0-9]+([-_][a-z0-9]+)*$"
const RuntimeIDDisallowedPattern = "[^a-z0-9_-]"

var runtimeIDRegexp = regexp.MustCompile(RuntimeIDPattern)
var runtimeIDDisallowedRegexp = regexp.MustCompile(RuntimeIDDisallowedPattern)

var OfficialRuntimeIDs = []string{
	"claude-code",
	"codex",
	"hermes",
	"openclaw",
}

var RuntimeIDAliases = map[string]string{
	"claude_code": "claude-code",
}

func IsValidRuntimeID(runtimeID string) bool {
	return len(runtimeID) <= RuntimeIDMaxLength &&
		runtimeIDRegexp.MatchString(runtimeID) &&
		!runtimeIDDisallowedRegexp.MatchString(runtimeID)
}

func NormalizeRuntimeID(runtimeID string) (string, bool) {
	if !IsValidRuntimeID(runtimeID) {
		return "", false
	}
	if canonical, ok := RuntimeIDAliases[runtimeID]; ok {
		return canonical, true
	}
	return runtimeID, true
}

func IsOfficialRuntimeID(runtimeID string) bool {
	normalized, ok := NormalizeRuntimeID(runtimeID)
	if !ok {
		return false
	}
	for _, official := range OfficialRuntimeIDs {
		if normalized == official {
			return true
		}
	}
	return false
}
