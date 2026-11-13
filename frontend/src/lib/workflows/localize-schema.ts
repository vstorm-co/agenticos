/** What a field says, in the reader's language - only what the catalog holds. */
export interface FieldCopy {
  title?: string;
  description?: string;
  placeholder?: string;
  hint?: string;
  /** What one of a choice's values is called, by the value - none when the catalog holds none. */
  option?: (value: string) => string | undefined;
}

type Json = Record<string, unknown>;

function isRecord(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * A node's config or input schema with each field's title, description,
 * placeholder and hint in the reader's language, wherever `copyOf` has one.
 *
 * A field is found by its path of property names - `auth__token` for `token`
 * inside `auth`, `choices__items__label` for `label` in each of a list's items -
 * through inline objects, list items, `$ref`s and `anyOf` branches, the way the
 * registry's own copy is collected. A `$defs` model shared by two fields is
 * worded once, by the first path that reaches it. Nothing else changes, and the
 * schema served is never mutated.
 */
export function localizeSchema(schema: Json, copyOf: (path: string) => FieldCopy): Json {
  const defs: Json = isRecord(schema.$defs) ? { ...schema.$defs } : {};
  const seen = new Set<string>();

  const defName = (ref: unknown): string | null =>
    typeof ref === "string" && ref.startsWith("#/$defs/") ? ref.slice("#/$defs/".length) : null;

  const nested = (target: Json, path: string[]): Json => {
    const properties = target.properties;
    if (!isRecord(properties)) return target;
    const next: Json = {};
    for (const [name, value] of Object.entries(properties)) {
      next[name] = isRecord(value) ? field(value, [...path, name]) : value;
    }
    return { ...target, properties: next };
  };

  const throughDef = (ref: unknown, path: string[]): void => {
    const name = defName(ref);
    if (name === null || seen.has(name) || !isRecord(defs[name])) return;
    seen.add(name);
    defs[name] = nested(defs[name] as Json, path);
  };

  const field = (property: Json, path: string[]): Json => {
    const copy = copyOf(path.join("__"));
    let out: Json = { ...property };
    if (copy.title !== undefined) out.title = copy.title;
    if (copy.description !== undefined) out.description = copy.description;
    if (copy.placeholder !== undefined) out["x-placeholder"] = copy.placeholder;
    if (copy.hint !== undefined) out["x-hint"] = copy.hint;
    const labels = property["x-enum-labels"];
    if (copy.option !== undefined && isRecord(labels)) {
      const option = copy.option;
      out["x-enum-labels"] = Object.fromEntries(
        Object.entries(labels).map(([value, label]) => [value, option(value) ?? label]),
      );
    }
    throughDef(property.$ref, path);
    if (isRecord(property.properties)) out = nested(out, path);
    out = listItems(out, path);
    if (Array.isArray(property.anyOf)) {
      out.anyOf = property.anyOf.map((branch: unknown) => {
        if (!isRecord(branch)) return branch;
        throughDef(branch.$ref, path);
        return listItems(branch, path);
      });
    }
    return out;
  };

  // A list's items are worded under the list's path and `items`: `choices__items__label`.
  const listItems = (schema: Json, path: string[]): Json => {
    if (!isRecord(schema.items)) return schema;
    const at = [...path, "items"];
    throughDef(schema.items.$ref, at);
    return isRecord(schema.items.properties)
      ? { ...schema, items: nested(schema.items, at) }
      : schema;
  };

  const localized = nested(schema, []);
  return isRecord(schema.$defs) ? { ...localized, $defs: defs } : localized;
}
