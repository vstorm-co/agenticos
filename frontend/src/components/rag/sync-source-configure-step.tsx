"use client";

import { Cog } from "lucide-react";
import { useTranslations } from "next-intl";

import { Input, Label, Switch, Textarea } from "@/components/ui";
import type { ConnectorInfo, SyncSourceCreate } from "@/lib/rag-api";

export function ConfigureStep({
  connector,
  form,
  setForm,
}: {
  connector: ConnectorInfo;
  form: SyncSourceCreate;
  setForm: React.Dispatch<React.SetStateAction<SyncSourceCreate>>;
}) {
  const t = useTranslations("rag");
  const fields = Object.entries(connector.config_schema);

  if (fields.length === 0) {
    return (
      <div className="border-foreground/10 bg-foreground/[0.03] rounded-xl border p-5 text-center">
        <Cog className="text-foreground/45 mx-auto h-6 w-6" />
        <p className="text-foreground/70 mt-3 text-sm">
          No additional configuration needed for{" "}
          <span className="text-foreground font-medium">{connector.name}</span>.
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
        <div key={key} className="space-y-1.5">
          <Label
            htmlFor={`cfg-${key}`}
            className="text-foreground/80 text-xs font-medium tracking-wider uppercase"
          >
            {field.label}
            {field.required && <span className="text-destructive ml-0.5">*</span>}
          </Label>

          {field.type === "boolean" ? (
            <div className="flex items-center gap-3 py-1">
              <Switch
                id={`cfg-${key}`}
                checked={!!form.config[key]}
                onCheckedChange={(val) =>
                  setForm((f) => ({ ...f, config: { ...f.config, [key]: val } }))
                }
              />
              {field.help && <span className="text-foreground/55 text-xs">{field.help}</span>}
            </div>
          ) : field.type === "textarea" ? (
            <>
              <Textarea
                id={`cfg-${key}`}
                placeholder={field.default !== undefined ? String(field.default) : ""}
                value={
                  form.config[key] !== undefined && form.config[key] !== null
                    ? String(form.config[key])
                    : ""
                }
                onChange={(e) =>
                  setForm((f) => ({ ...f, config: { ...f.config, [key]: e.target.value } }))
                }
                className="min-h-[160px] rounded-xl font-mono text-xs"
                spellCheck={false}
              />
              {field.help && <p className="text-foreground/55 text-xs">{field.help}</p>}
            </>
          ) : (
            <>
              <Input
                id={`cfg-${key}`}
                type={field.secret ? "password" : field.type === "integer" ? "number" : "text"}
                placeholder={field.default !== undefined ? String(field.default) : ""}
                value={
                  form.config[key] !== undefined && form.config[key] !== null
                    ? String(form.config[key])
                    : ""
                }
                onChange={(e) => {
                  const val =
                    field.type === "integer"
                      ? e.target.value
                        ? Number(e.target.value)
                        : ""
                      : e.target.value;
                  setForm((f) => ({ ...f, config: { ...f.config, [key]: val } }));
                }}
                className="h-10 rounded-xl"
              />
              {field.help && <p className="text-foreground/55 text-xs">{field.help}</p>}
            </>
          )}
        </div>
      ))}
    </div>
  );
}
