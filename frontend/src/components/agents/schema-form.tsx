"use client";

import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";

import {
  Input,
  Label,
  MarkdownEditor,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import { BrandIcon, type BrandName } from "@/components/icons/brand-icon";
import { BRAND_GLYPHS } from "@/lib/brand-glyphs.generated";
import { cn } from "@/lib/utils";
import type { JsonSchema, JsonSchemaProperty } from "@/types/agents";
import { useTranslations } from "next-intl";

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
 * The supported subset is deliberately small: strings, numbers, booleans, enums
 * and a list of strings, which is what capability configuration actually is. A
 * capability that needs a richer editor should ship its own component rather
 * than push this towards being a general schema renderer.
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
  const t = useTranslations("agents");
  const label = property.title ?? humanise(name);
  const choices = enumChoices(property);
  const kind = resolveKind(property);
  const masked = isSecret(property);
  // What the field shows while nobody has touched it. Shown as the *value*
  // rather than as placeholder grey: a field reading "Not set" over a
  // capability that will happily run says nothing about what it will do, and
  // three empty boxes under a strategy picker read as three decisions still to
  // make. Nothing is stored until it is edited — an untouched field and one set
  // to its default mean the same thing to the server, and writing the default
  // in would freeze it against a later change in code.
  const fallback = defaultOf(property);
  const multiline = property["x-multiline"] === true;
  // Off on every mount, including a re-open of the same dialog: revealing is a
  // decision about the room you are in, and the room changes.
  const [revealed, setRevealed] = useState(false);
  // A list is edited as text and stored as an array, so the text is state of its
  // own. Deriving it from the array instead would re-render the separator away
  // the moment it is typed, leaving a field nobody can put a second entry in.
  const [listText, setListText] = useState(() => (Array.isArray(value) ? value.join(", ") : ""));
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
          <Switch
            id={id}
            checked={value === undefined ? fallback === true : value === true}
            onCheckedChange={onChange}
            disabled={disabled}
          />
        )}
      </div>

      {kind === "number" && (
        <Input
          id={id}
          type="number"
          min={property.minimum}
          max={property.maximum}
          value={numberText(value, fallback)}
          disabled={disabled}
          // Empty means "unset", which is not the same as zero: an unset field
          // falls back to the capability's own default, and coercing it to 0
          // would silently pick a different behaviour.
          onChange={(event) =>
            onChange(event.target.value === "" ? undefined : Number(event.target.value))
          }
          {...invalid}
        />
      )}

      {kind === "enum" && choices !== null && (
        <Select
          value={
            typeof value === "string" ? value : typeof fallback === "string" ? fallback : UNSET
          }
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
              such state, and neither has one with a default, where "not set"
              and the default are the same behaviour under two names.
            */}
            {!required && fallback === undefined && (
              <SelectItem value={UNSET}>{t("notSet")}</SelectItem>
            )}
            {choices.map((choice) => (
              <SelectItem key={choice} value={choice}>
                <span className="flex items-center gap-2">
                  {/* The service's own mark, where the value names one. A list of
                      search providers or model vendors is read by their logos
                      before it is read at all, and the choice is the one thing
                      on these forms that is a product rather than a setting. */}
                  {isBrand(choice) && <BrandIcon name={choice} className="h-3.5 w-3.5 shrink-0" />}
                  {enumLabel(property, choice)}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      {kind === "stringList" && (
        <Input
          id={id}
          value={listText}
          placeholder={t("separateWithCommas")}
          disabled={disabled}
          // Blank stores nothing rather than an empty array, which is the same
          // distinction the other inputs make and the one the server reads: an
          // absent list is "no restriction", where `[]` is a list of nothing.
          onChange={(event) => {
            setListText(event.target.value);
            onChange(parseList(event.target.value));
          }}
          {...invalid}
        />
      )}

      {kind === "string" && multiline && (
        /* The same control the agent's own instructions get. A prompt is
           paragraphs - a one-line box for one is a field nobody can read what
           they are editing in, and a plain textarea shows Markdown as asterisks.
           The schema says which fields are prose: Pydantic has no notion of
           multiline, so a capability marks it the way it marks enum labels. */
        <MarkdownEditor
          id={id}
          label={label}
          rows={10}
          value={typeof value === "string" ? value : typeof fallback === "string" ? fallback : ""}
          disabled={disabled}
          onChange={(next) => onChange(next === "" ? undefined : next)}
          invalid={error !== undefined}
          describedBy={error === undefined ? undefined : errorId}
        />
      )}

      {kind === "string" && !multiline && (
        <div className="relative">
          <Input
            id={id}
            // Masked wherever the schema says so, which for a Pydantic model is
            // every `SecretStr`. Not because typing a key is dangerous, but
            // because these fields are filled in meetings and on shared screens.
            type={masked && !revealed ? "password" : undefined}
            autoComplete={masked ? "off" : undefined}
            maxLength={property.maxLength}
            value={typeof value === "string" ? value : typeof fallback === "string" ? fallback : ""}
            disabled={disabled}
            onChange={(event) =>
              onChange(event.target.value === "" ? undefined : event.target.value)
            }
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
              aria-label={
                revealed ? t("hideNamed", { name: label }) : t("showNamed", { name: label })
              }
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

type FieldKind = "string" | "number" | "boolean" | "enum" | "stringList";

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
  if (isStringList(property)) return "stringList";

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
 * Whether this field is a list of strings, which is the one array it renders.
 *
 * `list[str] | None` arrives as `anyOf: [{type: "array", items: …}, {type:
 * "null"}]`, so the branch carries the `items` rather than the property. An
 * array of anything else falls through to a text box, as it did before this
 * existed: a list of objects is the richer editor a capability should ship
 * itself. Without this every list was a text box, so typing a hostname into one
 * stored the string and the server refused the spec - which left `web_fetch`'s
 * domain filters publishable only by leaving them empty.
 */
function isStringList(property: JsonSchemaProperty): boolean {
  const branch = property.anyOf?.find((entry) => entry.type === "array") ?? property;
  return branch.type === "array" && branch.items?.type === "string";
}

/** The entries typed into a list field, or `undefined` when it is blank. */
function parseList(text: string): string[] | undefined {
  const entries = text.split(/[\s,]+/).filter((entry) => entry !== "");
  return entries.length === 0 ? undefined : entries;
}

/**
 * What this field falls back to when nobody has set it, or `undefined`.
 *
 * Pydantic writes `"default": null` for every optional field, which is not a
 * default at all - it is the absence of one, spelt in JSON. Rendering it would
 * put the word `null` in a text box.
 */
function defaultOf(property: JsonSchemaProperty): unknown {
  return property.default === null ? undefined : property.default;
}

/** A number input's text, showing the schema's default until somebody types. */
function numberText(value: unknown, fallback: unknown): string {
  const shown = value === undefined || value === null ? fallback : value;
  return typeof shown === "number" || typeof shown === "string" ? String(shown) : "";
}

/** Whether an enum's stored value is also the name of a mark the console holds. */
function isBrand(choice: string): choice is BrandName {
  return choice in BRAND_GLYPHS;
}

/**
 * What one choice of an enum is called in the picker.
 *
 * The values are spec format - `clear_tool_results`, `sliding_window` - and a
 * dropdown of them is a decision somebody makes by guessing. A schema may carry
 * `x-enum-labels` to say what each one does.
 *
 * It is an extension keyword because JSON Schema has none for this, and it
 * belongs in the schema for the same reason `description` does: the copy that
 * explains a field lives beside its definition, not in a table here that a
 * renamed value silently outlives.
 *
 * Without labels the value is shown verbatim rather than prettified. Some of
 * these are identifiers a person recognises - a tool id, an effort level - and
 * turning `get_channel_info` into `Get channel info` in a picker whose choice is
 * stored as the former is a rename this form is not entitled to make.
 */
function enumLabel(property: JsonSchemaProperty, choice: string): string {
  const labels =
    property["x-enum-labels"] ??
    property.anyOf?.find((entry) => entry["x-enum-labels"])?.["x-enum-labels"];
  return labels?.[choice] ?? choice;
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
