"use client";

import { Cog } from "lucide-react";
import { useTranslations } from "next-intl";

import { SchemaForm } from "@/components/agents/schema-form";
import { connectorConfigToJsonSchema } from "@/lib/connector-schema";
import type { ConnectorInfo, SyncSourceCreate } from "@/lib/rag-api";

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
  const hasFields = Object.keys(connector.config_schema).length > 0;

  if (!hasFields) {
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
          // Muted to match the asterisk SchemaForm actually draws beside a
          // required field; a red one here would promise a mark the fields below
          // do not wear.
          required: (chunks) => <span className="text-muted-foreground">{chunks}</span>,
        })}
      </p>
      <SchemaForm
        schema={connectorConfigToJsonSchema(connector.config_schema)}
        value={form.config}
        onChange={(config) => setForm((f) => ({ ...f, config }))}
        idPrefix="cfg"
        errors={errors}
      />
    </div>
  );
}
