"use client";

import { Check } from "lucide-react";
import { useTranslations } from "next-intl";

import { Input, Label } from "@/components/ui";
import { ConnectorIcon } from "@/components/rag/connector-icon";
import type { ConnectorInfo, SyncSourceCreate } from "@/lib/rag-api";
import { cn } from "@/lib/utils";

export function ConnectorStep({
  connectors,
  connectorsFailed,
  form,
  setForm,
  locked = false,
}: {
  connectors: ConnectorInfo[];
  connectorsFailed: boolean;
  /** Editing an existing source: its connector is fixed, and choosing another would wipe the config. */
  locked?: boolean;
  form: SyncSourceCreate;
  setForm: React.Dispatch<React.SetStateAction<SyncSourceCreate>>;
}) {
  const t = useTranslations("rag");
  return (
    <div className="space-y-5">
      <div className="space-y-1.5">
        <Label htmlFor="source-name">{t("sourceName")}</Label>
        <Input
          id="source-name"
          placeholder={t("eGEngineeringDocs")}
          value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          className="h-10 rounded-xl"
        />
      </div>

      <div className="space-y-2">
        <Label>{t("connector")}</Label>
        {connectorsFailed ? (
          // "No connectors enabled" is a statement about the deployment; a failed
          // request has not made it.
          <p className="border-destructive/30 text-destructive rounded-xl border px-4 py-3 text-sm">
            {t("connectorLoadFailed")}
          </p>
        ) : connectors.length === 0 ? (
          <p className="border-foreground/10 bg-foreground/[0.03] text-foreground/65 rounded-xl border px-4 py-3 text-sm">
            {t("noConnectorsEnabled")}
          </p>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            {connectors.map((conn) => {
              const isSelected = form.connector_type === conn.type;
              return (
                <button
                  key={conn.type}
                  type="button"
                  disabled={locked}
                  onClick={() => setForm((f) => ({ ...f, connector_type: conn.type, config: {} }))}
                  className={cn(
                    "flex items-center gap-3 rounded-xl border p-3.5 text-left transition-colors",
                    isSelected
                      ? "border-brand bg-brand/[0.06]"
                      : "border-foreground/10 bg-card hover:border-foreground/30",
                  )}
                >
                  <ConnectorIcon type={conn.type} />
                  <div className="min-w-0 flex-1">
                    <p className="text-foreground text-sm font-semibold">{conn.name}</p>
                  </div>
                  {isSelected && <Check className="text-brand h-4 w-4 shrink-0" />}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
