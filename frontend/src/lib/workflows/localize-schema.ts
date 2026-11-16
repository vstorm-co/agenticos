/** What a field says, in the reader's language - only what the catalog holds. */
export interface FieldCopy {
  title?: string;
  description?: string;
  placeholder?: string;
  hint?: string;
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
 * inside `auth` - through inline objects, `$ref`s and `anyOf` branches, the way
 * the registry's own copy is collected. A `$defs` model shared by two fields is
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
    throughDef(property.$ref, path);
    if (Array.isArray(property.anyOf)) {
      for (const branch of property.anyOf) if (isRecord(branch)) throughDef(branch.$ref, path);
    }
    if (isRecord(property.properties)) out = nested(out, path);
    return out;
  };

  const localized = nested(schema, []);
  return isRecord(schema.$defs) ? { ...localized, $defs: defs } : localized;
}
