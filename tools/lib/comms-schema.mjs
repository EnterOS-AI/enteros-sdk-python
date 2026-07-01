// comms-schema.mjs — shared JSON-Schema → language-agnostic model IR.
//
// The mcp/ generator derives scalar CONSTANTS from a contract *instance* (its
// values are the product). The workspace-comms/ contracts are different: their
// product is the *shape* of the request/response message types, which lives in
// the `*.schema.json` (the .contract.json is only a canonical example instance,
// validated against it). So this module reads every `workspace-comms/*.schema.json`
// and walks it into a language-agnostic intermediate representation (IR) of named
// model types + load-bearing string constants. The three `gen-<lang>.mjs`
// generators import this ONE IR and render it idiomatically (Go structs, TS
// interfaces, Python TypedDicts) — so the three languages stay in lockstep and
// every emitted name/field is DERIVED from the schema, never hand-written.
//
// What it does NOT do: it does not invent values. `const` string pins in the
// schema (status:"registered"|"ok"|"queued", jsonrpc:"2.0") become exported
// constants; `enum`/descriptions are carried into the IR as doc only. Anything
// the walker does not recognise is a hard error (fail-closed) so a schema shape
// it cannot model can never be silently dropped.

import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";

const COMMS_DIR = "workspace-comms";

// --- name helpers (deterministic; no special-casing) ------------------------

