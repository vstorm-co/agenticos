"use client";

import { Cog } from "lucide-react";
import { useTranslations } from "next-intl";

import { Input, Label, Switch, Textarea } from "@/components/ui";
import type { ConnectorConfigField, ConnectorInfo, SyncSourceCreate } from "@/lib/rag-api";

export function ConfigureStep({
  connector,
  form,
  setForm,
  errors,
}: {
  connector: ConnectorInfo;
  form: SyncSourceCreate;
  setForm: React.Dispatch<React.SetStateAction<SyncSourceCreate>>;
  /**
   * What the server said about individual config fields, by field name.
   *
   * The connector is what decides whether a folder id is a folder id, and it
   * answers about the field. Announcing that in a toast over a step holding
   * four inputs puts it where it cannot be acted on (#897).
   */
  errors?: Readonly<Record<string, string>>;
}) {
  const t = useTranslations("rag");
  const fields = Object.entries(connector.config_schema);

  if (fields.length === 0) {
    return (
      <div className="border-foreground/10 bg-foreground/[0.03] rounded-xl border p-5 text-center">
        <Cog className="text-foreground/45 mx-auto h-6 w-6" />
        <p className="text-foreground/70 mt-3 text-sm">
          {t.rich("configureNoneNeeded", {
            name: connector.name,
            emphasis: (chunks) => <span className="text-foreground font-medium">{chunks}</span>,
          })}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-foreground/65 text-sm">
        {t.rich("configureRequiredFields", {
          name: connector.name,
          required: (chunks) => <span className="text-destructive">{chunks}</span>,
        })}
      </p>
      {fields.map(([key, field]) => (
        <ConfigField
          key={key}
          name={key}
          field={field}
          value={form.config[key]}
          error={errors?.[key]}
          onChange={(value) => setForm((f) => ({ ...f, config: { ...f.config, [key]: value } }))}
        />
      ))}
    </div>
  );
}

function ConfigField({
  name,
  field,
  value,
  error,
  onChange,
}: {
  name: string;
  field: ConnectorConfigField;
  value: unknown;
  error?: string;
  onChange: (value: unknown) => void;
}) {
  const id = `cfg-${name}`;
  const errorId = `${id}-error`;
  const invalid =
    error === undefined ? undefined : { "aria-invalid": true, "aria-describedby": errorId };
  const text = value !== undefined && value !== null ? String(value) : "";
  const placeholder = field.default !== undefined ? String(field.default) : "";

  return (
    <div className="space-y-1.5">
      <Label
        htmlFor={id}
        className="text-foreground/80 text-xs font-medium tracking-wider uppercase"
      >
        {field.label}
        {field.required && <span className="text-destructive ml-0.5">*</span>}
      </Label>

      {field.type === "boolean" ? (
        <div className="flex items-center gap-3 py-1">
          <Switch id={id} checked={!!value} onCheckedChange={onChange} {...invalid} />
          {field.help && <span className="text-foreground/55 text-xs">{field.help}</span>}
        </div>
      ) : field.type === "textarea" ? (
        <>
          <Textarea
            id={id}
            placeholder={placeholder}
            value={text}
            onChange={(e) => onChange(e.target.value)}
            className="min-h-[160px] rounded-xl font-mono text-xs"
            spellCheck={false}
            {...invalid}
          />
          {field.help && <p className="text-foreground/55 text-xs">{field.help}</p>}
        </>
      ) : (
        <>
          <Input
            id={id}
            type={field.secret ? "password" : field.type === "integer" ? "number" : "text"}
            placeholder={placeholder}
            value={text}
            onChange={(e) =>
              onChange(
                field.type === "integer"
                  ? e.target.value
                    ? Number(e.target.value)
                    : ""
                  : e.target.value,
              )
            }
            className="h-10 rounded-xl"
            {...invalid}
          />
          {field.help && <p className="text-foreground/55 text-xs">{field.help}</p>}
        </>
      )}

      {error !== undefined && (
        <p id={errorId} className="text-destructive text-xs">
          {error}
        </p>
      )}
    </div>
  );
}
