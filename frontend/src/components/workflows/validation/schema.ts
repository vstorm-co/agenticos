/**
 * Type-compatibility helpers — the client mirror of `validate.py`'s rule 3, and
 * the schema half of what the binding picker needs.
 *
 * The backend compares Pydantic `model_fields`: two port schemas are compatible
 * when their `{(field name, type name)}` sets match, and a field path resolves to
 * a *terminal* type compared by name. The catalog serves those same schemas as
 * JSON Schema, so this module works the JSON-Schema analog:
 *
 * - a port's shape is the set of `(property name, {@link schemaTypeToken})` over
 *   its `properties`, the analog of `_model_shape`;
 * - a field path walks `properties` (resolving `$ref` against the schema's own
 *   `$defs`), the analog of `_resolve_field_path`;
 * - two terminal types are compatible when their tokens are equal, the analog of
 *   `_types_compatible`.
 *
 * Parity is at the *verdict* level and is exercised by the drift fixtures: the
 * token need not read `str` the way Python does, only distinguish exactly the
 * types the backend distinguishes. A `null` schema is a control port carrying no
 * payload and is compatible with anything, exactly as `_shapes_compatible` treats
 * `None`.
 */

import type { JsonSchema, NodeDefinition } from "@/lib/workflows/types";

/**
 * The sentinel a port / field lookup returns when the thing does not exist —
 * distinct from `null`, which is a real control port with no payload. Mirrors the
 * backend's `_UNKNOWN` object, kept apart from `None`.
 */
export const UNKNOWN: unique symbol = Symbol("unknown");
export type Unknown = typeof UNKNOWN;

/** A resolved type: a JSON-Schema fragment, a control port's `null`, or absent. */
export type ResolvedType = JsonSchema | null | Unknown;

/** The `$defs` a schema carries for resolving its own `$ref`s. */
type Defs = Record<string, JsonSchema>;

