"use client";

import { Cog } from "lucide-react";
import { useTranslations } from "next-intl";

import { SchemaForm } from "@/components/agents/schema-form";
import { DriveFolderPicker } from "@/components/rag/drive-folder-picker";
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
  const hasFields = Object.keys(connector.config_schema.properties ?? {}).length > 0;

  if (!hasFields) {
    return (
      <div className="border-foreground/10 bg-foreground/[0.03] rounded-xl border p-5 text-center">
        <Cog className="text-muted-foreground mx-auto h-6 w-6" />
        <p className="text-foreground/70 mt-3 text-sm">
          {t.rich("configureNoneNeeded", {
            name: connector.name,
            emphasis: (chunks) => <span className="text-foreground font-medium">{chunks}</span>,
          })}
        </p>
      </div>
    );
  }

  // A Drive source read through a connected account browses for its folder, so
  // the id is picked rather than typed. A service account cannot browse anybody's
  // Drive, so it keeps the typed id the schema draws.
  const driveAccount = connector.type === "gdrive" ? form.connected_account_id : null;
  if (driveAccount) {
    return (
      <div className="space-y-4">
        <DriveFolderPicker
          account={driveAccount}
          value={typeof form.config.folder_id === "string" ? form.config.folder_id : ""}
          onSelect={(folderId) =>
            setForm((f) => ({ ...f, config: { ...f.config, folder_id: folderId } }))
          }
          error={errors?.folder_id}
        />
        <SchemaForm
          schema={connector.config_schema}
          value={form.config}
          onChange={(config) => setForm((f) => ({ ...f, config }))}
          idPrefix="cfg"
          errors={errors}
          hiddenFields={["folder_id"]}
        />
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
      {connector.type === "gdrive" && (
        <p className="text-muted-foreground text-sm">{t("driveFolderIdHint")}</p>
      )}
      <SchemaForm
        schema={connector.config_schema}
        value={form.config}
        onChange={(config) => setForm((f) => ({ ...f, config }))}
        idPrefix="cfg"
        errors={errors}
      />
    </div>
  );
}