// pascal("agent_card") -> "AgentCard"; pascal("agentCard") -> "AgentCard";
// pascal("mcp_server_present") -> "McpServerPresent"; pascal("messageId") -> "MessageId".
// Splits on any non-alphanumeric run, uppercases the first letter of each word,
// preserves the rest (so internal camelCase like messageId survives).
export function pascal(s) {
  return String(s)
    .split(/[^A-Za-z0-9]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join("");
}

// upperSnake("RegisterResponseStatus") -> "REGISTER_RESPONSE_STATUS"
// Keeps runs of capitals together (MCP -> MCP), mirroring tools/gen-python.mjs.
export function upperSnake(pascalName) {
  return pascalName
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1_$2")
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toUpperCase();
}

// baseFromFile("register.schema.json") -> "Register";
// baseFromFile("a2a-envelope.schema.json") -> "A2aEnvelope".
function baseFromFile(file) {
  return pascal(file.replace(/\.schema\.json$/, ""));
}

// collapse a (possibly multi-line) schema description into one comment line.
function oneLine(s) {
  if (typeof s !== "string") return "";
  return s.replace(/\s+/g, " ").trim();
}

// --- the walker -------------------------------------------------------------

// buildCommsModelIR(repoRoot) returns:
//   {
//     types:  [ { name, doc, source, fields: [Field] }, ... ],   // emission order
//     consts: [ { name, value, doc, source }, ... ],             // const-pinned literals
//   }
// Field = { key, required, type: TypeRef, doc, enumValues|null }
// TypeRef =
//   { k:"scalar", t:"string"|"int"|"float"|"bool"|"any" }
//   | { k:"named", name }
//   | { k:"array", items: TypeRef }
//   | { k:"map", value: TypeRef }
// buildModelIR(repoRoot, dirs) — the generic walker over one or more surface
// directories of `*.schema.json` contracts. Each directory is read, its schema
// files sorted (deterministic emission order), and every root type + $def walked
// into the shared IR. A single shared `registered` set dedupes across dirs and a
// single `types`/`consts` pair aggregates them, so one IR → one generated file.
// Type names are prefixed by the schema FILENAME base (not the dir), so distinct
// contracts stay collision-free.
export function buildModelIR(repoRoot, dirs) {
  const types = [];
  const consts = [];
  const registered = new Set(); // type names already emitted (dedupe)

  for (const surfaceDir of dirs) {
    const dir = resolve(repoRoot, surfaceDir);
    const files = readdirSync(dir)
      .filter((f) => f.endsWith(".schema.json"))
      .sort(); // deterministic cross-file emission order

    for (const file of files) {
      const rel = `${surfaceDir}/${file}`;
      const abs = resolve(dir, file);
      let schema;
      try {
        schema = JSON.parse(readFileSync(abs, "utf8"));
      } catch (err) {
        throw new Error(`comms-schema: ${rel} is not valid JSON: ${err.message}`);
      }

      const base = baseFromFile(file);
      const defs = schema.$defs || {};
      const ctx = { rel, base, defs, types, consts, registered };

      // root type (and everything reachable from it)
      emitType(schema, base, ctx, `${rel}#`);

      // every OBJECT-WITH-PROPERTIES $def becomes a named, base-prefixed struct
      // type (referenced via $ref). Scalar/enum/map $defs (e.g. a string `enum`
      // runtime id) are NOT structs — they are resolved INLINE at their $ref
      // sites (see emitType's $ref branch), so we skip them here.
      for (const defName of Object.keys(defs)) {
        if (!isStructDef(defs[defName])) continue;
        const name = base + pascal(defName);
        registerObjectType(defs[defName], name, ctx, `${rel}#/$defs/${defName}`);
      }
    }
  }

  return { types, consts };
}

// buildCommsModelIR(repoRoot) — the original workspace-comms entry point, now a
// thin wrapper over the generic walker. Behaviour (and generated output) is
// byte-identical to before: a single dir, same filename-derived names, same order.
export function buildCommsModelIR(repoRoot) {
  return buildModelIR(repoRoot, [COMMS_DIR]);
}

// resolve a local "#/$defs/<name>" pointer to its base-prefixed type name.
function refName(pointer, ctx) {
  const m = /^#\/\$defs\/(.+)$/.exec(pointer);
  if (!m) {
    throw new Error(
      `comms-schema: ${ctx.rel}: only local '#/$defs/<name>' $refs are supported, got ${JSON.stringify(pointer)}`
    );
  }
  return ctx.base + pascal(m[1]);
}

// defNodeOf: resolve a local "#/$defs/<name>" pointer to the referenced $def
// schema node in the current file (used to decide struct-vs-scalar at a $ref).
function defNodeOf(pointer, ctx) {
  const m = /^#\/\$defs\/(.+)$/.exec(pointer);
  if (!m) {
    throw new Error(
      `comms-schema: ${ctx.rel}: only local '#/$defs/<name>' $refs are supported, got ${JSON.stringify(pointer)}`
    );
  }
  return ctx.defs[m[1]];
}

// isStructDef: a $def is a NAMED STRUCT only if it is an object with at least one
// named property. Everything else (a string `enum`, a scalar, a bare map) is a
// non-struct that gets resolved inline at its $ref site rather than emitted as a
// named type. (comms' only $def, `agentCard`, is a struct, so this is a no-op
// for the workspace-comms output.)
function isStructDef(node) {
  return (
    node != null &&
    typeof node === "object" &&
    node.properties != null &&
    Object.keys(node.properties).length > 0
  );
}

// emitType: map a schema node to a TypeRef, registering named object types as a
// side effect. `suggested` is the name to mint if this node is an anonymous
// (inline) object/array-item.
function emitType(schema, suggested, ctx, source) {
  if (schema == null || typeof schema !== "object") {
    throw new Error(`comms-schema: ${ctx.rel}: expected a schema object at ${source}`);
  }
  if (typeof schema.$ref === "string") {
    // A $ref to an OBJECT-WITH-PROPERTIES def is a named type. A $ref to a
    // scalar/enum/map def (e.g. a shared `runtimeId` string enum) is resolved
    // INLINE to that def's TypeRef — so a shared enum becomes the underlying
    // scalar at every use site instead of an un-emitted named alias.
    const target = defNodeOf(schema.$ref, ctx);
    if (target && !isStructDef(target)) {
      return emitType(target, refName(schema.$ref, ctx), ctx, source);
    }
    return { k: "named", name: refName(schema.$ref, ctx) };
  }

  const t = schema.type;

  // object — either a named struct (has `properties`) or a map (additionalProperties).
  if (t === "object" || schema.properties || schema.additionalProperties !== undefined) {
    if (schema.properties && Object.keys(schema.properties).length > 0) {
      registerObjectType(schema, suggested, ctx, source);
      return { k: "named", name: suggested };
    }
    // no named properties -> it is a map (open bag or typed-value map).
    const ap = schema.additionalProperties;
    if (ap && typeof ap === "object") {
      const value = emitType(ap, `${suggested}Value`, ctx, `${source}/additionalProperties`);
      return { k: "map", value };
    }
    // additionalProperties: true | undefined | false, no properties -> open map.
    return { k: "map", value: { k: "scalar", t: "any" } };
  }

  if (t === "array") {
    if (!schema.items || typeof schema.items !== "object") {
      throw new Error(`comms-schema: ${ctx.rel}: array at ${source} has no object 'items'`);
    }
    const items = emitType(schema.items, `${suggested}Item`, ctx, `${source}/items`);
    return { k: "array", items };
  }

  if (t === "string") return { k: "scalar", t: "string" };
  if (t === "integer") return { k: "scalar", t: "int" };
  if (t === "number") return { k: "scalar", t: "float" };
  if (t === "boolean") return { k: "scalar", t: "bool" };
  if (t === undefined) return { k: "scalar", t: "any" }; // untyped node -> opaque

  throw new Error(`comms-schema: ${ctx.rel}: unsupported schema type ${JSON.stringify(t)} at ${source}`);
}

// registerObjectType: declare a named struct/interface/TypedDict for an object
// schema with `properties`, recursing into each property. Parent is pushed
// before children so emission order is parent-first.
function registerObjectType(schema, name, ctx, source) {
  if (ctx.registered.has(name)) return; // dedupe (e.g. a $def referenced + iterated)
  ctx.registered.add(name);

  if (!schema.properties || typeof schema.properties !== "object") {
    throw new Error(`comms-schema: ${ctx.rel}: object ${name} at ${source} has no 'properties'`);
  }

  const def = { name, doc: oneLine(schema.description), source, fields: [] };
  ctx.types.push(def);

  const requiredSet = new Set(Array.isArray(schema.required) ? schema.required : []);

  for (const [key, propSchema] of Object.entries(schema.properties)) {
    const childSource = `${source}/properties/${key}`;
    const childSuggested = name + pascal(key);
    const type = emitType(propSchema, childSuggested, ctx, childSource);

    // a `const` string pin becomes an exported, importable constant.
    if (typeof propSchema.const === "string") {
      ctx.consts.push({
        name: name + pascal(key),
        value: propSchema.const,
        doc: oneLine(propSchema.description),
        source: childSource,
      });
    }

    def.fields.push({
      key,
      required: requiredSet.has(key),
      type,
      doc: oneLine(propSchema.description),
      enumValues: Array.isArray(propSchema.enum) ? propSchema.enum.slice() : null,
    });
  }
}
