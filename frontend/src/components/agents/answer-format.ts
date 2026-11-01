/**
 * The shape an agent's answer takes, as the Builder edits it: a list of named,
 * typed fields, and the JSON Schema `AgentSpec.output_schema` stores.
 *
 * The field list is the everyday way in - a name, a type, a line saying what
 * goes there, whether it must be there - and it only ever writes schemas it can
 * read back. A schema written elsewhere (YAML, the API) that uses more than the
 * list can say is shown and edited as JSON instead, never flattened.
 */

export type AnswerFieldType = "string" | "number" | "integer" | "boolean" | "string_list";

export const ANSWER_FIELD_TYPES: readonly AnswerFieldType[] = [
  "string",
  "number",
  "integer",
  "boolean",
  "string_list",
];

export interface AnswerField {
  name: string;
  type: AnswerFieldType;
  description: string;
  required: boolean;
}

type Schema = Record<string, unknown>;

function propertyOf(field: AnswerField): Schema {
  const shape: Schema =
    field.type === "string_list"
      ? { type: "array", items: { type: "string" } }
      : { type: field.type };
  const description = field.description.trim();
  return description === "" ? shape : { ...shape, description };
}

/** The JSON Schema a field list stands for: an object with exactly those fields. */
export function schemaOf(fields: readonly AnswerField[]): Schema {
  const named = fields.filter((field) => field.name.trim() !== "");
  return {
    type: "object",
    properties: Object.fromEntries(named.map((field) => [field.name.trim(), propertyOf(field)])),
    required: named.filter((field) => field.required).map((field) => field.name.trim()),
    additionalProperties: false,
  };
}

function isRecord(value: unknown): value is Schema {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function typeOf(property: Schema): AnswerFieldType | null {
  const allowed = new Set(["type", "description", "items"]);
  if (Object.keys(property).some((key) => !allowed.has(key))) return null;
  if (property["type"] === "array") {
    const items = property["items"];
    return isRecord(items) && Object.keys(items).length === 1 && items["type"] === "string"
      ? "string_list"
      : null;
  }
  if ("items" in property) return null;
  const type = property["type"];
  return ANSWER_FIELD_TYPES.find((candidate) => candidate === type) ?? null;
}

/**
 * The field list a schema is, or null when it says more than a list can - so
 * the form edits it as JSON rather than dropping what it cannot show.
 */
export function fieldsOf(schema: Schema): AnswerField[] | null {
  const allowed = new Set(["type", "properties", "required", "additionalProperties"]);
  if (schema["type"] !== "object" || Object.keys(schema).some((key) => !allowed.has(key))) {
    return null;
  }
  const properties = schema["properties"] ?? {};
  const required = schema["required"] ?? [];
  if (!isRecord(properties) || !Array.isArray(required)) return null;
  const fields: AnswerField[] = [];
  for (const [name, property] of Object.entries(properties)) {
    if (!isRecord(property)) return null;
    const type = typeOf(property);
    if (type === null) return null;
    const description = property["description"];
    fields.push({
      name,
      type,
      description: typeof description === "string" ? description : "",
      required: required.includes(name),
    });
  }
  return fields;
}

/** Parse the JSON editor's text: an object schema, or the reason it is not one. */
export function parseSchema(text: string): Schema | "notJson" | "notObject" {
  try {
    const value: unknown = JSON.parse(text);
    return isRecord(value) && value["type"] === "object" ? value : "notObject";
  } catch {
    return "notJson";
  }
}

/** A field list's first row, so switching to structured opens on something to fill in. */
export const FIRST_FIELD: AnswerField = {
  name: "answer",
  type: "string",
  description: "",
  required: true,
};
