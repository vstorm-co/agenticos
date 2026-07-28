"use client";

import { SchemaForm } from "@/components/agents/schema-form";
import type { JsonSchema } from "@/types/agents";
import type { SecretKind, SecretKindInfo, SecretPayload } from "@/types/secrets";

/**
 * The inputs one kind of secret needs, generated from the schema the server
 * publishes for it.
 *
 * There are five kinds and there will be more, and each one is a Pydantic model
 * whose fields the backend already describes in JSON Schema at
 * `GET /secrets/kinds`. Five hand-written forms here would be five forms that
 * stop matching the day somebody adds a field — and the failure mode is not a
 * broken build, it is a credential saved without its region that authenticates
 * nowhere.
 *
 * So there is one form, and it is the same generator the Builder uses for
 * capability configuration. What it knows about secrets specifically is two
 * lines of JSON Schema: `const` (a payload states its own `kind`, which is the
 * caller's to supply, not the reader's to answer) and `format: "password"`
 * (every `SecretStr`, masked).
 */
interface SecretFieldsProps {
  /** The kind being entered, with the schema its inputs come from. */
  info: SecretKindInfo;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  disabled?: boolean;
  /** Prefixed onto every field id, so two forms on one page keep distinct labels. */
  idPrefix: string;
  /** What the server said about individual fields, keyed by field name. */
  errors?: Readonly<Record<string, string>>;
}

export function SecretFields({
  info,
  value,
  onChange,
  disabled,
  idPrefix,
  errors,
}: SecretFieldsProps) {
  return (
    <div className="space-y-4">
      <p className="text-muted-foreground text-xs leading-relaxed">{info.description}</p>
      <SchemaForm
        schema={info.json_schema}
        value={value}
        onChange={onChange}
        disabled={disabled}
        idPrefix={idPrefix}
        errors={errors}
      />
    </div>
  );
}

/**
 * The fields a form generated from `schema` actually renders.
 *
 * Used to tell `submitFailure` which of the server's complaints this form can
 * show. Without it a message about `api_version` would be announced in a toast
 * while the input it belongs to sat there unmarked.
 */
export function secretFieldNames(schema: JsonSchema): string[] {
  return Object.entries(schema.properties ?? {})
    .filter(([, property]) => property.const === undefined)
    .map(([name]) => name);
}

/**
 * Whether every required field has an answer.
 *
 * The server refuses an incomplete payload, so this only decides whether the
 * submit button is offered — being told a region is missing before sending
 * beats being told after. A field the form cleared reads back as `undefined`,
 * which is what an untouched one already is.
 */
export function isSecretComplete(schema: JsonSchema, value: Record<string, unknown>): boolean {
  const required = schema.required ?? [];
  return secretFieldNames(schema)
    .filter((name) => required.includes(name))
    .every((name) => {
      const answer = value[name];
      return typeof answer === "string" ? answer.trim().length > 0 : answer !== undefined;
    });
}

/**
 * The payload for the wire: the discriminator, then what was typed.
 *
 * `kind` is written first and the values spread over it, which is deliberate —
 * a schema cannot contribute a `kind` of its own, because the generated form
 * never renders a `const` field in the first place.
 */
export function toSecretPayload(kind: SecretKind, value: Record<string, unknown>): SecretPayload {
  return { ...value, kind };
}
