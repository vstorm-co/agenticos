/**
 * Interpreting a catalog JSON Schema for the property form — the primitives
 * `schema-form.tsx` never had: `$ref` resolution, and telling an object, an
 * array-of-objects, a discriminated union and a scalar leaf apart.
 *
 * The node catalog serves each `config_schema` / `input_schema` / port schema as
 * an opaque `JsonSchema` (`Record<string, unknown>` in `@/lib/workflows/types`).
 * `schema-form.tsx` renders the *scalar* leaves from the structured
 * `JsonSchemaProperty` view of the same JSON Schema, so this module is the one
 * place the two views are bridged, and the one place a `$ref` is followed. It is
 * pure: nothing here renders, so every branch is unit-testable without React.
 */

import type { JsonSchema } from "@/lib/workflows/types";
import type { JsonSchema as FormSchema, JsonSchemaProperty as FormProperty } from "@/types/agents";

/** A catalog JSON Schema — the opaque object shape the wire carries. */
export type Schema = JsonSchema;

/** The `$defs` a section-root schema carries, for resolving its own `$ref`s. */
export type Defs = Record<string, Schema>;

/** Whether a value is a plain object (a schema node), not an array or null. */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The `$defs` block of a section-root schema, or an empty map. */
export function defsOf(schema: Schema): Defs {
  const defs = schema["$defs"];
  return isRecord(defs) ? (defs as Defs) : {};
}

/** The last segment of a `$ref` pointer — `#/$defs/Name` → `Name`. */
function refName(ref: string): string {
  return ref.slice(ref.lastIndexOf("/") + 1);
}

/**
 * Follow a `$ref` (`#/$defs/Name`) against `defs`; return the schema unchanged
 * when it carries no `$ref`, or when the target is not a real def. One hop only:
 * the catalog's schemas alias a named model, never a chain.
 */
export function resolveRef(schema: Schema, defs: Defs): Schema {
  const ref = schema["$ref"];
  if (typeof ref !== "string") return schema;
  const target = defs[refName(ref)];
  return isRecord(target) ? (target as Schema) : schema;
}

/**
 * Unwrap Pydantic's optional wrapping — `anyOf: [X, {type: "null"}]` — to `X`, so
 * an optional object/array/union is classified by its real shape rather than
 * falling through to a leaf. Left unchanged unless exactly one non-null branch
 * remains (a genuine `anyOf` of several types stays a leaf, bound wholesale).
 */
export function unwrapOptional(schema: Schema): Schema {
  const anyOf = schema["anyOf"];
  if (!Array.isArray(anyOf)) return schema;
  const branches = anyOf.filter(
    (branch): branch is Schema => isRecord(branch) && branch["type"] !== "null",
  );
  return branches.length === 1 ? (branches[0] as Schema) : schema;
}

/** One property of an object schema — its name, its schema, and whether it is required. */
export interface FieldEntry {
  name: string;
  schema: Schema;
  required: boolean;
}

/** A schema that renders as a fieldset of nested fields. */
export interface ObjectShape {
  kind: "object";
  entries: FieldEntry[];
}

/** An array-of-objects that renders as add/remove/reorder repeatable rows. */
export interface ArrayShape {
  kind: "array";
  items: Schema;
}

/** One branch of a discriminated union — its discriminator value, label and sub-schema. */
export interface UnionBranch {
  value: string;
  label: string;
  schema: Schema;
}

/** A discriminated union that renders as a discriminator `Select` plus the branch sub-form. */
export interface UnionShape {
  kind: "union";
  discriminator: string;
  branches: UnionBranch[];
}

/** A scalar (or wholesale-bound) leaf — `schema-form.tsx`'s territory, or a picker. */
export interface LeafShape {
  kind: "leaf";
  schema: Schema;
}

/** What a schema renders as, once its `$ref` and optional wrapping are resolved. */
export type Shape = ObjectShape | ArrayShape | UnionShape | LeafShape;

/** The property names an object schema marks required. */
function requiredNames(schema: Schema): Set<string> {
  const required = schema["required"];
  if (!Array.isArray(required)) return new Set();
  return new Set(required.filter((name): name is string => typeof name === "string"));
}

/**
 * The renderable properties of an object schema, dropping `const`-only fields —
 * a discriminator a union already renders, the same fields `schema-form.tsx`
 * itself skips because a control for a single legal value can only be wrong.
 */
function objectEntries(schema: Schema): FieldEntry[] {
  // Only reached once `isObjectSchema` has confirmed `properties` is a record.
  const properties = schema["properties"] as Record<string, unknown>;
  const required = requiredNames(schema);
  const entries: FieldEntry[] = [];
  for (const [name, raw] of Object.entries(properties)) {
    if (!isRecord(raw)) continue;
    if (raw["const"] !== undefined) continue;
    entries.push({ name, schema: raw as Schema, required: required.has(name) });
  }
  return entries;
}

/** Whether a schema is an object with rendered properties. */
function isObjectSchema(schema: Schema): boolean {
  return schema["type"] === "object" && isRecord(schema["properties"]);
}

/** The `items` schema of an array, or null when it declares none. */
function arrayItems(schema: Schema): Schema | null {
  const items = schema["items"];
  return isRecord(items) ? (items as Schema) : null;
}

