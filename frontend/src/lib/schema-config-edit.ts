import type { JsonSchema, JsonSchemaProperty } from "@/types/agents";

type Config = Record<string, unknown>;

function effective(schema: JsonSchema, value: Config, field: string): unknown {
  return value[field] ?? schema.properties?.[field]?.default;
}

export function conditionalChoices(
  property: JsonSchemaProperty,
  schema: JsonSchema,
  value: Config,
): string[] | undefined {
  const when = property["x-enum-when"];
  if (when === undefined) return undefined;
  const read = (field: string) => String(effective(schema, value, field));
  if (when.unless?.equals.includes(read(when.unless.field))) return undefined;
  return when.choices[read(when.field)] ?? [];
}

export function visible(property: JsonSchemaProperty, schema: JsonSchema, value: Config): boolean {
  const when = property["x-visible-when"];
  return when === undefined || when.equals.includes(String(effective(schema, value, when.field)));
}

/**
 * Edit a field without sending dependent settings invalid for the new mode.
 * An editor can keep those settings in session memory to restore when switching back.
 */
export function editSchemaConfig(
  schema: JsonSchema,
  value: Config,
  key: string,
  fieldValue: unknown,
  remembered?: Map<string, unknown>,
): Config {
  const next = { ...value, [key]: fieldValue };
  for (const [other, property] of Object.entries(schema.properties ?? {})) {
    const visibility = property["x-visible-when"];
    const choices = property["x-enum-when"];
    const affectsVisibility = visibility?.field === key;
    const affectsChoices = choices?.field === key || choices?.unless?.field === key;
    if (!affectsVisibility && !affectsChoices) continue;

    const fields = [visibility?.field, choices?.field, choices?.unless?.field];
    const memoryKey = (config: Config) =>
      JSON.stringify([other, ...fields.map((field) => field && effective(schema, config, field))]);
    const available = visible(property, schema, next);
    const allowed = affectsChoices ? conditionalChoices(property, schema, next) : undefined;
    const nextKey = memoryKey(next);
    const previousKey = memoryKey(value);
    const saved = remembered?.get(nextKey);
    if (
      remembered &&
      available &&
      nextKey !== previousKey &&
      saved !== undefined &&
      (allowed === undefined || allowed.includes(String(saved)))
    ) {
      if (next[other] !== undefined) remembered.set(previousKey, next[other]);
      next[other] = saved;
      remembered.delete(nextKey);
    }
    if (
      (affectsVisibility && !available) ||
      (next[other] !== undefined && allowed !== undefined && !allowed.includes(String(next[other])))
    ) {
      if (next[other] !== undefined) remembered?.set(previousKey, next[other]);
      next[other] = undefined;
    }
  }
  return next;
}
