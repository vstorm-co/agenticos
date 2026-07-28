"use client";

import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";

import {
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import { cn } from "@/lib/utils";
import type { JsonSchema, JsonSchemaProperty } from "@/types/agents";

/**
 * The option standing for "this field was left alone".
 *
 * A select needs a value for every option and the empty string is not one Radix
 * accepts, so absence needs a name. It never reaches the spec: choosing it
 * stores `undefined`, which is what an untouched field already is.
 */
const UNSET = "__unset__";

interface SchemaFormProps {
  schema: JsonSchema;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  disabled?: boolean;
  /** Prefixed onto field ids so two forms on one page keep distinct labels. */
  idPrefix: string;
  /**
   * What the server said about individual fields, keyed by field name.
   *
   * A generated form has to be able to show a generated refusal. "This is not a
   * service account key - its 'type' is not service_account" is a sentence
   * about one input, and announcing it in a toast puts it somewhere it cannot
   * be acted on and then takes it away.
   */
  errors?: Readonly<Record<string, string>>;
}

/**
 * A form generated from a capability's JSON Schema.
 *
 * The backend publishes `config_schema` precisely so this exists: a developer
 * adds a field to a Pydantic model and it appears here, with its constraints and
 * its help text, without anyone touching the frontend. Hand-maintaining a form
 * per capability is how the two drift - the form keeps accepting a field the
 * backend removed, and the new field nobody added stays unreachable.
 *
 * The supported subset is deliberately small: strings, numbers, booleans and
 * enums, which is what capability configuration actually is. A capability that
 * needs a richer editor should ship its own component rather than push this
 * towards being a general schema renderer.
 *
 * The same generator builds the vault's secret forms, from the schemas
 * `/secrets/kinds` serves - which is why it knows about `const` and about
 * `format: "password"`. Both are Pydantic's own output: the discriminator on a
 * secret payload, and every `SecretStr` in it.
 */
export function SchemaForm({
  schema,
  value,
  onChange,
  disabled,
  idPrefix,
  errors,
}: SchemaFormProps) {
  const properties = Object.entries(schema.properties ?? {}).filter(
    // A field with exactly one legal value is not a question. Rendering it
    // would offer a control whose every other answer the server refuses, and
    // for a secret payload that control is the `kind` the caller already chose.
    ([, property]) => property.const === undefined,
  );
  if (properties.length === 0) return null;

  const set = (key: string, fieldValue: unknown) => onChange({ ...value, [key]: fieldValue });

  return (
    <div className="space-y-4">
      {properties.map(([key, property]) => (
        <SchemaField
          key={key}
          id={`${idPrefix}-${key}`}
          name={key}
          property={property}
          value={value[key]}
          required={schema.required?.includes(key) ?? false}
          disabled={disabled}
          error={errors?.[key]}
          onChange={(fieldValue) => set(key, fieldValue)}
        />
      ))}
    </div>
  );
}

interface SchemaFieldProps {
  id: string;
  name: string;
  property: JsonSchemaProperty;
  value: unknown;
  required: boolean;
  disabled?: boolean;
  error?: string;
  onChange: (value: unknown) => void;
}

function SchemaField({
  id,
  name,
  property,
  value,
  required,
  disabled,
  error,
  onChange,
}: SchemaFieldProps) {
  const label = property.title ?? humanise(name);
  const choices = enumChoices(property);
  const kind = resolveKind(property);
  const masked = isSecret(property);
  // Off on every mount, including a re-open of the same dialog: revealing is a
  // decision about the room you are in, and the room changes.
  const [revealed, setRevealed] = useState(false);
  const errorId = `${id}-error`;
  const invalid =
    error === undefined ? undefined : { "aria-invalid": true, "aria-describedby": errorId };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <Label htmlFor={id}>
          {label}
          {required && <span className="text-muted-foreground"> *</span>}
        </Label>
        {kind === "boolean" && (
          <Switch id={id} checked={value === true} onCheckedChange={onChange} disabled={disabled} />
        )}
      </div>

      {kind === "number" && (
        <Input
          id={id}
          type="number"
          min={property.minimum}
          max={property.maximum}
          value={value === undefined || value === null ? "" : String(value)}
          disabled={disabled}
          // Empty means "unset", which is not the same as zero: an unset field
          // falls back to the capability's own default, and coercing it to 0
          // would silently pick a different behaviour.
          onChange={(event) =>
            onChange(event.target.value === "" ? undefined : Number(event.target.value))
          }
          placeholder={property.default === undefined ? "" : String(property.default)}
          {...invalid}
        />
      )}

      {kind === "enum" && choices !== null && (
        <Select
          value={typeof value === "string" ? value : UNSET}
          disabled={disabled}
          onValueChange={(choice) => onChange(choice === UNSET ? undefined : choice)}
        >
          <SelectTrigger id={id}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {/*
              A field with a fixed set of values still has the state of nobody
              having picked one, and for an optional field that state is a real
              answer - it is what defers to whatever is configured further down.
              Offered only where the schema allows it: a required field has no
              such state and offering it would produce a spec the backend
              refuses.
            */}
            {!required && <SelectItem value={UNSET}>Not set</SelectItem>}
            {choices.map((choice) => (
              <SelectItem key={choice} value={choice}>
                {choice}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      {kind === "string" && (
        <div className="relative">
          <Input
            id={id}
            // Masked wherever the schema says so, which for a Pydantic model is
            // every `SecretStr`. Not because typing a key is dangerous, but
            // because these fields are filled in meetings and on shared screens.
            type={masked && !revealed ? "password" : undefined}
            autoComplete={masked ? "off" : undefined}
            maxLength={property.maxLength}
            value={typeof value === "string" ? value : ""}
            disabled={disabled}
            onChange={(event) =>
              onChange(event.target.value === "" ? undefined : event.target.value)
            }
            placeholder={property.default === undefined ? "" : String(property.default)}
            className={cn(masked && "pr-10 font-mono")}
            {...invalid}
          />
          {/* A key is pasted, and a paste that went wrong is invisible behind
              dots - a trailing newline, half a value, the wrong clipboard entry.
              The vault never shows a stored secret again, so this is the only
              moment its value can be checked at all. */}
          {masked && (
            <button
              type="button"
              onClick={() => setRevealed((shown) => !shown)}
              disabled={disabled}
              aria-label={revealed ? `Hide ${label}` : `Show ${label}`}
              aria-pressed={revealed}
              className="text-muted-foreground hover:text-foreground absolute top-1/2 right-1 -translate-y-1/2 rounded-md p-2 disabled:pointer-events-none disabled:opacity-50"
            >
              {revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          )}
        </div>
      )}

      {property.description && (
        <p className="text-muted-foreground text-xs">{property.description}</p>
      )}

      {error !== undefined && (
        <p id={errorId} className="text-destructive text-xs">
          {error}
        </p>
      )}
    </div>
  );
}

type FieldKind = "string" | "number" | "boolean" | "enum";

/**
 * What kind of input a property needs.
 *
 * Pydantic renders an optional field as `anyOf: [{type: "x"}, {type: "null"}]`
 * rather than a plain type, so the null branch has to be looked past - without
 * that, every optional field would fall through to a text box.
 */
function resolveKind(property: JsonSchemaProperty): FieldKind {
  // Before the type check, not after: a `Literal` is a string, and a text box
  // for a closed set of values is a way to type one the backend will refuse.
  if (enumChoices(property) !== null) return "enum";

  const candidates = property.anyOf
    ? property.anyOf.map((entry) => entry.type)
    : [property.type].flat();

  const type = candidates.find((entry) => entry !== undefined && entry !== "null");
  if (type === "integer" || type === "number") return "number";
  if (type === "boolean") return "boolean";
  return "string";
}

/**
 * The values a property is restricted to, or null when it is not restricted.
 *
 * An optional `Literal` arrives as `anyOf: [{enum: [...]}, {type: "null"}]`, so
 * the branches are searched as well as the property itself. Non-string members
 * are dropped rather than rendered: this form's controls put their value back
 * as a string, and a select that turned `3` into `"3"` would fail validation
 * somewhere far from here.
 */
function enumChoices(property: JsonSchemaProperty): string[] | null {
  const values = property.enum ?? property.anyOf?.find((entry) => entry.enum)?.enum;
  if (values === undefined) return null;
  return values.filter((value): value is string => typeof value === "string");
}

/**
 * Whether this field holds something that must not be shown while it is typed.
 *
 * The null branch is searched as well as the property itself: an optional
 * `SecretStr` arrives as `anyOf: [{format: "password"}, {type: "null"}]`, and
 * `aws_session_token` is exactly that - the one field of the five kinds where
 * missing the branch would render a real credential in the clear.
 */
function isSecret(property: JsonSchemaProperty): boolean {
  return (
    property.format === "password" ||
    (property.anyOf?.some((entry) => entry.format === "password") ?? false)
  );
}

/** `default_top_k` -> `Default top k`, for schemas that omit a title. */
function humanise(name: string): string {
  const words = name.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}
