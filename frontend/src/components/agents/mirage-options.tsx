"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { SchemaForm } from "@/components/agents/schema-form";
import { CodeArea } from "@/components/ui/code-area";
import { Label } from "@/components/ui";
import type { JsonSchema, JsonSchemaProperty } from "@/types/agents";

type StructuredKind = "object" | "array";

function structuredKind(property: JsonSchemaProperty): StructuredKind | null {
  const types = Array.isArray(property.type) ? property.type : [property.type];
  if (types.includes("object")) return "object";
  if (types.includes("array") && property.items?.type !== "string") return "array";
  for (const branch of property.anyOf ?? []) {
    const kind = structuredKind(branch);
    if (kind !== null) return kind;
  }
  return null;
}

function nullable(property: JsonSchemaProperty): boolean {
  return (
    property.type === "null" ||
    (Array.isArray(property.type) && property.type.includes("null")) ||
    (property.anyOf?.some((branch) => nullable(branch)) ?? false)
  );
}

function parsed(
  text: string,
  kind: StructuredKind,
  required: boolean,
  allowsNull: boolean,
): { ok: true; value: unknown } | { ok: false } {
  if (text.trim() === "") return required ? { ok: false } : { ok: true, value: undefined };
  try {
    const value: unknown = JSON.parse(text);
    const valid =
      value === null
        ? allowsNull
        : kind === "array"
          ? Array.isArray(value)
          : typeof value === "object" && !Array.isArray(value);
    return valid ? { ok: true, value } : { ok: false };
  } catch {
    return { ok: false };
  }
}

interface StructuredOptionProps {
  id: string;
  name: string;
  property: JsonSchemaProperty;
  kind: StructuredKind;
  value: unknown;
  required: boolean;
  disabled?: boolean;
  onChange: (value: unknown) => void;
}

function StructuredOption({
  id,
  name,
  property,
  kind,
  value,
  required,
  disabled,
  onChange,
}: StructuredOptionProps) {
  const t = useTranslations("mirage");
  const stored = JSON.stringify(value);
  const defaultValue =
    property.default === undefined ? (kind === "object" ? {} : []) : property.default;
  const displayed = JSON.stringify(value === undefined ? defaultValue : value, null, 2) ?? "";
  const [text, setText] = useState(displayed);
  const accepted = useRef(stored);
  useEffect(() => {
    if (stored !== accepted.current) {
      accepted.current = stored;
      setText(displayed);
    }
  }, [stored, displayed]);
  const invalid = !parsed(text, kind, required, nullable(property)).ok;
  const label = t("jsonLabel", { name: property.title ?? name });
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <CodeArea
        id={id}
        name={`${name}.json`}
        aria-label={label}
        value={text}
        readOnly={disabled}
        invalid={invalid}
        describedBy={invalid ? `${id}-error` : `${id}-hint`}
        className="min-h-32"
        onChange={(next) => {
          setText(next);
          const result = parsed(next, kind, required, nullable(property));
          if (result.ok) {
            accepted.current = JSON.stringify(result.value);
            onChange(result.value);
          }
        }}
      />
      <p id={`${id}-hint`} className="text-muted-foreground text-xs">
        {property.description ?? t("jsonHint")}
      </p>
      {invalid && (
        <p id={`${id}-error`} role="alert" className="text-destructive text-xs">
          {t("jsonInvalid")}
        </p>
      )}
    </div>
  );
}

interface MirageOptionsProps {
  schema: JsonSchema;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  disabled?: boolean;
  idPrefix: string;
}

export function MirageOptions({ schema, value, onChange, disabled, idPrefix }: MirageOptionsProps) {
  const fields = Object.entries(schema.properties ?? {}).map(([name, property]) => ({
    name,
    property,
    kind: structuredKind(property),
  }));
  const simple = Object.fromEntries(
    fields.filter((field) => field.kind === null).map(({ name, property }) => [name, property]),
  );
  return (
    <div className="space-y-4">
      <SchemaForm
        schema={{ ...schema, properties: simple }}
        value={value}
        onChange={onChange}
        disabled={disabled}
        idPrefix={idPrefix}
      />
      {fields.map(({ name, property, kind }) =>
        kind === null ? null : (
          <StructuredOption
            key={name}
            id={`${idPrefix}-${name}`}
            name={name}
            property={property}
            kind={kind}
            value={value[name]}
            required={schema.required?.includes(name) ?? false}
            disabled={disabled}
            onChange={(next) => {
              const options = { ...value };
              if (next === undefined) delete options[name];
              else options[name] = next;
              onChange(options);
            }}
          />
        ),
      )}
    </div>
  );
}