function defsOf(schema: JsonSchema): Defs {
  const defs = schema["$defs"];
  return isObject(defs) ? (defs as Defs) : {};
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The last segment of a `$ref` pointer — `#/$defs/Name` → `Name`. */
function refName(ref: string): string {
  return ref.slice(ref.lastIndexOf("/") + 1);
}

/** Follow a `$ref` (`#/$defs/Name`) against `defs`; return the schema unchanged otherwise. */
function resolveRef(schema: JsonSchema, defs: Defs): JsonSchema {
  const ref = schema["$ref"];
  if (typeof ref !== "string") return schema;
  const target = defs[refName(ref)];
  return isObject(target) ? target : schema;
}

/**
 * A single comparable token for a property's type, distinguishing exactly the
 * types the backend's `_type_name` (`annotation.__name__`) distinguishes.
 *
 * A `$ref` or an object's `title` gives the model name (what a nested Pydantic
 * model's `__name__` is); a scalar gives its JSON `type`, suffixed with `format`
 * so a `date-time` string is not the same token as a plain string. The two coarse
 * cases the naive token collapsed are folded in:
 *
 * - **collections** — `list`, `set` and `tuple` are three names on the server, so
 *   an `array` schema is discriminated by its facets (`uniqueItems` → set,
 *   `prefixItems` → tuple, neither → list), see {@link arrayToken}; the item type
 *   is left out because `list[str]` and `list[int]` are both "list";
 * - **unions** — `anyOf`/`oneOf` is a composite of its members' tokens, see
 *   {@link unionToken}, because `str | None` and `int | None` are different names
 *   a single `"unknown"` false-matched.
 *
 * Anything with no type information is `"unknown"`.
 */
export function schemaTypeToken(schema: ResolvedType): string {
  if (schema === UNKNOWN) return "unknown";
  if (schema === null) return "null";
  const union = unionToken(schema);
  if (union !== null) return union;
  const ref = schema["$ref"];
  if (typeof ref === "string") return refName(ref);
  const type = schema["type"];
  if (typeof type === "string") {
    if (type === "object" && typeof schema["title"] === "string") return schema["title"] as string;
    if (type === "array") return arrayToken(schema);
    const format = schema["format"];
    return typeof format === "string" ? `${type}:${format}` : type;
  }
  if (typeof schema["title"] === "string") return schema["title"] as string;
  return "unknown";
}

/**
 * The token for an `array` schema — the collection type the backend names by
 * `__name__`. `prefixItems` (a fixed-length heterogeneous tuple) → tuple;
 * `uniqueItems` (a set) → set; neither → a plain list. The element type is
 * deliberately omitted: `_type_name(list[str])` and `_type_name(list[int])` are
 * both "list", so a list of strings and a list of ints share a token, exactly as
 * they do on the server — folding the item type in would reject an edge the server
 * accepts.
 */
function arrayToken(schema: JsonSchema): string {
  if (Array.isArray(schema["prefixItems"])) return "array:tuple";
  if (schema["uniqueItems"] === true) return "array:set";
  return "array";
}

/**
 * A composite token for a JSON-Schema union (`anyOf`/`oneOf`), or `null` when the
 * schema is not one. Built from the members' tokens in order, recursively, so a
 * union of models or arrays is discriminated too. The backend names a union by
 * `str(annotation)` (e.g. `"str | None"`), which distinguishes both the members
 * and their order (`str | int` ≠ `int | str`); a single `"unknown"` collapsed
 * every union into one token and false-accepted edges and bindings the server
 * rejects, so member order is preserved rather than sorted.
 */
function unionToken(schema: JsonSchema): string | null {
  const members = schema["anyOf"] ?? schema["oneOf"];
  if (!Array.isArray(members)) return null;
  const tokens = members.map((member) =>
    isObject(member) ? schemaTypeToken(member as JsonSchema) : "unknown",
  );
  return `union(${tokens.join("|")})`;
}

/** The `{(property, token)}` shape of an object schema — the analog of `_model_shape`. */
function objectShape(schema: JsonSchema): Set<string> {
  const properties = schema["properties"];
  const shape = new Set<string>();
  if (!isObject(properties)) return shape;
  for (const [name, propSchema] of Object.entries(properties)) {
    const token = isObject(propSchema) ? schemaTypeToken(propSchema as JsonSchema) : "unknown";
    shape.add(`${name}\u0000${token}`);
  }
  return shape;
}

function sameSet(left: Set<string>, right: Set<string>): boolean {
  if (left.size !== right.size) return false;
  for (const value of left) {
    if (!right.has(value)) return false;
  }
  return true;
}

/**
 * Whether an edge may carry `source`'s payload into `target` — the analog of
 * `_shapes_compatible`. A `null` (control) port on either end is compatible with
 * anything; two data ports must share the same property shape.
 */
export function portShapesCompatible(source: ResolvedType, target: ResolvedType): boolean {
  if (source === UNKNOWN || target === UNKNOWN) return false;
  if (source === null || target === null) return true;
  return sameSet(objectShape(source), objectShape(target));
}

/** A definition's port schema by id and direction, or {@link UNKNOWN} if no such port. */
export function portSchema(
  definition: NodeDefinition,
  portId: string,
  kind: "input" | "output",
): ResolvedType {
  for (const port of definition.ports) {
    if (port.id === portId && port.kind === kind) return port.schema;
  }
  return UNKNOWN;
}

/**
 * The type a `NodeOutputRef` resolves to: walk `field_path` from the output port's
 * schema. The analog of `_resolve_field_path`.
 *
 * An empty path is the whole port value. A step into a scalar (no `properties`) or
 * a name the schema does not declare is {@link UNKNOWN}; a `null` control port with
 * an empty path stays `null`.
 */
export function resolveFieldType(
  definition: NodeDefinition,
  portId: string,
  fieldPath: readonly string[],
): ResolvedType {
  const schema = portSchema(definition, portId, "output");
  if (schema === UNKNOWN || schema === null) return schema;
  const defs = defsOf(schema);
  let current: JsonSchema = schema;
  for (const part of fieldPath) {
    const resolved = resolveRef(current, defs);
    const properties = resolved["properties"];
    if (!isObject(properties) || !isObject(properties[part])) return UNKNOWN;
    current = properties[part] as JsonSchema;
  }
  return current;
}

/**
 * The declared type of a target field — its `input_schema` field, or its
 * `config_schema` field, in that order. The analog of `_field_type`. {@link UNKNOWN}
 * when neither schema declares it.
 */
export function fieldType(definition: NodeDefinition, fieldName: string): ResolvedType {
  for (const schema of [definition.input_schema, definition.config_schema]) {
    if (schema === null) continue;
    const properties = schema["properties"];
    if (isObject(properties) && isObject(properties[fieldName])) {
      return resolveRef(properties[fieldName] as JsonSchema, defsOf(schema));
    }
  }
  return UNKNOWN;
}

/** Whether two resolved terminal types are compatible — the analog of `_types_compatible`. */
export function typesCompatible(source: ResolvedType, target: ResolvedType): boolean {
  return schemaTypeToken(source) === schemaTypeToken(target);
}
