import type { JsonSchema, Port } from "./types";

/**
 * The typed fields a "Manual or API" trigger may declare - the client mirror of
 * `app/workflows/nodes/core_input/_handler.py`.
 *
 * Declared fields are the run's contract: a run is refused at the start when its
 * input does not fit them, the Run dialog asks for each one by name, and a later
 * step binds `payload.<field>` knowing its type. A trigger with none takes any
 * JSON object, as it always has.
 */

export const INPUT_FIELD_TYPES = [
  "text",
  "number",
  "integer",
  "boolean",
  "date",
  "choice",
] as const;

export type InputFieldType = (typeof INPUT_FIELD_TYPES)[number];

export interface InputField {
  name: string;
  label: string | null;
  type: InputFieldType;
  required: boolean;
  description: string | null;
  options: string[];
}

/** What a field's name must look like: a path segment a binding can name. */
export const FIELD_NAME = /^[a-z][a-z0-9_]{0,63}$/;

/** The most fields one trigger declares - `MAX_FIELDS`. */
export const MAX_FIELDS = 50;

/** The most options one choice offers - `MAX_OPTIONS`. */
export const MAX_OPTIONS = 50;

function isInputFieldType(value: unknown): value is InputFieldType {
  return typeof value === "string" && (INPUT_FIELD_TYPES as readonly string[]).includes(value);
}

function textOrNull(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

/** The fields a trigger's config declares, in order - entries of no known shape skipped. */
export function inputFieldsOf(config: Record<string, unknown>): InputField[] {
  const fields = config["fields"];
  if (!Array.isArray(fields)) return [];
  return fields.flatMap((entry: unknown): InputField[] => {
    if (typeof entry !== "object" || entry === null) return [];
    const field = entry as Record<string, unknown>;
    const name = field["name"];
    const type = field["type"];
    if (typeof name !== "string" || !isInputFieldType(type)) return [];
    const options = Array.isArray(field["options"])
      ? field["options"].filter((option): option is string => typeof option === "string")
      : [];
    return [
      {
        name,
        label: textOrNull(field["label"]),
        type,
        required: field["required"] !== false,
        description: textOrNull(field["description"]),
        options,
      },
    ];
  });
}

/** The words a field is shown under: its label, or its name. */
export function fieldCaption(field: Pick<InputField, "name" | "label">): string {
  return field.label ?? field.name;
}

const JSON_TYPE: Record<InputFieldType, string> = {
  text: "string",
  number: "number",
  integer: "integer",
  boolean: "boolean",
  date: "string",
  choice: "string",
};

/**
 * The JSON Schema of one field as the backend's generated model emits it: the
 * value's own type, or that or `null` when the field may be left out.
 */
function fieldSchema(field: InputField): JsonSchema {
  const own: JsonSchema = { type: JSON_TYPE[field.type] };
  const title = fieldCaption(field);
  return field.required
    ? { ...own, title }
    : { anyOf: [own, { type: "null" }], default: null, title };
}

/** The shape `payload` has when a trigger declares `fields`. */
export function payloadSchema(fields: readonly InputField[]): JsonSchema {
  return {
    type: "object",
    title: "Payload",
    additionalProperties: false,
    properties: Object.fromEntries(fields.map((field) => [field.name, fieldSchema(field)])),
    required: fields.filter((field) => field.required).map((field) => field.name),
  };
}

/**
 * The trigger's `out` port with `payload` typed by its declared fields, or the
 * port unchanged when it declares none - its payload is then any object.
 */
export function typedPayloadPort(port: Port, fields: readonly InputField[]): Port {
  const schema = port.schema;
  if (fields.length === 0 || schema === null || port.kind !== "output") return port;
  const properties = (schema["properties"] ?? {}) as Record<string, JsonSchema>;
  return {
    ...port,
    schema: { ...schema, properties: { ...properties, payload: payloadSchema(fields) } },
  };
}

/** A value the Run form holds for one field: typed text, or a switch's state. */
export type FormValue = string | boolean;

/** Each field's starting value in the Run form: off for a switch, empty otherwise. */
export function initialValues(fields: readonly InputField[]): Record<string, FormValue> {
  return Object.fromEntries(
    fields.map((field) => [field.name, field.type === "boolean" ? false : ""]),
  );
}

/** Why a field's value cannot start the run. */
export type FieldProblem = "required" | "number" | "integer" | "date" | "choice";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function isIsoDate(text: string): boolean {
  if (!ISO_DATE.test(text)) return false;
  const parsed = new Date(`${text}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().startsWith(text);
}

/** One field's value as the run's input holds it, or why it cannot be. */
function fieldValue(
  field: InputField,
  value: FormValue,
): { value: unknown } | { problem: FieldProblem } | null {
  if (typeof value === "boolean") return { value };
  const text = value.trim();
  if (text === "") return field.required ? { problem: "required" } : null;
  switch (field.type) {
    case "number": {
      const number = Number(text);
      return Number.isFinite(number) ? { value: number } : { problem: "number" };
    }
    case "integer": {
      const number = Number(text);
      return Number.isSafeInteger(number) ? { value: number } : { problem: "integer" };
    }
    case "date":
      return isIsoDate(text) ? { value: text } : { problem: "date" };
    case "choice":
      return field.options.includes(text) ? { value: text } : { problem: "choice" };
    default:
      return { value: text };
  }
}

/**
 * The run's input from the Run form, typed the way the trigger declares it, or
 * what is wrong with each field that cannot start the run. An optional field
 * left empty is left out.
 */
export function runInputFrom(
  fields: readonly InputField[],
  values: Readonly<Record<string, FormValue>>,
): { input: Record<string, unknown> } | { problems: Record<string, FieldProblem> } {
  const input: Record<string, unknown> = {};
  const problems: Record<string, FieldProblem> = {};
  for (const field of fields) {
    const result = fieldValue(field, values[field.name] ?? (field.type === "boolean" ? false : ""));
    if (result === null) continue;
    if ("problem" in result) problems[field.name] = result.problem;
    else input[field.name] = result.value;
  }
  return Object.keys(problems).length > 0 ? { problems } : { input };
}