/** The discriminator property names a branch carries as a string `const`. */
function branchConsts(branch: Schema): string[] {
  const properties = branch["properties"];
  if (!isRecord(properties)) return [];
  return Object.entries(properties)
    .filter(([, prop]) => isRecord(prop) && typeof prop["const"] === "string")
    .map(([name]) => name);
}

/**
 * The discriminator property name of a `oneOf` union: Pydantic's own
 * `discriminator.propertyName` when present, otherwise the one string-`const`
 * property every branch shares. Null when no single such property exists.
 */
function discriminatorOf(schema: Schema, branches: Schema[]): string | null {
  const declared = schema["discriminator"];
  if (isRecord(declared) && typeof declared["propertyName"] === "string") {
    return declared["propertyName"] as string;
  }
  // `branches` is non-empty: `unionShape` only calls this once it has confirmed
  // every `oneOf` member resolved, so `branches[0]` is a real schema.
  const first = branches[0] as Schema;
  for (const name of branchConsts(first)) {
    if (branches.every((branch) => branchConsts(branch).includes(name))) return name;
  }
  return null;
}

/** One union branch's value/label/schema, or null when it lacks the discriminator const. */
function branchFor(branch: Schema, discriminator: string): UnionBranch | null {
  const properties = branch["properties"];
  if (!isRecord(properties)) return null;
  const disc = properties[discriminator];
  if (!isRecord(disc) || typeof disc["const"] !== "string") return null;
  const value = disc["const"] as string;
  const label = typeof branch["title"] === "string" ? (branch["title"] as string) : value;
  return { value, label, schema: branch as Schema };
}

/** A discriminated-union shape, or null when the schema is not one. */
function unionShape(schema: Schema, defs: Defs): UnionShape | null {
  const oneOf = schema["oneOf"];
  if (!Array.isArray(oneOf) || oneOf.length === 0) return null;
  const resolved = oneOf.filter(isRecord).map((branch) => resolveRef(branch as Schema, defs));
  if (resolved.length !== oneOf.length) return null;
  const discriminator = discriminatorOf(schema, resolved);
  if (discriminator === null) return null;
  const branches: UnionBranch[] = [];
  for (const branch of resolved) {
    const built = branchFor(branch, discriminator);
    if (built === null) return null;
    branches.push(built);
  }
  return { kind: "union", discriminator, branches };
}

/**
 * Classify a schema into what it renders as, resolving `$ref` and optional
 * wrapping first. A union wins over an object (its branches are objects); an
 * array-of-objects becomes repeatable rows; a plain object becomes a fieldset;
 * everything else (a scalar, a list of scalars, an untyped `anyOf`) is a leaf.
 */
export function classify(raw: Schema, defs: Defs): Shape {
  const schema = resolveRef(unwrapOptional(raw), defs);
  const union = unionShape(schema, defs);
  if (union !== null) return union;
  if (schema["type"] === "array") {
    const items = arrayItems(schema);
    if (items !== null && isObjectSchema(resolveRef(items, defs))) {
      return { kind: "array", items: resolveRef(items, defs) };
    }
  }
  if (isObjectSchema(schema)) return { kind: "object", entries: objectEntries(schema) };
  return { kind: "leaf", schema };
}

/** The rendered fields of an object schema, or an empty list when it is not one. */
export function objectFields(schema: Schema, defs: Defs): FieldEntry[] {
  const shape = classify(schema, defs);
  return shape.kind === "object" ? shape.entries : [];
}

/** Which resource picker a config leaf pins, from its `x-resource` keyword, or null. */
export type ResourceKind = "agent" | "table" | "secret";

/** The resource a leaf pins through a picker, or null for an ordinary literal leaf. */
export function resourceKind(schema: Schema): ResourceKind | null {
  const value = schema["x-resource"];
  return value === "agent" || value === "table" || value === "secret" ? value : null;
}

/** Whether a `config_schema` leaf opts into binding via `x-bindable: true`. */
export function isBindable(schema: Schema): boolean {
  return schema["x-bindable"] === true;
}

/** `default_top_k` → `Default top k`, for a schema that omits a `title`. */
export function humanise(name: string): string {
  const words = name.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** A leaf's label: its schema `title`, else its humanised field name. */
export function labelOf(schema: Schema, name: string): string {
  return typeof schema["title"] === "string" ? (schema["title"] as string) : humanise(name);
}

/**
 * The structured `JsonSchemaProperty` view of a catalog leaf schema, for handing
 * to `schema-form.tsx`. The catalog serves JSON Schema as an opaque `Record`; the
 * form consumes the same JSON Schema through Pydantic's structured interface, so
 * this is a view of one object, not a conversion — the single cast between the two.
 */
export function asFormProperty(schema: Schema): FormProperty {
  return schema as unknown as FormProperty;
}

/**
 * A one-field object schema wrapping a single scalar leaf, so `schema-form.tsx`
 * renders exactly its existing input (masking, `x-multiline`, `x-suggestions`,
 * enums) for that leaf. `required` places the field in the schema's `required`.
 */
export function singleFieldSchema(name: string, schema: Schema, required: boolean): FormSchema {
  return {
    type: "object",
    properties: { [name]: asFormProperty(schema) },
    required: required ? [name] : [],
  };
}
